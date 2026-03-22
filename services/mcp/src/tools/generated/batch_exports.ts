// AUTO-GENERATED from products/batch_exports/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    BatchExportsBackfillsCreateBody,
    BatchExportsBackfillsCreateParams,
    BatchExportsCreateBody,
    BatchExportsDestroyParams,
    BatchExportsListQueryParams,
    BatchExportsPartialUpdateBody,
    BatchExportsPartialUpdateParams,
    BatchExportsPauseCreateBody,
    BatchExportsPauseCreateParams,
    BatchExportsRetrieveParams,
    BatchExportsRunsListParams,
    BatchExportsRunsListQueryParams,
    BatchExportsUnpauseCreateBody,
    BatchExportsUnpauseCreateParams,
} from '@/generated/batch_exports/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const BatchExportsListSchema = BatchExportsListQueryParams

const batchExportsList = (): ToolBase<
    typeof BatchExportsListSchema,
    Schemas.PaginatedBatchExportList & { _posthogUrl: string }
> => ({
    name: 'batch-exports-list',
    schema: BatchExportsListSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedBatchExportList>({
            method: 'GET',
            path: `/api/projects/${projectId}/batch_exports/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/batch_exports`,
        }
    },
})

const BatchExportGetSchema = BatchExportsRetrieveParams.omit({ organization_id: true })

const batchExportGet = (): ToolBase<typeof BatchExportGetSchema, Schemas.BatchExport> => ({
    name: 'batch-export-get',
    schema: BatchExportGetSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.BatchExport>({
            method: 'GET',
            path: `/api/projects/${projectId}/batch_exports/${params.id}/`,
        })
        return result
    },
})

const BatchExportCreateSchema = BatchExportsCreateBody

const batchExportCreate = (): ToolBase<typeof BatchExportCreateSchema, Schemas.BatchExport> => ({
    name: 'batch-export-create',
    schema: BatchExportCreateSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.destination !== undefined) {
            body['destination'] = params.destination
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.paused !== undefined) {
            body['paused'] = params.paused
        }
        if (params.last_paused_at !== undefined) {
            body['last_paused_at'] = params.last_paused_at
        }
        if (params.start_at !== undefined) {
            body['start_at'] = params.start_at
        }
        if (params.end_at !== undefined) {
            body['end_at'] = params.end_at
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.timezone !== undefined) {
            body['timezone'] = params.timezone
        }
        if (params.offset_day !== undefined) {
            body['offset_day'] = params.offset_day
        }
        if (params.offset_hour !== undefined) {
            body['offset_hour'] = params.offset_hour
        }
        const result = await context.api.request<Schemas.BatchExport>({
            method: 'POST',
            path: `/api/projects/${projectId}/batch_exports/`,
            body,
        })
        return result
    },
})

const BatchExportUpdateSchema = BatchExportsPartialUpdateParams.omit({ organization_id: true }).extend(
    BatchExportsPartialUpdateBody.shape
)

const batchExportUpdate = (): ToolBase<typeof BatchExportUpdateSchema, Schemas.BatchExport> => ({
    name: 'batch-export-update',
    schema: BatchExportUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.destination !== undefined) {
            body['destination'] = params.destination
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.paused !== undefined) {
            body['paused'] = params.paused
        }
        if (params.last_paused_at !== undefined) {
            body['last_paused_at'] = params.last_paused_at
        }
        if (params.start_at !== undefined) {
            body['start_at'] = params.start_at
        }
        if (params.end_at !== undefined) {
            body['end_at'] = params.end_at
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.timezone !== undefined) {
            body['timezone'] = params.timezone
        }
        if (params.offset_day !== undefined) {
            body['offset_day'] = params.offset_day
        }
        if (params.offset_hour !== undefined) {
            body['offset_hour'] = params.offset_hour
        }
        const result = await context.api.request<Schemas.BatchExport>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/batch_exports/${params.id}/`,
            body,
        })
        return result
    },
})

const BatchExportDeleteSchema = BatchExportsDestroyParams.omit({ organization_id: true })

const batchExportDelete = (): ToolBase<typeof BatchExportDeleteSchema, unknown> => ({
    name: 'batch-export-delete',
    schema: BatchExportDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${projectId}/batch_exports/${params.id}/`,
        })
        return result
    },
})

