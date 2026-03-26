import { DateTime } from 'luxon'
import { Pool } from 'pg'
import { RRule } from 'rrule'

import { KAFKA_CDP_BATCH_HOGFLOW_REQUESTS } from '~/config/kafka-topics'
import { KafkaProducerWrapper } from '~/kafka/producer'
import {
    HealthCheckResult,
    HealthCheckResultError,
    HealthCheckResultOk,
    PluginServerService,
    PluginsServerConfig,
} from '~/types'
import { logger } from '~/utils/logger'

interface DueSchedule {
    id: string
    next_run_at: Date
    hog_flow_id: string
    team_id: number
    rrule: string
    starts_at: Date
    timezone: string
    variables: Record<string, unknown>
}

interface HogFlowRow {
    status: string
    trigger: Record<string, unknown>
    variables: Array<{ key: string; default?: unknown }> | null
}

export class HogFlowScheduleService {
    private pool: Pool
    private kafkaProducer: KafkaProducerWrapper | null = null
    private intervalHandle: ReturnType<typeof setInterval> | null = null
    private readonly pollIntervalMs: number
    private readonly batchSize: number

    constructor(private config: PluginsServerConfig) {
        this.pool = new Pool({
            connectionString: config.DATABASE_URL,
            max: 5,
            idleTimeoutMillis: 30000,
        })
        this.pollIntervalMs = 60_000
        this.batchSize = 100
    }

    async start(): Promise<void> {
        const client = await this.pool.connect()
        client.release()

        this.kafkaProducer = await KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK)

        this.intervalHandle = setInterval(() => {
            this.pollAndDispatch().catch((err) => {
                logger.error('HogFlowScheduleService poll error', { error: String(err) })
            })
        }, this.pollIntervalMs)

