import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { scheduleLogicType } from './scheduleLogicType'

export interface ScheduleConfig {
    id?: string
    rrule: string
    starts_at: string
    timezone?: string
    variables?: Record<string, unknown>
    status?: string
    next_run_at?: string | null
}

export interface ScheduleLogicProps {
    workflowId: string
}

export const scheduleLogic = kea<scheduleLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'hogflows', 'steps', 'scheduleLogic']),
    props({} as ScheduleLogicProps),
    key((props) => props.workflowId),

    actions({
        saveSchedule: (schedule: Omit<ScheduleConfig, 'id' | 'status' | 'next_run_at'>) => ({ schedule }),
        deleteSchedule: (scheduleId: string) => ({ scheduleId }),
        setSaveStatus: (status: 'idle' | 'saving' | 'saved' | 'error') => ({ status }),
    }),

    loaders(({ props }) => ({
        schedules: [
            [] as ScheduleConfig[],
            {
                loadSchedules: async () => {
                    if (!props.workflowId || props.workflowId === 'new') {
                        return []
                    }
                    const projectId = teamLogic.values.currentTeamId
                    const response = await api.get(`api/projects/${projectId}/hog_flows/${props.workflowId}/schedules/`)
                    return response.results ?? response
                },
            },
        ],
    })),

    reducers({
        saveStatus: [
            'idle' as 'idle' | 'saving' | 'saved' | 'error',
            {
                setSaveStatus: (_, { status }) => status,
            },
        ],
    }),

    selectors({
        currentSchedule: [(s) => [s.schedules], (schedules): ScheduleConfig | null => schedules[0] ?? null],
    }),

    listeners(({ actions, props, values }) => ({
        saveSchedule: async ({ schedule }) => {
            if (!props.workflowId || props.workflowId === 'new') {
                return
            }

            const projectId = teamLogic.values.currentTeamId
            const baseUrl = `api/projects/${projectId}/hog_flows/${props.workflowId}/schedules/`

            actions.setSaveStatus('saving')
            try {
                const existing = values.currentSchedule
                if (existing?.id) {
                    await api.update(`${baseUrl}${existing.id}/`, schedule)
                } else {
                    await api.create(baseUrl, schedule)
                }
                actions.loadSchedules()
                actions.setSaveStatus('saved')
                setTimeout(() => actions.setSaveStatus('idle'), 2000)
            } catch {
                actions.setSaveStatus('error')
                setTimeout(() => actions.setSaveStatus('idle'), 3000)
            }
        },

        deleteSchedule: async ({ scheduleId }) => {
            const projectId = teamLogic.values.currentTeamId
            const url = `api/projects/${projectId}/hog_flows/${props.workflowId}/schedules/${scheduleId}/`
            await api.delete(url)
            actions.loadSchedules()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadSchedules()
    }),
])
