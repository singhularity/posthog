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

interface DueRun {
    id: string
    run_at: Date
    hog_flow_id: string
    team_id: number
    schedule_id: string | null
}

interface HogFlowRow {
    status: string
    trigger: Record<string, unknown>
    variables: Array<{ key: string; default?: unknown }> | null
}

interface ScheduleRow {
    id: string
    rrule: string
    starts_at: Date
    timezone: string
    variables: Record<string, unknown>
    status: string
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

            const result = await client.query<DueRun>(
                `SELECT r.id, r.run_at, r.hog_flow_id::text as hog_flow_id, r.team_id,
                        r.schedule_id::text as schedule_id
                 FROM workflows_hogflowscheduledrun r
                 WHERE r.status = 'pending'
                   AND r.run_at <= NOW()
                 ORDER BY r.run_at ASC
                 LIMIT $1
                 FOR UPDATE OF r SKIP LOCKED`,
                [this.batchSize]
            )

            for (const run of result.rows) {
                try {
                    const hogFlowResult = await client.query<HogFlowRow>(
                        `SELECT status, trigger, variables FROM posthog_hogflow WHERE id = $1`,
                        [run.hog_flow_id]
                    )

                    if (!hogFlowResult.rows.length || hogFlowResult.rows[0].status !== 'active') {
                        await client.query(
                            `UPDATE workflows_hogflowscheduledrun
                             SET status = 'failed', completed_at = NOW(), updated_at = NOW(),
                                 failure_reason = 'Workflow not active'
                             WHERE id = $1`,
                            [run.id]
                        )
                        continue
                    }

                    const hogFlow = hogFlowResult.rows[0]
                    const triggerType = (hogFlow.trigger as Record<string, unknown>)?.type

                    if (triggerType === 'batch') {
                        await this.dispatchBatchTrigger(run, hogFlow.trigger as Record<string, unknown>)
                    } else {
                        await client.query(
                            `UPDATE workflows_hogflowscheduledrun
                             SET status = 'failed', completed_at = NOW(), updated_at = NOW(),
                                 failure_reason = $2
                             WHERE id = $1`,
                            [run.id, `Unsupported trigger type: ${triggerType}`]
                        )
                        continue
                    }

                    // Mark as completed
                    await client.query(
                        `UPDATE workflows_hogflowscheduledrun
                         SET status = 'completed', completed_at = NOW(), updated_at = NOW()
                         WHERE id = $1`,
                        [run.id]
                    )

                    // Create the next pending run from the schedule
                    if (run.schedule_id) {
                        await this.createNextPendingRun(client, run, hogFlow)
                    }
                } catch (err) {
                    logger.error('HogFlowScheduleService: failed to process run', {
                        runId: run.id,
                        error: String(err),
                    })
                    await client.query(
                        `UPDATE workflows_hogflowscheduledrun
                         SET status = 'failed', completed_at = NOW(), updated_at = NOW(),
                             failure_reason = $2
                         WHERE id = $1`,
                        [run.id, String(err)]
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

    private async dispatchBatchTrigger(run: DueRun, trigger: Record<string, unknown>): Promise<void> {
        if (!this.kafkaProducer) {
            throw new Error('Kafka producer not available')
        }

        const filters = trigger.filters as Record<string, unknown> | undefined

        const batchHogFlowRequest = {
            teamId: run.team_id,
            hogFlowId: run.hog_flow_id,
            parentRunId: null,
            filters: {
                properties: (filters?.properties as unknown[]) || [],
                filter_test_accounts: false,
            },
        }

        await this.kafkaProducer.produce({
            topic: KAFKA_CDP_BATCH_HOGFLOW_REQUESTS,
            value: Buffer.from(JSON.stringify(batchHogFlowRequest)),
            key: `${run.team_id}_${run.hog_flow_id}`,
        })

        logger.info('HogFlowScheduleService: dispatched batch trigger', {
            runId: run.id,
            hogFlowId: run.hog_flow_id,
            teamId: run.team_id,
        })
    }

    private async createNextPendingRun(client: any, completedRun: DueRun, hogFlow: HogFlowRow): Promise<void> {
        // Fetch the schedule that produced this run
        const scheduleResult = await client.query<ScheduleRow>(
            `SELECT id, rrule, starts_at, timezone, variables, status
             FROM workflows_hogflowschedule
             WHERE id = $1`,
            [completedRun.schedule_id]
        )

        if (!scheduleResult.rows.length || scheduleResult.rows[0].status !== 'active') {
            return
        }

        const schedule = scheduleResult.rows[0]
        const nextRunAt = this.computeNextOccurrence(
            schedule.rrule,
            new Date(schedule.starts_at),
            new Date(completedRun.run_at),
            schedule.timezone
        )

        if (!nextRunAt) {
            // RRULE exhausted, mark schedule as completed
            await client.query(
                `UPDATE workflows_hogflowschedule SET status = 'completed', updated_at = NOW() WHERE id = $1`,
                [schedule.id]
            )
            return
        }

        // Resolve variables: HogFlow defaults merged with schedule overrides
        const resolvedVariables = this.resolveVariables(hogFlow.variables, schedule.variables)

        await client.query(
            `INSERT INTO workflows_hogflowscheduledrun
             (id, team_id, hog_flow_id, schedule_id, run_at, status, variables, created_at, updated_at)
             VALUES (gen_random_uuid(), $1, $2, $3, $4, 'pending', $5, NOW(), NOW())`,
            [completedRun.team_id, completedRun.hog_flow_id, schedule.id, nextRunAt, JSON.stringify(resolvedVariables)]
        )
    }

    private resolveVariables(
        hogFlowVariables: Array<{ key: string; default?: unknown }> | null,
        scheduleVariables: Record<string, unknown>
    ): Record<string, unknown> {
        const defaults: Record<string, unknown> = {}
        for (const v of hogFlowVariables || []) {
            defaults[v.key] = v.default ?? null
        }
        return { ...defaults, ...scheduleVariables }
    }

    private computeNextOccurrence(
        rruleStr: string,
        startsAt: Date,
        after: Date,
        timezone: string = 'UTC'
    ): Date | null {
        // Convert startsAt to the schedule's timezone for RRULE expansion
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

        // Convert after to the same "fake UTC" representation
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

        // Use between() which respects COUNT/UNTIL
        const upperBound = new Date(afterFakeUtc.getTime() + 365 * 24 * 60 * 60 * 1000 * 10)
        const occurrences = rule.between(afterFakeUtc, upperBound, false)

        if (occurrences.length === 0) {
            return null
        }

        // Convert back from "fake UTC" to actual UTC
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
