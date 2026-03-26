// AUTO-GENERATED from products/mcp_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import {
    McpAnalyticsFeedbackCreateBody,
    McpAnalyticsMissingCapabilitiesCreateBody,
} from '@/generated/mcp_analytics/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const McpFeedbackSubmitSchema = McpAnalyticsFeedbackCreateBody.omit({
    mcp_client_name: true,
    mcp_client_version: true,
    mcp_protocol_version: true,
    mcp_transport: true,
    mcp_session_id: true,
    mcp_trace_id: true,
})

const mcpFeedbackSubmit = (): ToolBase<typeof McpFeedbackSubmitSchema> => ({
    name: 'mcp-feedback-submit',
    schema: McpFeedbackSubmitSchema,
    handler: async (context: Context, params: z.infer<typeof McpFeedbackSubmitSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.attempted_tool !== undefined) {
            body['attempted_tool'] = params.attempted_tool
        }
        if (params.goal !== undefined) {
            body['goal'] = params.goal
        }
        if (params.feedback !== undefined) {
            body['feedback'] = params.feedback
        }
        if (params.category !== undefined) {
            body['category'] = params.category
        }
        const result = await context.api.request({
            method: 'POST',
            path: `/api/environments/${projectId}/mcp_analytics/feedback/`,
            body,
        })
        return result
    },
})

const McpMissingCapabilityReportSchema = McpAnalyticsMissingCapabilitiesCreateBody.omit({
    mcp_client_name: true,
    mcp_client_version: true,
    mcp_protocol_version: true,
    mcp_transport: true,
    mcp_session_id: true,
    mcp_trace_id: true,
})

const mcpMissingCapabilityReport = (): ToolBase<typeof McpMissingCapabilityReportSchema> => ({
    name: 'mcp-missing-capability-report',
    schema: McpMissingCapabilityReportSchema,
    handler: async (context: Context, params: z.infer<typeof McpMissingCapabilityReportSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.attempted_tool !== undefined) {
            body['attempted_tool'] = params.attempted_tool
        }
        if (params.goal !== undefined) {
            body['goal'] = params.goal
        }
        if (params.missing_capability !== undefined) {
            body['missing_capability'] = params.missing_capability
        }
        if (params.blocked !== undefined) {
            body['blocked'] = params.blocked
        }
        const result = await context.api.request({
            method: 'POST',
            path: `/api/environments/${projectId}/mcp_analytics/missing_capabilities/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'mcp-feedback-submit': mcpFeedbackSubmit,
    'mcp-missing-capability-report': mcpMissingCapabilityReport,
}
