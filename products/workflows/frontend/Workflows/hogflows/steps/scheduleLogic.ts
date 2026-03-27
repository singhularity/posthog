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

const DEBOUNCE_MS = 1500

export const scheduleLogic = kea<scheduleLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'hogflows', 'steps', 'scheduleLogic']),
    props({} as ScheduleLogicProps),
    key((props) => props.workflowId),

    actions({
        setDraftSchedule: (schedule: Omit<ScheduleConfig, 'id' | 'status' | 'next_run_at'> | null) => ({ schedule }),
        debouncedSave: true,
        doSave: true,
        doDelete: true,
        setSaveStatus: (status: 'idle' | 'unsaved' | 'saving' | 'saved' | 'error') => ({ status }),
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
            'idle' as 'idle' | 'unsaved' | 'saving' | 'saved' | 'error',
            {
                setSaveStatus: (_, { status }) => status,
            },
        ],
        draftSchedule: [
            undefined as Omit<ScheduleConfig, 'id' | 'status' | 'next_run_at'> | null | undefined,
            {
                setDraftSchedule: (_, { schedule }) => schedule,
                loadSchedulesSuccess: () => undefined,
            },
        ],
    }),

    selectors({
        currentSchedule: [(s) => [s.schedules], (schedules): ScheduleConfig | null => schedules[0] ?? null],
    }),

    listeners(({ actions, props, values, cache }) => ({
        setDraftSchedule: () => {
            actions.setSaveStatus('unsaved')
            actions.debouncedSave()
        },

        debouncedSave: () => {
            if (cache.debounceTimeout) {
                clearTimeout(cache.debounceTimeout)
            }
            cache.debounceTimeout = setTimeout(() => {
                if (values.draftSchedule === null) {
                    actions.doDelete()
                } else if (values.draftSchedule !== undefined) {
                    actions.doSave()
                }
            }, DEBOUNCE_MS)
        },

        doSave: async () => {
            if (!props.workflowId || props.workflowId === 'new' || values.draftSchedule === undefined) {
                return
            }

            const projectId = teamLogic.values.currentTeamId
            const baseUrl = `api/projects/${projectId}/hog_flows/${props.workflowId}/schedules/`

            actions.setSaveStatus('saving')
            try {
                const existing = values.currentSchedule
                if (existing?.id) {
                    await api.update(`${baseUrl}${existing.id}/`, values.draftSchedule)
                } else {
                    await api.create(baseUrl, values.draftSchedule)
                }
                actions.loadSchedules()
                actions.setSaveStatus('saved')
                setTimeout(() => actions.setSaveStatus('idle'), 2000)
            } catch {
                actions.setSaveStatus('error')
                setTimeout(() => actions.setSaveStatus('idle'), 3000)
            }
        },

        doDelete: async () => {
            const existing = values.currentSchedule
            if (!existing?.id) {
                actions.setSaveStatus('idle')
                return
            }

            const projectId = teamLogic.values.currentTeamId
            const url = `api/projects/${projectId}/hog_flows/${props.workflowId}/schedules/${existing.id}/`

            actions.setSaveStatus('saving')
            try {
                await api.delete(url)
                actions.loadSchedules()
                actions.setSaveStatus('saved')
                setTimeout(() => actions.setSaveStatus('idle'), 2000)
            } catch {
                actions.setSaveStatus('error')
                setTimeout(() => actions.setSaveStatus('idle'), 3000)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadSchedules()
    }),
])