        await this.pollAndDispatch()
    }

    async pollAndDispatch(): Promise<void> {
        const client = await this.pool.connect()
        try {
            await client.query('BEGIN')

            // Query due schedules directly from HogFlowSchedule
            const result = await client.query<DueSchedule>(
                `SELECT s.id, s.next_run_at, s.hog_flow_id::text as hog_flow_id, s.team_id,
                        s.rrule, s.starts_at, s.timezone, s.variables
                 FROM workflows_hogflowschedule s
                 WHERE s.status = 'active'
                   AND s.next_run_at IS NOT NULL
                   AND s.next_run_at <= NOW()
                 ORDER BY s.next_run_at ASC
                 LIMIT $1
                 FOR UPDATE OF s SKIP LOCKED`,
                [this.batchSize]
            )

            for (const schedule of result.rows) {
                try {
                    const hogFlowResult = await client.query<HogFlowRow>(
                        `SELECT status, trigger, variables FROM posthog_hogflow WHERE id = $1`,
                        [schedule.hog_flow_id]
                    )

                    if (!hogFlowResult.rows.length || hogFlowResult.rows[0].status !== 'active') {
                        // Workflow no longer active, clear next_run_at
                        await client.query(
                            `UPDATE workflows_hogflowschedule SET next_run_at = NULL, updated_at = NOW() WHERE id = $1`,
                            [schedule.id]
                        )
                        continue
                    }

                    const hogFlow = hogFlowResult.rows[0]
                    const triggerType = (hogFlow.trigger as Record<string, unknown>)?.type

                    if (triggerType === 'batch') {
                        await this.dispatchBatchTrigger(schedule, hogFlow)
                    } else {
                        await client.query(
                            `UPDATE workflows_hogflowschedule SET next_run_at = NULL, updated_at = NOW() WHERE id = $1`,
                            [schedule.id]
                        )
                        continue
                    }

                    // Compute and set next_run_at
                    const nextRunAt = this.computeNextOccurrence(
                        schedule.rrule,
                        new Date(schedule.starts_at),
                        new Date(schedule.next_run_at),
                        schedule.timezone
                    )

                    if (nextRunAt) {
                        await client.query(
                            `UPDATE workflows_hogflowschedule SET next_run_at = $2, updated_at = NOW() WHERE id = $1`,
                            [schedule.id, nextRunAt]
                        )
                    } else {
                        // RRULE exhausted
                        await client.query(
                            `UPDATE workflows_hogflowschedule
                             SET status = 'completed', next_run_at = NULL, updated_at = NOW()
                             WHERE id = $1`,
                            [schedule.id]
                        )
                    }
                } catch (err) {
                    logger.error('HogFlowScheduleService: failed to process schedule', {
                        scheduleId: schedule.id,
                        error: String(err),
                    })
                    // Clear next_run_at to prevent retry loop, will be re-synced on next save
                    await client.query(
                        `UPDATE workflows_hogflowschedule SET next_run_at = NULL, updated_at = NOW() WHERE id = $1`,
                        [schedule.id]
                    )
                }
            }

            await client.query('COMMIT')
        } catch (err) {
            await client.query('ROLLBACK')
            throw err
        } finally {
            client.release()
        }
    }

    private async dispatchBatchTrigger(schedule: DueSchedule, hogFlow: HogFlowRow): Promise<void> {
        if (!this.kafkaProducer) {
            throw new Error('Kafka producer not available')
        }

        const filters = (hogFlow.trigger as Record<string, unknown>)?.filters as Record<string, unknown> | undefined
        const resolvedVariables = this.resolveVariables(hogFlow.variables, schedule.variables)

        const batchHogFlowRequest = {
            teamId: schedule.team_id,
            hogFlowId: schedule.hog_flow_id,
            parentRunId: null,
            filters: {
                properties: (filters?.properties as unknown[]) || [],
                filter_test_accounts: false,
            },
            variables: resolvedVariables,
        }

        await this.kafkaProducer.produce({
            topic: KAFKA_CDP_BATCH_HOGFLOW_REQUESTS,
            value: Buffer.from(JSON.stringify(batchHogFlowRequest)),
            key: `${schedule.team_id}_${schedule.hog_flow_id}`,
        })

        logger.info('HogFlowScheduleService: dispatched batch trigger', {
            scheduleId: schedule.id,
            hogFlowId: schedule.hog_flow_id,
            teamId: schedule.team_id,
        })
    }

    private resolveVariables(
        hogFlowVariables: Array<{ key: string; default?: unknown }> | null,
        scheduleVariables: Record<string, unknown>
    ): Record<string, unknown> {
        const defaults: Record<string, unknown> = {}
        for (const variable of hogFlowVariables || []) {
            defaults[variable.key] = variable.default ?? null
        }
        return { ...defaults, ...scheduleVariables }
    }

    private computeNextOccurrence(
        rruleStr: string,
        startsAt: Date,
        after: Date,
        timezone: string = 'UTC'
    ): Date | null {
        const startsAtLocal = DateTime.fromJSDate(startsAt, { zone: 'utc' }).setZone(timezone)
        const dtstart = new Date(
            Date.UTC(
                startsAtLocal.year,
                startsAtLocal.month - 1,
                startsAtLocal.day,
                startsAtLocal.hour,
                startsAtLocal.minute,
                startsAtLocal.second
            )
        )

        const parsed = RRule.fromString(rruleStr)
        const rule = new RRule({ ...parsed.origOptions, dtstart })

        const afterLocal = DateTime.fromJSDate(after, { zone: 'utc' }).setZone(timezone)
        const afterFakeUtc = new Date(
            Date.UTC(
                afterLocal.year,
                afterLocal.month - 1,
                afterLocal.day,
                afterLocal.hour,
                afterLocal.minute,
                afterLocal.second
            )
        )

        const upperBound = new Date(afterFakeUtc.getTime() + 365 * 24 * 60 * 60 * 1000 * 10)
        const occurrences = rule.between(afterFakeUtc, upperBound, false)

        if (occurrences.length === 0) {
            return null
        }

        const next = occurrences[0]
        const localDt = DateTime.fromObject(
            {
                year: next.getUTCFullYear(),
                month: next.getUTCMonth() + 1,
                day: next.getUTCDate(),
                hour: next.getUTCHours(),
                minute: next.getUTCMinutes(),
                second: next.getUTCSeconds(),
            },
            { zone: timezone }
        )
        return localDt.toUTC().toJSDate()
    }

    isRunning(): boolean {
        return this.intervalHandle !== null
    }

    async stop(): Promise<void> {
        if (this.intervalHandle) {
            clearInterval(this.intervalHandle)
            this.intervalHandle = null
        }
        await this.kafkaProducer?.disconnect()
        await this.pool.end()
    }

    isHealthy(): HealthCheckResult {
        if (!this.isRunning()) {
            return new HealthCheckResultError('HogFlowScheduleService interval is not running', {})
        }
        return new HealthCheckResultOk()
    }

    get service(): PluginServerService {
        return {
            id: 'cdp-hogflow-scheduler',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }
}
