/**
 * Retry and backoff for the Nemotron client (R-AI-RES-3).
 *
 * Extracted from `nemotron-client.ts` under R-TDH-23 so the client stays under
 * `limits.size_budget_lines` and the retry decision can be tested on its own,
 * without a transport or a circuit breaker in the loop. The behaviour is the
 * client's original behaviour, unchanged: a failed attempt is retried when it
 * looks like a transient network fault, a 429, or a 5xx, up to `maxRetries`
 * more attempts, with exponential backoff plus jitter capped at `maxBackoffMs`.
 */

/** The retry budget and backoff window; `NemotronConfig` satisfies this. */
export interface RetryPolicy {
  readonly maxRetries: number;
  readonly baseBackoffMs: number;
  readonly maxBackoffMs: number;
}

/** Sink for the outcome of the whole retry loop; `CircuitBreaker` satisfies this. */
export interface RetryObserver {
  recordSuccess(): void;
  recordFailure(): void;
}

export interface RetryOptions {
  readonly policy: RetryPolicy;
  /** Notified once per call: success on return, failure on the final throw. */
  readonly observer?: RetryObserver | undefined;
  /** Injectable so tests never wait on a real timer. */
  readonly sleep?: ((ms: number) => Promise<void>) | undefined;
  /** Injectable so tests can pin the jitter to an exact value. */
  readonly random?: (() => number) | undefined;
}

/** Error names raised by `fetch`/`AbortController` on a dead or slow connection. */
export const RETRYABLE_ERROR_NAMES: readonly string[] = [
  'AbortError',
  'TimeoutError',
];

/** Node socket error codes that mean "the network failed", not "the request was wrong". */
export const RETRYABLE_ERROR_CODES: readonly string[] = [
  'ECONNRESET',
  'ETIMEDOUT',
  'ENOTFOUND',
];

/** Message fragments matched when a transport wraps the cause without a code. */
export const RETRYABLE_MESSAGE_FRAGMENTS: readonly string[] = [
  'aborted',
  'timed out',
  'fetch failed',
];

/** HTTP status that means "slow down"; retried alongside the 5xx range. */
export const RATE_LIMITED_STATUS = 429;
const SERVER_ERROR_FLOOR = 500;
const SERVER_ERROR_CEILING = 600;

/**
 * Upper bound of the random jitter added to each backoff. The policy declares
 * no jitter key (only `nemotron.max_retries`), so this is the one literal the
 * module owns; it is exported so a test can pin the arithmetic against it
 * rather than restating the number.
 */
export const JITTER_CEILING_MS = 200;

/** The subset of thrown-value shape the retry decision looks at. */
interface ErrorFacets {
  readonly name?: string;
  readonly code?: string;
  readonly message?: string;
  readonly statusCode?: number;
}

/**
 * Read the facets we branch on without trusting the thrown value's type.
 *
 * Anything can be thrown; `catch (err: any)` used to paper over that. A
 * non-object (or a field of the wrong type) simply contributes nothing, so a
 * thrown string is non-retryable rather than a TypeError inside the loop.
 */
function facetsOf(err: unknown): ErrorFacets {
  if (typeof err !== 'object' || err === null) return {};
  const record = err as Record<string, unknown>;
  const name = record['name'];
  const code = record['code'];
  const message = record['message'];
  const statusCode = record['statusCode'];
  return {
    ...(typeof name === 'string' ? { name } : {}),
    ...(typeof code === 'string' ? { code } : {}),
    ...(typeof message === 'string' ? { message } : {}),
    ...(typeof statusCode === 'number' ? { statusCode } : {}),
  };
}

/** True when the failure looks like a transient transport fault. */
export function isNetworkError(err: unknown): boolean {
  const { name, code, message } = facetsOf(err);
  if (name !== undefined && RETRYABLE_ERROR_NAMES.includes(name)) return true;
  if (code !== undefined && RETRYABLE_ERROR_CODES.includes(code)) return true;
  if (message === undefined) return false;
  return RETRYABLE_MESSAGE_FRAGMENTS.some((fragment) =>
    message.includes(fragment),
  );
}

/** True when a retry could plausibly succeed: network fault, 429, or 5xx. */
export function isRetryableError(err: unknown): boolean {
  if (isNetworkError(err)) return true;
  const { statusCode } = facetsOf(err);
  if (statusCode === undefined) return false;
  return (
    statusCode === RATE_LIMITED_STATUS ||
    (statusCode >= SERVER_ERROR_FLOOR && statusCode < SERVER_ERROR_CEILING)
  );
}

/**
 * Delay before the retry that follows failed attempt number `attempt` (1-based).
 *
 * Doubles from `baseBackoffMs`, adds up to `JITTER_CEILING_MS` of jitter so a
 * burst of clients does not retry in lockstep, and never exceeds `maxBackoffMs`.
 */
export function computeBackoffMs(
  attempt: number,
  policy: RetryPolicy,
  random: () => number = Math.random,
): number {
  const jitter = random() * JITTER_CEILING_MS;
  return Math.min(
    policy.maxBackoffMs,
    policy.baseBackoffMs * Math.pow(2, attempt - 1) + jitter,
  );
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Run `operation`, retrying retryable failures up to `policy.maxRetries` times.
 *
 * The observer hears exactly one verdict per call: `recordSuccess` when an
 * attempt returns, `recordFailure` when the loop gives up. Intermediate
 * failures that are about to be retried are not reported, so a circuit
 * breaker counts calls, not attempts, exactly as the client always did.
 */
export async function executeWithRetry<T>(
  operation: () => Promise<T>,
  options: RetryOptions,
): Promise<T> {
  const { policy, observer } = options;
  const sleep = options.sleep ?? defaultSleep;
  const random = options.random ?? Math.random;
  let attempt = 0;
  for (;;) {
    try {
      const result = await operation();
      observer?.recordSuccess();
      return result;
    } catch (err: unknown) {
      attempt++;
      if (!isRetryableError(err) || attempt > policy.maxRetries) {
        observer?.recordFailure();
        throw err;
      }
      await sleep(computeBackoffMs(attempt, policy, random));
    }
  }
}