const BatchExportPauseSchema = BatchExportsPauseCreateParams.omit({ organization_id: true }).extend(
    BatchExportsPauseCreateBody.shape
)

const batchExportPause = (): ToolBase<typeof BatchExportPauseSchema, unknown> => ({
    name: 'batch-export-pause',
    schema: BatchExportPauseSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportPauseSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.destination !== undefined) {
            body['destination'] = params.destination
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.paused !== undefined) {
            body['paused'] = params.paused
        }
        if (params.last_paused_at !== undefined) {
            body['last_paused_at'] = params.last_paused_at
        }
        if (params.start_at !== undefined) {
            body['start_at'] = params.start_at
        }
        if (params.end_at !== undefined) {
            body['end_at'] = params.end_at
        }
        if (params.hogql_query !== undefined) {
            body['hogql_query'] = params.hogql_query
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.timezone !== undefined) {
            body['timezone'] = params.timezone
        }
        if (params.offset_day !== undefined) {
            body['offset_day'] = params.offset_day
        }
        if (params.offset_hour !== undefined) {
            body['offset_hour'] = params.offset_hour
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${projectId}/batch_exports/${params.id}/pause/`,
            body,
        })
        return result
    },
})

const BatchExportUnpauseSchema = BatchExportsUnpauseCreateParams.omit({ organization_id: true }).extend(
    BatchExportsUnpauseCreateBody.shape
)

const batchExportUnpause = (): ToolBase<typeof BatchExportUnpauseSchema, unknown> => ({
    name: 'batch-export-unpause',
    schema: BatchExportUnpauseSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportUnpauseSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.destination !== undefined) {
            body['destination'] = params.destination
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.paused !== undefined) {
            body['paused'] = params.paused
        }
        if (params.last_paused_at !== undefined) {
            body['last_paused_at'] = params.last_paused_at
        }
        if (params.start_at !== undefined) {
            body['start_at'] = params.start_at
        }
        if (params.end_at !== undefined) {
            body['end_at'] = params.end_at
        }
        if (params.hogql_query !== undefined) {
            body['hogql_query'] = params.hogql_query
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.timezone !== undefined) {
            body['timezone'] = params.timezone
        }
        if (params.offset_day !== undefined) {
            body['offset_day'] = params.offset_day
        }
        if (params.offset_hour !== undefined) {
            body['offset_hour'] = params.offset_hour
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${projectId}/batch_exports/${params.id}/unpause/`,
            body,
        })
        return result
    },
})

const BatchExportRunsListSchema = BatchExportsRunsListParams.omit({ project_id: true }).extend(
    BatchExportsRunsListQueryParams.shape
)

const batchExportRunsList = (): ToolBase<
    typeof BatchExportRunsListSchema,
    Schemas.PaginatedBatchExportRunList & { _posthogUrl: string }
> => ({
    name: 'batch-export-runs-list',
    schema: BatchExportRunsListSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportRunsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedBatchExportRunList>({
            method: 'GET',
            path: `/api/projects/${projectId}/batch_exports/${params.batch_export_id}/runs/`,
            query: {
                cursor: params.cursor,
                ordering: params.ordering,
            },
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/batch_exports`,
        }
    },
})

const BatchExportBackfillCreateSchema = BatchExportsBackfillsCreateParams.omit({ project_id: true }).extend(
    BatchExportsBackfillsCreateBody.shape
)

const batchExportBackfillCreate = (): ToolBase<
    typeof BatchExportBackfillCreateSchema,
    Schemas.BatchExportBackfill
> => ({
    name: 'batch-export-backfill-create',
    schema: BatchExportBackfillCreateSchema,
    handler: async (context: Context, params: z.infer<typeof BatchExportBackfillCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.BatchExportBackfill>({
            method: 'POST',
            path: `/api/projects/${projectId}/batch_exports/${params.batch_export_id}/backfills/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'batch-exports-list': batchExportsList,
    'batch-export-get': batchExportGet,
    'batch-export-create': batchExportCreate,
    'batch-export-update': batchExportUpdate,
    'batch-export-delete': batchExportDelete,
    'batch-export-pause': batchExportPause,
    'batch-export-unpause': batchExportUnpause,
    'batch-export-runs-list': batchExportRunsList,
    'batch-export-backfill-create': batchExportBackfillCreate,
}
