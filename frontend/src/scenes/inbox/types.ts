export interface SignalReport {
    id: string
    title: string | null
    summary: string | null
    status: SignalReportStatus
    total_weight: number
    signal_count: number
    relevant_user_count: number | null
    created_at: string
    updated_at: string
    artefact_count: number
    is_suggested_reviewer: boolean
}

export interface RelevantCommit {
    sha: string
    url: string
}

export interface EnrichedReviewer {
    github_login: string
    github_name: string | null
    relevant_commits: RelevantCommit[]
    user: {
        id: number
        uuid: string
        first_name: string
        last_name: string
        email: string
        hedgehog_config: Record<string, any> | null
    } | null
}

export enum SignalReportStatus {
    POTENTIAL = 'potential',
    CANDIDATE = 'candidate',
    IN_PROGRESS = 'in_progress',
    PENDING_INPUT = 'pending_input',
    READY = 'ready',
    FAILED = 'failed',
}

export interface SignalReportArtefact {
    id: string
    type: string
    content: Record<string, any>
    created_at: string
}

export interface SignalReportArtefactResponse {
    results: SignalReportArtefact[]
    count: number
}

export interface SignalSourceConfig {
    id: string
    source_product: SignalSourceProduct
    source_type: SignalSourceType
    enabled: boolean
    config: Record<string, any>
    created_at: string
    updated_at: string
    status: SignalSourceConfigStatus | null
}

export enum SignalSourceProduct {
    SESSION_REPLAY = 'session_replay',
    LLM_ANALYTICS = 'llm_analytics',
    GITHUB = 'github',
    LINEAR = 'linear',
    ZENDESK = 'zendesk',
}

export enum SignalSourceType {
    SESSION_ANALYSIS_CLUSTER = 'session_analysis_cluster',
    EVALUATION = 'evaluation',
    ISSUE = 'issue',
    TICKET = 'ticket',
}

export interface ToggleSignalSourceParams {
    sourceProduct: SignalSourceProduct
    sourceType: SignalSourceType
    enabled: boolean
    config?: Record<string, any>
}

export enum SignalSourceConfigStatus {
    RUNNING = 'running',
    COMPLETED = 'completed',
    FAILED = 'failed',
}
