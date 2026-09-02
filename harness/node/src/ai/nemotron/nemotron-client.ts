/**
 * NVIDIA Nemotron Ultra API Client Adapter.
 *
 * Requirement Citations:
 * - R-AI-NEMO-1: OpenAI-compatible wire protocol with endpoint abstraction
 * - R-AI-NEMO-2: Strict type contracts for streaming, chat messages, and token telemetry
 * - R-AI-RES-3: Exponential backoff with jitter and circuit breaker resilience
 * - C-AI-SEC-1: Secret sanitization and prevention of sensitive key leakage in stdout/logs
 */

import {
  NemotronConfig,
  ChatCompletionOptions,
  ChatCompletionResponse,
  StreamChunk,
} from './types.js';
import { SecretMasker } from './secret-masker.js';
import { CircuitBreaker } from './circuit-breaker.js';
import { NEMOTRON_POLICY } from './policy.js';
import { executeWithRetry } from './retry.js';
import * as fs from 'node:fs';
import * as path from 'node:path';

// Timeout and retry budget come from the governance policy (R-NPW-1); the
// backoff window and endpoint have no policy key yet and stay as they are.
export const DEFAULT_NEMOTRON_CONFIG: NemotronConfig = {
  baseUrl: 'https://integrate.api.nvidia.com/v1',
  timeoutMs: NEMOTRON_POLICY.timeout_ms,
  maxRetries: NEMOTRON_POLICY.max_retries,
  baseBackoffMs: 500,
  maxBackoffMs: 5000,
};

/**
 * The real `fetch` as it existed at module load.
 *
 * The egress floor (R-EGF-5) must refuse the *vendor network path* without
 * breaking a caller that supplied its own transport. A test double installed
 * over `globalThis.fetch` is a declared transport; this pristine reference is
 * how we tell the two apart, rather than guessing from the URL.
 */
const PRISTINE_FETCH: typeof fetch | undefined = globalThis.fetch;

/** Transport modes. `online` is the only value that permits the real network. */
export type NemotronMode = 'online' | 'offline';

/** Raised when a run would reach the network without an explicit declaration. */
export class NemotronEgressRefused extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NemotronEgressRefused';
  }
}

export function resolveNemotronMode(
  env: NodeJS.ProcessEnv = process.env,
): NemotronMode | undefined {
  const raw = env['NEMOTRON_MODE'];
  if (raw === 'online' || raw === 'offline') return raw;
  return undefined;
}

export class NemotronClient {
  public readonly config: NemotronConfig;
  private readonly circuitBreaker: CircuitBreaker;
  private readonly customFetch?: typeof fetch | undefined;

  constructor(
    customConfig: Partial<NemotronConfig> = {},
    customFetch?: typeof fetch | undefined,
  ) {
    const resolvedEnv = NemotronClient.resolveEnvironment();
    this.config = {
      baseUrl:
        customConfig.baseUrl ||
        resolvedEnv.baseUrl ||
        DEFAULT_NEMOTRON_CONFIG.baseUrl,
      apiKey: customConfig.apiKey ?? resolvedEnv.apiKey,
      defaultModel: customConfig.defaultModel || resolvedEnv.defaultModel,
      timeoutMs:
        customConfig.timeoutMs ??
        resolvedEnv.timeoutMs ??
        DEFAULT_NEMOTRON_CONFIG.timeoutMs,
      maxRetries: customConfig.maxRetries ?? DEFAULT_NEMOTRON_CONFIG.maxRetries,
      baseBackoffMs:
        customConfig.baseBackoffMs ?? DEFAULT_NEMOTRON_CONFIG.baseBackoffMs,
      maxBackoffMs:
        customConfig.maxBackoffMs ?? DEFAULT_NEMOTRON_CONFIG.maxBackoffMs,
    };
    this.circuitBreaker = new CircuitBreaker();
    this.customFetch = customFetch;
  }

