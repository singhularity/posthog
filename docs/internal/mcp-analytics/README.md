# MCP Analytics

## Purpose

`mcp_analytics` is a proposed PostHog product focused on one question:

How should a product team improve its product when users increasingly interact with it through MCP instead of a traditional UI or direct API?

For the first iteration, PostHog is customer zero.
We will use this product to understand how people use the PostHog MCP server,
where they fail,
what capabilities they are missing,
and which product decisions we should make because of that data.

This product should reuse LLM Analytics patterns and infrastructure wherever possible.
It should not introduce a separate ingestion stack or a parallel observability model unless we later prove we need one.

## Thesis

- MCP usage of products is increasing.
- Traditional product analytics is weak at explaining MCP-native workflows.
- Product teams need more than counts.
  They need workflow visibility,
  failure diagnosis,
  and unmet-demand signals.
- PostHog already emits enough MCP and AI trace data to validate the thesis without building a new backend first.

## Customer Problem

If a product is being used through MCP,
the product team needs to answer:

- What jobs are people trying to do through MCP?
- Which tools are most used?
- Which workflows succeed?
- Where do users fail?
- Which failures are caused by bad UX,
  missing capabilities,
  auth problems,
  schema problems,
  or underlying product limitations?
- What are users asking for that we do not yet support?

## Product Goal

Help MCP server owners improve their product by giving them an MCP-native view of:

- adoption
- workflows
- failures
- unmet demand
- feedback

The first version only needs to work well for the PostHog MCP server.

## Non-goals

- A generic SDK for third-party MCP servers
- A separate storage system for MCP data
- Pixel-style session replay
- A clone of MCP Cat's full product surface
- Extending `mcp_store` into an analytics product

## Principles

- Reuse LLM Analytics patterns aggressively.
- Prefer filtered views over existing `$ai_trace` and `$ai_span` data.
- Add new instrumentation only when it materially improves product decisions.
- Add unmet-demand capture before intent capture.
- Validate with PostHog's own MCP usage before generalizing the product.

## Existing Foundations

The current PostHog MCP server already emits:

- `mcp tool call`
- `mcp tool response`
- `$ai_trace`
- `$ai_span`

It also already captures or derives:

- MCP session linkage
- MCP client name and version
- MCP protocol version
- transport
- tool-level success and failure
- input and output state for traces and spans

LLM Analytics already provides product patterns for:

- trace lists
- session lists
- tool tables
- error analysis
- feedback views
- detail pages

`mcp_analytics` should start as a product lens over that existing model.

## Validation Questions

We should only invest in this product if it can answer the following with real data:

1. Who is using the PostHog MCP server?
2. Which MCP clients are driving usage?
3. Which tools and workflows matter most?
4. Which failure modes are most common?
5. Which missing capabilities are most requested?
6. Which roadmap decisions should we make because of this data?

## Success Criteria

The product is working if,
within the first few weeks of internal use,
we can consistently produce:

- the top 5 MCP jobs users are trying to accomplish
- the top 5 failure clusters
- the top 5 missing capabilities
- the top MCP clients by usage and friction
- at least 2 concrete PostHog MCP product decisions driven by this data

## Initial Product Surface

The MVP should include only these views:

- Overview
- Tools
- Sessions
- Failures
- Feedback

The MVP does not need:

- evaluations
- datasets
- prompt management
- generalized external-server onboarding
- broad customer-facing configuration

## Proposed Data Model

We should standardize around a minimal MCP event model that fits the current trace pipeline.

Core properties:

- `ai_product = "mcp"`
- `tool`
- `mcp_client_name`
- `mcp_client_version`
- `mcp_protocol_version`
- `mcp_transport`
- `read_only`
- `organization_id_pinned`
- `project_id_pinned`
- `valid_input`
- `outcome`
- `error_type`
- `error_message_normalized`
- `$session_id`
- `$ai_trace_id`

First-pass outcome taxonomy:

- `success`
- `validation_error`
- `auth_error`
- `permission_error`
- `upstream_error`
- `tool_internal_error`

This taxonomy matters because raw exceptions are not enough to drive product decisions.

## Current Instrumentation Inventory

The current PostHog MCP server already captures enough to support a first read-only MVP.

Currently emitted event families:

- `mcp tool call`
- `mcp tool response`
- `$ai_trace`
- `$ai_span`
- `mcp_ui_app_*` events for embedded UI app interactions

Currently captured MCP and trace properties:

- `tool`
- `valid_input`
- `$session_id`
- `$ai_trace_id`
- `$ai_span_id`
- `$ai_parent_id`
- `$ai_span_name`
- `$ai_input_state`
- `$ai_output_state`
- `$ai_latency`
- `$ai_is_error`
- `ai_product = "mcp"`
- `mcp_oauth_client_name`
- `mcp_client_name`
- `mcp_client_version`
- `mcp_protocol_version`
- `mcp_transport`

