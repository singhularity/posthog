import { INTERNAL_SERVICE_CALL_HEADER_NAME } from '~/api/middleware/internal-api-auth'
import { KAFKA_CDP_BATCH_HOGFLOW_REQUESTS } from '~/config/kafka-topics'
import { KafkaProducerWrapper } from '~/kafka/producer'
import {
    HealthCheckResult,
    HealthCheckResultError,
    HealthCheckResultOk,
    PluginServerService,
    PluginsServerConfig,
} from '~/types'
import { parseJSON } from '~/utils/json-parse'
import { logger } from '~/utils/logger'
import { internalFetch } from '~/utils/request'

interface ProcessedSchedule {
    schedule_id: string
    team_id: number
    hog_flow_id: string
    trigger_type: string
    filters: Record<string, unknown>
    variables: Record<string, unknown>
}

interface ProcessDueSchedulesResponse {
    processed: ProcessedSchedule[]
    initialized: string[]
}

export class HogFlowScheduleService {
    private kafkaProducer: KafkaProducerWrapper | null = null
    private intervalHandle: ReturnType<typeof setInterval> | null = null
    private readonly pollIntervalMs: number
    private readonly internalApiBaseUrl: string
    private readonly internalApiSecret: string

    constructor(private config: PluginsServerConfig) {
        this.pollIntervalMs = 60_000
        this.internalApiBaseUrl = config.SITE_URL || 'http://localhost:8000'
        this.internalApiSecret = config.INTERNAL_API_SECRET || 'posthog123'
    }

    async start(): Promise<void> {
        this.kafkaProducer = await KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK)

        this.intervalHandle = setInterval(() => {
            this.pollAndDispatch().catch((err) => {
                logger.error('HogFlowScheduleService poll error', { error: String(err) })
            })
        }, this.pollIntervalMs)

        await this.pollAndDispatch()
    }

    async pollAndDispatch(): Promise<void> {
        try {
            const url = `${this.internalApiBaseUrl}/api/internal/hog_flows/process_due_schedules`
            const response = await internalFetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    [INTERNAL_SERVICE_CALL_HEADER_NAME]: this.internalApiSecret,
                },
                body: JSON.stringify({ batch_size: 100 }),
            })

            if (response.status !== 200) {
                const errorText = await response.text()
                logger.error('HogFlowScheduleService: Django endpoint returned error', {
                    status: response.status,
                    error: errorText,
                })
                return
            }

            const data = parseJSON(await response.text()) as ProcessDueSchedulesResponse

            if (data.initialized.length > 0) {
                logger.info('HogFlowScheduleService: initialized schedules', {
                    count: data.initialized.length,
                })
            }

            for (const schedule of data.processed) {
                if (schedule.trigger_type === 'batch') {
                    await this.dispatchBatchTrigger(schedule)
                }
            }

            if (data.processed.length > 0) {
                logger.info('HogFlowScheduleService: processed due schedules', {
                    count: data.processed.length,
                })
            }
        } catch (err) {
            logger.error('HogFlowScheduleService: failed to poll', { error: String(err) })
        }
    }

    private async dispatchBatchTrigger(schedule: ProcessedSchedule): Promise<void> {
        if (!this.kafkaProducer) {
            throw new Error('Kafka producer not available')
        }

        const batchHogFlowRequest = {
            teamId: schedule.team_id,
            hogFlowId: schedule.hog_flow_id,
            parentRunId: null,
            filters: {
                properties: (schedule.filters?.properties as unknown[]) || [],
                filter_test_accounts: false,
            },
            variables: schedule.variables,
        }

        await this.kafkaProducer.produce({
            topic: KAFKA_CDP_BATCH_HOGFLOW_REQUESTS,
            value: Buffer.from(JSON.stringify(batchHogFlowRequest)),
            key: `${schedule.team_id}_${schedule.hog_flow_id}`,
        })

        logger.info('HogFlowScheduleService: dispatched batch trigger', {
            scheduleId: schedule.schedule_id,
            hogFlowId: schedule.hog_flow_id,
            teamId: schedule.team_id,
        })
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