  /**
   * Helper to load environment variables from process.env and .env files safely.
   */
  private static resolveEnvironment(): {
    baseUrl?: string | undefined;
    apiKey?: string | undefined;
    defaultModel?: string | undefined;
    timeoutMs?: number | undefined;
  } {
    let apiKey = process.env['NVIDIA_API_KEY'];
    let baseUrl = process.env['NVIDIA_BASE_URL'];
    let defaultModel = process.env['NEMOTRON_DEFAULT_MODEL'];
    let timeoutMs = process.env['NEMOTRON_TIMEOUT_MS']
      ? parseInt(process.env['NEMOTRON_TIMEOUT_MS'], 10)
      : undefined;

    if (!apiKey) {
      // Look for .env in current working dir or parent directory
      const candidatePaths = [
        path.resolve(process.cwd(), '.env'),
        path.resolve(process.cwd(), '../../.env'),
        path.resolve(process.cwd(), '../.env'),
      ];

      for (const p of candidatePaths) {
        if (fs.existsSync(p)) {
          try {
            const content = fs.readFileSync(p, 'utf-8');
            for (const line of content.split('\n')) {
              const trimmed = line.trim();
              if (
                trimmed &&
                !trimmed.startsWith('#') &&
                trimmed.includes('=')
              ) {
                const idx = trimmed.indexOf('=');
                const k = trimmed.slice(0, idx).trim();
                const v = trimmed.slice(idx + 1).trim();
                if (k === 'NVIDIA_API_KEY' && !apiKey) apiKey = v;
                if (k === 'NVIDIA_BASE_URL' && !baseUrl) baseUrl = v;
                if (k === 'NEMOTRON_DEFAULT_MODEL' && !defaultModel)
                  defaultModel = v;
              }
            }
            if (apiKey) break;
          } catch (_) {
            // Best effort ignore file read errors
          }
        }
      }
    }

    return { baseUrl, apiKey, defaultModel, timeoutMs };
  }

