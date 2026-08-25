/**
 * NVIDIA Nemotron Ultra API Client - Type Definitions.
 *
 * Requirement Citations:
 * - R-AI-NEMO-1: OpenAI-compatible wire protocol with endpoint abstraction
 * - R-AI-NEMO-2: Strict type contracts for streaming, chat messages, and token telemetry
 * - C-AI-SEC-1: Secret sanitization and fail-closed configuration contracts
 */

export interface NemotronConfig {
  /** Base URL for NVIDIA NIM / OpenAI compatible endpoint (default: https://integrate.api.nvidia.com/v1) */
  readonly baseUrl: string;
  /** API key for authorization (loaded from NVIDIA_API_KEY env or .env) */
  readonly apiKey?: string | undefined;
  /** Default model identifier */
  readonly defaultModel: string;
  /** Request timeout in milliseconds (default: 30000) */
  readonly timeoutMs: number;
  /** Maximum number of retry attempts on 429/5xx (default: 3) */
  readonly maxRetries: number;
  /** Initial backoff duration in milliseconds (default: 500) */
  readonly baseBackoffMs: number;
  /** Maximum backoff duration in milliseconds (default: 5000) */
  readonly maxBackoffMs: number;
}

export type ChatRole = 'system' | 'user' | 'assistant' | 'tool';

export interface ChatMessage {
  readonly role: ChatRole;
  readonly content: string;
  readonly name?: string | undefined;
}

export interface ChatCompletionOptions {
  /** Model to invoke. Defaults to config.defaultModel */
  readonly model?: string | undefined;
  /** Sequence of chat messages forming conversation context */
  readonly messages: readonly ChatMessage[];
  /** Sampling temperature (clamped between 0.0 and 2.0) */
  readonly temperature?: number | undefined;
  /** Nucleus sampling parameter (clamped between 0.0 and 1.0) */
  readonly top_p?: number | undefined;
  /** Maximum completion tokens to generate */
  readonly max_tokens?: number | undefined;
  /** Stop sequences */
  readonly stop?: readonly string[] | undefined;
  /** Whether to stream response via SSE */
  readonly stream?: boolean | undefined;
}

export interface TokenUsage {
  readonly promptTokens: number;
  readonly completionTokens: number;
  readonly totalTokens: number;
}

export interface ChatCompletionChoice {
  readonly index: number;
  readonly message: ChatMessage;
  readonly finishReason: string | null;
}

export interface ChatCompletionResponse {
  readonly id: string;
  readonly model: string;
  readonly content: string;
  readonly choices: readonly ChatCompletionChoice[];
  readonly usage: TokenUsage;
  readonly latencyMs: number;
}

export interface StreamChunk {
  readonly id: string;
  readonly model: string;
  readonly delta: string;
  readonly finishReason: string | null;
}

export interface NemotronErrorDetails {
  readonly statusCode?: number | undefined;
  readonly message: string;
  readonly rawError?: unknown;
}
