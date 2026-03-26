/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create a new MCP feedback submission for the current project.
 */
export const McpAnalyticsFeedbackCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const mcpAnalyticsFeedbackCreateBodyAttemptedToolDefault = ``
export const mcpAnalyticsFeedbackCreateBodyMcpClientNameDefault = ``
export const mcpAnalyticsFeedbackCreateBodyMcpClientVersionDefault = ``
export const mcpAnalyticsFeedbackCreateBodyMcpProtocolVersionDefault = ``
export const mcpAnalyticsFeedbackCreateBodyMcpTransportDefault = ``
export const mcpAnalyticsFeedbackCreateBodyMcpSessionIdDefault = ``
export const mcpAnalyticsFeedbackCreateBodyMcpTraceIdDefault = ``
export const mcpAnalyticsFeedbackCreateBodyCategoryDefault = `other`

export const McpAnalyticsFeedbackCreateBody = /* @__PURE__ */ zod.object({
    attempted_tool: zod
        .string()
        .default(mcpAnalyticsFeedbackCreateBodyAttemptedToolDefault)
        .describe('The tool the user tried before leaving feedback, if known.'),
    mcp_client_name: zod
        .string()
        .default(mcpAnalyticsFeedbackCreateBodyMcpClientNameDefault)
        .describe('MCP client name, for example Claude Desktop or Cursor.'),
    mcp_client_version: zod
        .string()
        .default(mcpAnalyticsFeedbackCreateBodyMcpClientVersionDefault)
        .describe('Version string for the MCP client when available.'),
    mcp_protocol_version: zod
        .string()
        .default(mcpAnalyticsFeedbackCreateBodyMcpProtocolVersionDefault)
        .describe('MCP protocol version negotiated for the session when available.'),
    mcp_transport: zod
        .string()
        .default(mcpAnalyticsFeedbackCreateBodyMcpTransportDefault)
        .describe('Transport used for the MCP session, for example streamable_http or sse.'),
    mcp_session_id: zod
        .string()
        .default(mcpAnalyticsFeedbackCreateBodyMcpSessionIdDefault)
        .describe('Stable MCP session identifier when available.'),
    mcp_trace_id: zod
        .string()
        .default(mcpAnalyticsFeedbackCreateBodyMcpTraceIdDefault)
        .describe('Trace identifier for the surrounding MCP workflow when available.'),
    goal: zod.string().describe("The user's intended outcome when using MCP."),
    feedback: zod.string().describe('Concrete feedback about the MCP experience, tool result, or workflow friction.'),
    category: zod
        .enum(['results', 'usability', 'bug', 'docs', 'other'])
        .describe('* `results` - Results\n* `usability` - Usability\n* `bug` - Bug\n* `docs` - Docs\n* `other` - Other')
        .default(mcpAnalyticsFeedbackCreateBodyCategoryDefault)
        .describe(
            'High-level category for the feedback.\n\n* `results` - Results\n* `usability` - Usability\n* `bug` - Bug\n* `docs` - Docs\n* `other` - Other'
        ),
})

/**
 * Create a new missing capability report for the current project.
 */
export const McpAnalyticsMissingCapabilitiesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const mcpAnalyticsMissingCapabilitiesCreateBodyAttemptedToolDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpClientNameDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpClientVersionDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpProtocolVersionDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpTransportDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpSessionIdDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpTraceIdDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyBlockedDefault = true

export const McpAnalyticsMissingCapabilitiesCreateBody = /* @__PURE__ */ zod.object({
    attempted_tool: zod
        .string()
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyAttemptedToolDefault)
        .describe('The tool the user tried before leaving feedback, if known.'),
    mcp_client_name: zod
        .string()
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyMcpClientNameDefault)
        .describe('MCP client name, for example Claude Desktop or Cursor.'),
    mcp_client_version: zod
        .string()
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyMcpClientVersionDefault)
        .describe('Version string for the MCP client when available.'),
    mcp_protocol_version: zod
        .string()
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyMcpProtocolVersionDefault)
        .describe('MCP protocol version negotiated for the session when available.'),
    mcp_transport: zod
        .string()
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyMcpTransportDefault)
        .describe('Transport used for the MCP session, for example streamable_http or sse.'),
    mcp_session_id: zod
        .string()
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyMcpSessionIdDefault)
        .describe('Stable MCP session identifier when available.'),
    mcp_trace_id: zod
        .string()
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyMcpTraceIdDefault)
        .describe('Trace identifier for the surrounding MCP workflow when available.'),
    goal: zod.string().describe("The user's intended outcome when using MCP."),
    missing_capability: zod.string().describe('Capability, tool, or workflow support that is currently missing.'),
    blocked: zod
        .boolean()
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyBlockedDefault)
        .describe("Whether the missing capability blocked the user's progress."),
})
