/** Shared API types mirroring the FastAPI response schemas. */

export type DocumentStatus =
  | 'uploading'
  | 'queued'
  | 'extracting'
  | 'chunking'
  | 'embedding'
  | 'indexing'
  | 'indexed'
  | 'failed'

export interface User {
  id: string
  email: string
  username: string
  created_at: string
  preferences: Record<string, unknown>
}

export interface AuthResponse {
  access_token: string
  token_type: string
  user: User
}

export interface Citation {
  document_id: string
  filename: string
  excerpt: string
  page_number: number | null
  section: string | null
  chunk_id: string | null
  score: number
  rank: number
  /** Provenance: an uploaded file, or a web page that was fetched. */
  source_type: 'document' | 'web'
  source_url: string | null
  domain: string | null
}

/** Which subsystem produced an answer. */
export type AnswerMode = 'document' | 'web' | 'live' | 'entity' | 'general'

export interface DocumentItem {
  id: string
  filename: string
  content_type: string
  file_size: number
  status: DocumentStatus
  status_detail: string
  progress: number
  error: string | null
  page_count: number
  chunk_count: number
  word_count: number
  used_ocr: boolean
  collection_id: string | null
  created_at: string
  doc_metadata: Record<string, unknown>
}

export interface DocumentList {
  items: DocumentItem[]
  total: number
  page: number
  page_size: number
}

export interface Collection {
  id: string
  name: string
  description: string
  color: string
  is_default: boolean
  created_at: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  model: string | null
  grounded: boolean
  confidence: number | null
  latency_ms: number | null
  created_at: string
  citations: Citation[]
  /** Which subsystem answered this turn. */
  mode: AnswerMode
  /** Structured entity payload for entity lookups. */
  entity: EntityCard | null
  /** Emotional tone of the user's question, when it read clearly. */
  tone: ToneReading | null
}

export interface Conversation {
  id: string
  title: string
  collection_id: string | null
  model: string | null
  archived: boolean
  created_at: string
  updated_at: string
  message_count: number
}

export interface ConversationDetail {
  id: string
  title: string
  collection_id: string | null
  model: string | null
  created_at: string
  updated_at: string
  messages: Message[]
}

export interface RetrievedChunk {
  chunk_id: string
  document_id: string
  filename: string
  text: string
  score: number
  rerank_score: number | null
  page_number: number | null
  section: string | null
  source_type: 'document' | 'web'
  source_url: string | null
  domain: string | null
}

export interface ChatResponse {
  conversation_id: string
  answer: string
  sources: string[]
  mode: AnswerMode
  mode_reason: string
  entity: EntityCard | null
  tone?: ToneReading | null
  citations: Citation[]
  retrieved_chunks: RetrievedChunk[]
  model: string
  grounded: boolean
  confidence: number
  processing_time_ms: number
  message_id: string
  title: string
}

export interface SmartResponse {
  result: string
  sources: string[]
  citations: Citation[]
  model: string
  processing_time_ms: number
}

export interface ModelDescriptor {
  id: string
  label: string
  task: string
  context_length: number
  backend: string
  description: string
  approx_size_mb: number | null
  requires_token: boolean
  /** False when the provider has no credential; the option is shown disabled. */
  configured?: boolean
  unavailable_reason?: string
}

/** How the user's message read emotionally, returned only when it was clear. */
export interface ToneReading {
  emotion: string
  label: string
  confidence: number
  valence: number
  intensity: number
  guidance?: string
}

export interface EmotionPassage {
  text: string
  emotion: string
  polarity: string
  charge: number
  intensity: number
  hits: number
  valence: number
  document_id: string
  filename: string
  page_number: number | null
  section?: string | null
}

export interface EmotionDocument {
  document_id: string
  filename: string
  emotion: string
  emotion_label: string
  polarity: string
  valence: number
  arousal: number
  scores: Record<string, number>
  hits: number
  chunks_analysed: number
  matched_words: string[]
  charged_passages: EmotionPassage[]
  has_text: boolean
}

export interface EmotionOverall {
  emotion: string
  emotion_label: string
  polarity: string
  valence: number
  arousal: number
  scores: Record<string, number>
  documents_analysed: number
  emotional_hits: number
  signal: 'strong' | 'moderate' | 'sparse'
}

export interface EmotionResponse {
  summary: string
  documents: EmotionDocument[]
  overall: EmotionOverall | null
  charged_passages: EmotionPassage[]
  sources: string[]
  citations: Citation[]
  model: string
  processing_time_ms: number
}

export interface ToneReading {
  emotion: string
  label: string
  confidence: number
  valence: number
  intensity: number
  guidance?: string
}

export interface ProviderStatus {
  local: boolean
  hf_api: boolean
  openai: boolean
  anthropic: boolean
  gemini: boolean
}

export interface ModelsResponse {
  generation: ModelDescriptor[]
  embeddings: ModelDescriptor[]
  reranking: ModelDescriptor[]
  auxiliary: ModelDescriptor[]
  tiers: Record<string, ModelDescriptor>
  providers?: ProviderStatus
  active: {
    generation_backend: string
    embedding_backend: string
    reranker_backend: string
    local_model: string
    embedding_model: string
    reranker_model: string
    hf_token_configured: boolean
  }
  retrieval_defaults: {
    chunk_size: number
    chunk_overlap: number
    top_k: number
    rerank_top_n: number
    temperature: number
    top_p: number
    max_tokens: number
    relevance_threshold: number
  }
}

export interface Health {
  status: string
  version: string
  database: string
  vector_db: string
  vector_count: number
  generation_backend: string
  generation_model: string
  embedding_model: string
  hf_token_configured: boolean
  ocr_available: boolean
  reranker_available: boolean
  documents: number
}

export interface AppSettings {
  user: User
  preferences: Record<string, unknown>
  ai: Record<string, unknown>
  documents: Record<string, unknown>
  retrieval: Record<string, unknown>
  privacy: Record<string, unknown>
}

export interface ChunkContext {
  chunk_id: string
  text: string
  page_number: number | null
  section: string | null
  document_id: string
  filename: string
  content_type: string
}

export interface DocumentChunk {
  id: string
  index: number
  text: string
  page_number: number | null
  section: string | null
  tokens: number
}

export interface WebResultItem {
  url: string
  title: string
  domain: string
  snippet: string
  provider: string
  content_chars: number
  ingested_document_id: string | null
}

export interface WebResponse {
  query: string
  provider: string
  results: WebResultItem[]
  errors: string[]
  ingested: string[]
}

export interface EntityFact {
  label: string
  value: string
  entity_ids: string[]
  url: string | null
}

export interface EntityCard {
  qid: string
  label: string
  description: string
  wikipedia_url: string | null
  image: string | null
  aliases: string[]
  facts: EntityFact[]
}