  /**
   * Generates a non-streaming chat completion from the Nemotron API.
   */
  async complete(
    options: ChatCompletionOptions,
  ): Promise<ChatCompletionResponse> {
    this.validateApiKey();

    if (!this.circuitBreaker.canExecute()) {
      throw new Error(
        'NemotronClient: Circuit breaker is OPEN. Outgoing requests temporarily suspended.',
      );
    }

    const model = options.model || this.config.defaultModel;
    if (!model) {
      throw new Error(
        'NemotronClient: Target model is not configured. Set NEMOTRON_DEFAULT_MODEL environment variable or provide it in options.',
      );
    }
    const body = {
      model,
      messages: options.messages,
      temperature:
        options.temperature !== undefined
          ? Math.max(0, Math.min(2.0, options.temperature))
          : NEMOTRON_POLICY.temperature,
      top_p:
        options.top_p !== undefined
          ? Math.max(0, Math.min(1.0, options.top_p))
          : 0.7,
      max_tokens: options.max_tokens ?? NEMOTRON_POLICY.max_tokens,
      stream: false,
      ...(options.stop ? { stop: options.stop } : {}),
    };

    const startTime = Date.now();
    const data: any = await this.executeWithRetry(async () => {
      const response = await this.doFetch('/chat/completions', {
        method: 'POST',
        headers: this.buildHeaders(),
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const errorText = await response.text();
        const sanitized = SecretMasker.sanitize(errorText, [
          this.config.apiKey,
        ]);
        const err = new Error(
          `Nemotron API Error HTTP ${response.status}: ${sanitized}`,
        );
        (err as any).statusCode = response.status;
        throw err;
      }

      return response.json();
    });

    const latencyMs = Date.now() - startTime;
    const choice = data.choices?.[0];
    const content = choice?.message?.content || '';

    return {
      id: data.id || `nemo-${Date.now()}`,
      model: data.model || model,
      content,
      choices: (data.choices || []).map((c: any) => ({
        index: c.index ?? 0,
        message: {
          role: c.message?.role || 'assistant',
          content: c.message?.content || '',
        },
        finishReason: c.finish_reason ?? null,
      })),
      usage: {
        promptTokens: data.usage?.prompt_tokens ?? 0,
        completionTokens: data.usage?.completion_tokens ?? 0,
        totalTokens: data.usage?.total_tokens ?? 0,
      },
      latencyMs,
    };
  }

  /**
   * Generates a streaming chat completion yielding SSE chunks.
   */
  async *stream(options: ChatCompletionOptions): AsyncIterable<StreamChunk> {
    this.validateApiKey();

    if (!this.circuitBreaker.canExecute()) {
      throw new Error(
        'NemotronClient: Circuit breaker is OPEN. Outgoing requests temporarily suspended.',
      );
    }

    const model = options.model || this.config.defaultModel;
    if (!model) {
      throw new Error(
        'NemotronClient: Target model is not configured. Set NEMOTRON_DEFAULT_MODEL environment variable or provide it in options.',
      );
    }
    const body = {
      model,
      messages: options.messages,
      temperature:
        options.temperature !== undefined
          ? Math.max(0, Math.min(2.0, options.temperature))
          : NEMOTRON_POLICY.temperature,
      top_p:
        options.top_p !== undefined
          ? Math.max(0, Math.min(1.0, options.top_p))
          : 0.7,
      max_tokens: options.max_tokens ?? NEMOTRON_POLICY.max_tokens,
      stream: true,
      ...(options.stop ? { stop: options.stop } : {}),
    };

    const response = await this.executeWithRetry(async () => {
      const resp = await this.doFetch('/chat/completions', {
        method: 'POST',
        headers: this.buildHeaders(),
        body: JSON.stringify(body),
      });

      if (!resp.ok) {
        const errorText = await resp.text();
        const sanitized = SecretMasker.sanitize(errorText, [
          this.config.apiKey,
        ]);
        const err = new Error(
          `Nemotron API Stream Error HTTP ${resp.status}: ${sanitized}`,
        );
        (err as any).statusCode = resp.status;
        throw err;
      }
      return resp;
    });

    if (!response.body) {
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(':')) continue;
        if (trimmed === 'data: [DONE]') return;

        if (trimmed.startsWith('data: ')) {
          const jsonStr = trimmed.slice(6);
          try {
            const parsed = JSON.parse(jsonStr);
            const choice = parsed.choices?.[0];
            const delta = choice?.delta?.content || '';
            const finishReason = choice?.finish_reason ?? null;

            yield {
              id: parsed.id || '',
              model: parsed.model || model,
              delta,
              finishReason,
            };
          } catch (_) {
            // Ignore incomplete or unparseable SSE frame
          }
        }
      }
    }
  }

  private buildHeaders(): Record<string, string> {
    return {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      Authorization: `Bearer ${this.config.apiKey}`,
      'User-Agent': 'Agentic-SSD-Nemotron-Client/2.0',
    };
  }

  /**
   * Resolve the transport, failing closed (R-EGF-5, DEC-EGF-003).
   *
   * An injected `customFetch` is always honoured -- supplying a transport IS
   * the declaration. A `globalThis.fetch` that is no longer the pristine
   * reference is a test double, likewise declared. Only the genuine vendor
   * network path requires `NEMOTRON_MODE=online`; unset refuses rather than
   * silently resolving to the vendor endpoint, which is the defect this
   * change exists to close.
   */
  private resolveTransport(): typeof fetch {
    if (this.customFetch) return this.customFetch;

    const current = globalThis.fetch;
    const isPristine = current === PRISTINE_FETCH;
    if (!isPristine && current) return current;

    const mode = resolveNemotronMode();
    if (mode === 'online') {
      if (!current) {
        throw new NemotronEgressRefused(
          'NEMOTRON_MODE=online but no fetch implementation is available',
        );
      }
      return current;
    }
    if (mode === 'offline') {
      throw new NemotronEgressRefused(
        'NEMOTRON_MODE=offline: refusing to open a network transport. ' +
          'Inject a transport (the NemotronClient customFetch argument) to run offline.',
      );
    }
    throw new NemotronEgressRefused(
      'no transport mode declared: refusing to reach ' +
        `${this.config.baseUrl}. Set NEMOTRON_MODE=online to permit network ` +
        'egress, NEMOTRON_MODE=offline to forbid it, or inject a transport.',
    );
  }

  private async doFetch(
    endpoint: string,
    init: RequestInit,
  ): Promise<Response> {
    const fetchFn = this.resolveTransport();
    const url = `${this.config.baseUrl.replace(/\/+$/, '')}${endpoint}`;

    const controller = new AbortController();
    const timeoutId = setTimeout(
      () => controller.abort(),
      this.config.timeoutMs,
    );

    try {
      return await fetchFn(url, {
        ...init,
        signal: controller.signal,
      });
    } catch (fetchErr: any) {
      if (fetchErr.name === 'AbortError') {
        const timeoutErr = new Error(
          `Request to ${url} timed out after ${this.config.timeoutMs}ms`,
        );
        (timeoutErr as any).name = 'TimeoutError';
        throw timeoutErr;
      }
      throw fetchErr;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  /**
   * The retry decision lives in `retry.ts` (R-TDH-23); the client contributes
   * only its budget and the circuit breaker that hears each call's verdict.
   */
  private executeWithRetry<T>(operation: () => Promise<T>): Promise<T> {
    return executeWithRetry(operation, {
      policy: this.config,
      observer: this.circuitBreaker,
    });
  }

  private validateApiKey(): void {
    if (!this.config.apiKey || this.config.apiKey.trim().length === 0) {
      throw new Error(
        'NemotronClient: NVIDIA_API_KEY is not configured. Please set the NVIDIA_API_KEY environment variable or provide it in .env.',
      );
    }
  }
}
