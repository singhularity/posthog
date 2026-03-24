import { z } from 'zod'

import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

interface QueryWrapperConfig<T extends ZodObjectAny> {
    name: string
    schema: T
    kind: string
    uiResourceUri?: string
    /** Values merged into the query body alongside agent-provided params. */
    fixedProperties?: Record<string, unknown>
    /** When set, `_posthogUrl` uses `{baseUrl}{urlPrefix}` instead of `/insights/new?q=...`. */
    urlPrefix?: string
}

export function createQueryWrapper<T extends ZodObjectAny>(config: QueryWrapperConfig<T>): () => ToolBase<T> {
    return () => ({
        name: config.name,
        schema: config.schema,
        handler: async (context: Context, params: z.infer<T>) => {
            const projectId = await context.stateManager.getProjectId()
            const query = { ...params, ...config.fixedProperties, kind: config.kind }
            const result = await context.api.request<{
                results: unknown
                columns?: unknown
                formatted_results?: string
            }>({
                method: 'POST',
                path: `/api/environments/${projectId}/query/`,
                body: { query },
                headers: { 'X-PostHog-Client': 'mcp' },
            })
            const baseUrl = context.api.getProjectBaseUrl(projectId)
            const posthogUrl = config.urlPrefix
                ? `${baseUrl}${config.urlPrefix}`
                : `${baseUrl}/insights/new?q=${encodeURIComponent(JSON.stringify(query))}`
            return {
                results: result.formatted_results ?? result.results,
                _posthogUrl: posthogUrl,
            }
        },
        ...(config.uiResourceUri ? { _meta: { ui: { resourceUri: config.uiResourceUri } } } : {}),
    })
}
