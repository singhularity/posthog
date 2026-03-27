import { parseJSON } from '~/utils/json-parse'

import { HogFlowScheduleService } from './hogflow-schedule.service'

const mockProduce = jest.fn()
const mockDisconnect = jest.fn()

jest.mock('~/kafka/producer', () => ({
    KafkaProducerWrapper: {
        create: jest.fn().mockResolvedValue({
            produce: mockProduce,
            disconnect: mockDisconnect,
        }),
    },
}))

const mockFetch = jest.fn()
jest.mock('~/common/services/internal-fetch', () => ({
    InternalFetchService: jest.fn().mockImplementation(() => ({
        fetch: mockFetch,
    })),
}))

const config = {
    SITE_URL: 'http://localhost:8000',
    INTERNAL_API_SECRET: 'test-secret',
    KAFKA_CLIENT_RACK: undefined,
} as any

describe('HogFlowScheduleService', () => {
    let service: HogFlowScheduleService

    beforeEach(() => {
        jest.clearAllMocks()
        service = new HogFlowScheduleService(config)
    })

    describe('pollAndDispatch', () => {
        it('produces correct Kafka message for processed schedules', async () => {
            mockFetch.mockResolvedValue({
                fetchResponse: {
                    status: 200,
                    text: () =>
                        JSON.stringify({
                            processed: [
                                {
                                    schedule_id: 'schedule-1',
                                    team_id: 1,
                                    hog_flow_id: 'flow-1',
                                    filters: { properties: [{ key: 'email', value: '@posthog.com' }] },
                                    variables: { greeting: 'Hello' },
                                },
                            ],
                            initialized: [],
                            failed: [],
                        }),
                },
                fetchError: null,
            })

            await service.start()

            expect(mockProduce).toHaveBeenCalledWith({
                topic: expect.stringContaining('cdp_batch_hogflow_requests'),
                value: expect.any(Buffer),
                key: '1_flow-1',
            })

            const producedValue = parseJSON(mockProduce.mock.calls[0][0].value.toString())
            expect(producedValue).toEqual({
                teamId: 1,
                hogFlowId: 'flow-1',
                parentRunId: null,
                filters: {
                    properties: [{ key: 'email', value: '@posthog.com' }],
                    filter_test_accounts: false,
                },
                variables: { greeting: 'Hello' },
            })
        })

        it('does not produce to Kafka when no schedules are due', async () => {
            mockFetch.mockResolvedValue({
                fetchResponse: {
                    status: 200,
                    text: () => JSON.stringify({ processed: [], initialized: [], failed: [] }),
                },
                fetchError: null,
            })

            await service.start()

            expect(mockProduce).not.toHaveBeenCalled()
        })

        it('does not produce to Kafka when endpoint returns error', async () => {
            mockFetch.mockResolvedValue({
                fetchResponse: {
                    status: 500,
                    text: () => 'Internal Server Error',
                },
                fetchError: null,
            })

            await service.start()

            expect(mockProduce).not.toHaveBeenCalled()
        })

        it('does not produce to Kafka when fetch fails', async () => {
            mockFetch.mockResolvedValue({
                fetchResponse: null,
                fetchError: new Error('Connection refused'),
            })

            await service.start()

            expect(mockProduce).not.toHaveBeenCalled()
        })

        it('continues dispatching other schedules when one fails', async () => {
            mockFetch.mockResolvedValue({
                fetchResponse: {
                    status: 200,
                    text: () =>
                        JSON.stringify({
                            processed: [
                                { schedule_id: 's1', team_id: 1, hog_flow_id: 'f1', filters: {}, variables: {} },
                                { schedule_id: 's2', team_id: 2, hog_flow_id: 'f2', filters: {}, variables: {} },
                            ],
                            initialized: [],
                            failed: [],
                        }),
                },
                fetchError: null,
            })

            mockProduce.mockRejectedValueOnce(new Error('Kafka error')).mockResolvedValueOnce(undefined)

            await service.start()

            expect(mockProduce).toHaveBeenCalledTimes(2)
        })
    })

    describe('lifecycle', () => {
        it('reports healthy when running', async () => {
            mockFetch.mockResolvedValue({
                fetchResponse: { status: 200, text: () => '{"processed":[],"initialized":[],"failed":[]}' },
                fetchError: null,
            })

            await service.start()
            expect(service.isHealthy().status).toBe('ok')
        })

        it('reports unhealthy when not running', () => {
            expect(service.isHealthy().status).toBe('error')
        })
    })
})
