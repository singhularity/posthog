import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo, useRef } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import MaxTool from 'scenes/max/MaxTool'
import { castAssistantQuery } from 'scenes/max/utils'
import { QUERY_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import {
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
} from '~/queries/schema/schema-assistant-queries'
import {
    DataVisualizationNode,
    InsightQueryNode,
    InsightVizNode,
    NodeKind,
    QuerySchema,
} from '~/queries/schema/schema-general'
import { isHogQLQuery, isInsightQueryNode } from '~/queries/utils'

import { SessionAnalysisWarning } from './SessionAnalysisWarning'
import { SuggestionBanner } from './SuggestionBanner'

export interface InsightEditorPanelProps {
    query: InsightQueryNode
    showing: boolean
    embedded: boolean
    children: React.ReactNode
}

export function InsightEditorPanel({ query, showing, embedded, children }: InsightEditorPanelProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, shouldShowSessionAnalysisWarning } = useValues(insightVizDataLogic(insightProps))
    const { setQuery } = useActions(insightVizDataLogic(insightProps))
    const { handleInsightSuggested, onRejectSuggestedInsight } = useActions(insightLogic(insightProps))
    const { previousQuery, suggestedQuery } = useValues(insightLogic(insightProps))

    const panelRef = useRef<HTMLDivElement>(null)
    const resizerProps = useMemo(
        () => ({
            logicKey: 'insight-editor-panel',
            persistent: true,
            placement: 'right' as const,
            containerRef: panelRef,
        }),
        []
    )
    const { desiredSize: panelWidth, isResizeInProgress: isResizing } = useValues(resizerLogic(resizerProps))

    useEffect(() => {
        if (showing) {
            posthog.capture('editor panel shown', { panel_width: panelWidth })
        }
    }, [showing]) // oxlint-disable-line react-hooks/exhaustive-deps

    const QueryTypeIcon = QUERY_TYPES_METADATA[query.kind].icon

    return (
        <div
            ref={panelRef}
            className={clsx(
                'EditorFiltersWrapper relative self-stretch @container/editor-panel',
                isResizing ? '' : 'transition-all duration-300 ease-out',
                showing ? 'opacity-100' : 'w-0 min-w-0 max-w-0 opacity-0 overflow-hidden border-0 !p-0'
            )}
            style={
                showing && panelWidth
                    ? { width: panelWidth, minWidth: 320, maxWidth: 600 }
                    : showing
                      ? { width: 'max(min(30%, 600px), 420px)', minWidth: 320, maxWidth: 600 }
                      : undefined
            }
        >
            {showing && <Resizer {...resizerProps} />}
            <MaxTool
                identifier="create_insight"
                context={{ current_query: querySource }}
                contextDescription={{ text: 'Current query', icon: <QueryTypeIcon /> }}
                callback={(
                    toolOutput:
                        | AssistantTrendsQuery
                        | AssistantFunnelsQuery
                        | AssistantRetentionQuery
                        | AssistantHogQLQuery
                ) => {
                    const source = castAssistantQuery(toolOutput)
                    if (!source) {
                        return
                    }
                    let node: QuerySchema
                    if (isHogQLQuery(source)) {
                        node = { kind: NodeKind.DataVisualizationNode, source } satisfies DataVisualizationNode
                    } else if (isInsightQueryNode(source)) {
                        node = { kind: NodeKind.InsightVizNode, source } satisfies InsightVizNode
                    } else {
                        node = source
                    }
                    handleInsightSuggested(node)
                    setQuery(node)
                }}
                initialMaxPrompt="Show me users who "
                className="h-full [&_button.absolute]:!-top-1 [&_button.absolute]:!-right-1"
                active={!embedded}
            >
                <div className={clsx('h-full overflow-y-auto', showing && 'px-3 pt-2 pb-4')}>
                    {shouldShowSessionAnalysisWarning ? <SessionAnalysisWarning /> : null}
                    {children}
                    {previousQuery && (
                        <SuggestionBanner
                            previousQuery={previousQuery}
                            suggestedQuery={suggestedQuery}
                            onReject={onRejectSuggestedInsight}
                        />
                    )}
                </div>
            </MaxTool>
        </div>
    )
}