What this already enables:

- tool usage ranking
- MCP client breakdowns
- trace and session-level inspection
- latency analysis
- validation failure detection
- error rate measurement

## Known Gaps

These gaps should be addressed before we consider the product validated:

- no explicit missing-capability capture
- no normalized `outcome` field shared across success and failure paths
- no normalized `error_type` and `error_message_normalized`
- no workflow or job classification
- no product-facing summary of which failures are friction versus true product gaps
- no intent capture

## Feedback Strategy

The first explicit feedback path should be unmet-demand capture.

We should add a lightweight PostHog-native equivalent of MCP Cat's "report missing tools" behavior.
This should capture:

- the freeform missing capability request
- the current tool
- the current trace
- the current session
- the MCP client
- whether the user was blocked or merely suggesting an improvement

This is the first high-value signal to add because it gives us direct product demand without changing every tool schema.

## Intent Capture Strategy

Intent capture is valuable,
but it should not be phase 1.

Injecting a required context field into all tools is a high-leverage idea,
but it changes tool contracts and may add friction for some clients.

We should only add intent capture after we have validated the value of:

- existing trace data
- existing tool call data
- unmet-demand capture

If we later add intent capture,
we should begin with a small,
opt-in subset of tools or a narrow experiment.

## Phased Plan

### Phase 0: Product brief and questions

Deliverables:

- this document
- a locked set of validation questions
- a named customer-zero scope

Exit criteria:

- we agree what decisions `mcp_analytics` is supposed to help us make

### Phase 1: Instrumentation audit and normalization

Deliverables:

- audit current MCP analytics events
- standardize MCP properties
- add outcome taxonomy
- identify any gaps that prevent useful analysis

Exit criteria:

- for any MCP trace,
  we can explain what happened without relying on raw worker logs

### Phase 2: Missing-capability capture

Deliverables:

- a missing-capability feedback path in the PostHog MCP server
- stored data linked to session and trace
- a basic query or table for reviewing requests

Exit criteria:

- we can rank missing capabilities by volume and context

### Phase 3: Product shell

Deliverables:

- scaffold `products/mcp_analytics`
- define routes and scenes
- reuse LLM Analytics patterns for traces,
  sessions,
  tools,
  and failures

Exit criteria:

- we have a coherent product shell without new backend storage

### Phase 4: First read model and views

Deliverables:

- Overview view
- Tools table
- Sessions list and detail
- Failures view
- Feedback view

Exit criteria:

- a PM or engineer can use the product to identify at least one concrete MCP improvement

### Phase 5: PostHog as customer zero

Deliverables:

- weekly review of PostHog MCP usage
- documented top workflows,
  failures,
  and missing capabilities
- resulting roadmap changes

Exit criteria:

- the product directly influences the PostHog MCP roadmap

### Phase 6: Evaluate intent capture

Deliverables:

- decision on whether intent capture is required
- if yes,
  an opt-in implementation plan with limited blast radius

Exit criteria:

- we can show that intent capture changes product decisions enough to justify the added contract complexity

## MVP Query and UI Priorities

The first useful UI should answer these questions fast:

- How many users and sessions are using MCP?
- Which clients are using it?
- Which tools are most used?
- Which tools have the highest failure rate?
- Which sessions are most painful?
- What are people asking for that we do not support?

The first screens should optimize for fast diagnosis rather than completeness.

## Recommended Technical Direction

- Create a new `products/mcp_analytics` product.
- Reuse LLM Analytics frontend and query patterns wherever possible.
- Start with MCP-only filtered queries over existing AI event data.
- Keep the backend minimal until the product proves it needs more specialization.
- Treat `mcp_store` as configuration and installation,
  not as the foundation for analytics UX.

## Risks

- We may overfit the product to the PostHog MCP server and fail to generalize later.
- Existing MCP events may be too shallow to explain true user goals.
- Error normalization may require more effort than expected.
- Missing-capability capture could be noisy if not framed carefully.
- Intent capture may be valuable but expensive to adopt across tools and clients.

## Decision Log

Current decisions:

- Build a separate product surface instead of burying this inside `mcp_store`.
- Reuse LLM Analytics patterns and existing `$ai_*` data.
- Start with PostHog as customer zero.
- Prioritize unmet-demand capture before context injection.
- Validate with product decisions,
  not just usage charts.

## First Execution Tasks

1. Audit current MCP events and document the exact schema we already have.
2. Define the normalized MCP outcome properties.
3. Add missing-capability capture to the PostHog MCP server.
4. Scaffold `products/mcp_analytics`.
5. Implement the first read-only views using filtered LLM Analytics patterns.
