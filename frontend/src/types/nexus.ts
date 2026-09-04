export type AgentKind = 'ingestion' | 'matcher' | 'math' | 'decision' | 'output'

export type SessionStatus =
  | 'welcome'
  | 'collecting'
  | 'interview'
  | 'ready_to_confirm'
  | 'confirmed'
  | 'handoff'

export interface ChatMessage {
  id: string
  role: 'assistant' | 'user' | 'system'
  content: string
  meta?: Record<string, unknown>
}

export interface Port {
  name: string
  direction?: 'in' | 'out'
}

export interface PipelineNode {
  id: string
  agent: AgentKind
  mode: string
  behavior_ref: string
  label: string
  config: Record<string, unknown>
  error_strategy?: string
  ports: Port[]
}

export interface PipelineEdge {
  id: string
  source: string
  source_port: string
  target: string
  target_port: string
  type?: string
  condition?: string | null
}

export interface Pipeline {
  id: string
  name: string
  version: string
  nodes: PipelineNode[]
  edges: PipelineEdge[]
  meta?: Record<string, unknown>
  file_slots?: FileSlot[]
  missing_files?: string[]
}

export interface ConfigPatch {
  node_id: string
  config: Record<string, unknown>
}

export interface ProgressiveReveal {
  upsert_nodes: PipelineNode[]
  remove_node_ids: string[]
  upsert_edges: PipelineEdge[]
  remove_edge_ids: string[]
  config_patches: ConfigPatch[]
}

export interface ChatResponse {
  session_id: string
  status: SessionStatus
  confirmed: boolean
  question_count: number
  ready_to_confirm: boolean
  summary: string | null
  upload_offer?: 'data' | 'knowledge' | null
  message: ChatMessage
  user_message?: ChatMessage | null
  reveal: ProgressiveReveal | null
  pipeline: Pipeline | null
  cannot_serve?: boolean
  suggest_handoff?: boolean
}

export interface AgentCatalogEntry {
  name: AgentKind
  label: string
  summary: string
  modes: string[]
  ports: { out: string[] }
  config_schema: Record<string, Record<string, unknown>>
}

export interface RunStepView {
  node_id: string
  agent: string
  behavior_version: string
  status: 'ok' | 'skipped' | 'error'
  duration_ms: number
  error: string | null
  skip_reason?: string | null
  summary?: string
  emitted_by: string[]
  output_ports: string[]
}

export interface RunStreamEvent {
  type: 'node_start' | 'node_finish' | 'done' | 'result' | 'error'
  run_id?: string
  node_id?: string
  agent?: string
  label?: string
  status?: string
  duration_ms?: number
  skip_reason?: string | null
  error?: string | null
  summary?: string
  message?: string
  artifacts?: string[]
  run?: RunView
}

export interface RunView {
  id: string
  pipeline_id: string
  pipeline_version: string
  status: string
  artifacts: string[]
  artifact_paths: string[]
  steps: RunStepView[]
  extra: Record<string, unknown>
}

export interface Envelope {
  run_id: string
  node_id: string
  port: string
  payload: Record<string, unknown>
  emitted_by: string
  knowledge_context?: Record<string, unknown> | null
  meta?: Record<string, unknown>
}

export interface RunStepFull {
  node_id: string
  agent: string
  behavior_version: string
  status: string
  duration_ms: number
  error: string | null
  inputs: Envelope[]
  outputs: Envelope[]
}

export interface RunSnapshot {
  run: {
    id: string
    pipeline_id: string
    pipeline_version: string
    status: string
    artifacts: string[]
    steps: RunStepFull[]
    started_at?: string | null
    finished_at?: string | null
    error?: string | null
    extra?: Record<string, unknown>
  }
  pipeline: Pipeline | null
}

export interface FileSlot {
  node_id: string
  kind: 'data' | 'knowledge' | string
  filename: string
  label: string
}

export interface LibraryPipeline {
  id: string
  name: string
  version: string
  nodes: number
  brief?: string | null
  file_slots?: FileSlot[]
}
