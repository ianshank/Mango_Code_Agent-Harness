/**
 * Retry / backoff unit tests for the module extracted under R-TDH-23.
 *
 * Requirement Citations:
 * - R-AI-RES-3: Exponential backoff with jitter; the circuit breaker hears one
 *   verdict per call, not per attempt
 * - R-TDH-23: retry logic lives beside the client and is testable without a
 *   transport
 */

import { describe, it, expect, vi } from 'vitest';
import {
  computeBackoffMs,
  executeWithRetry,
  isNetworkError,
  isRetryableError,
  JITTER_CEILING_MS,
  RATE_LIMITED_STATUS,
  RETRYABLE_ERROR_CODES,
  RETRYABLE_ERROR_NAMES,
  RETRYABLE_MESSAGE_FRAGMENTS,
  type RetryObserver,
  type RetryPolicy,
} from '../../../src/ai/nemotron/retry.js';

const POLICY: RetryPolicy = {
  maxRetries: 2,
  baseBackoffMs: 100,
  maxBackoffMs: 1000,
};

function errorWith(fields: Record<string, unknown>): Error {
  return Object.assign(new Error('opaque'), fields);
}

function observer(): RetryObserver & {
  successes: number;
  failures: number;
} {
  const o = {
    successes: 0,
    failures: 0,
    recordSuccess() {
      o.successes++;
    },
    recordFailure() {
      o.failures++;
    },
  };
  return o;
}

describe('isNetworkError', () => {
  it.each(RETRYABLE_ERROR_NAMES)('matches error name %s', (name) => {
    expect(isNetworkError(errorWith({ name }))).toBe(true);
  });

  it.each(RETRYABLE_ERROR_CODES)('matches socket code %s', (code) => {
    expect(isNetworkError(errorWith({ code }))).toBe(true);
  });

  it.each(RETRYABLE_MESSAGE_FRAGMENTS)(
    'matches a message containing %s',
    (fragment) => {
      expect(
        isNetworkError(new Error(`transport: ${fragment} (wrapped)`)),
      ).toBe(true);
    },
  );

  it('rejects an error with an unrelated name, code and message', () => {
    expect(
      isNetworkError(errorWith({ name: 'TypeError', code: 'EACCES' })),
    ).toBe(false);
  });

  it('treats a thrown non-object as non-network rather than throwing', () => {
    expect(isNetworkError('fetch failed')).toBe(false);
    expect(isNetworkError(null)).toBe(false);
    expect(isNetworkError(undefined)).toBe(false);
  });

  it('ignores facets of the wrong type instead of coercing them', () => {
    // A numeric name, code or message contributes nothing; only a string
    // `message` is searched, so an object with no usable facet is not network.
    expect(isNetworkError({ name: 7, code: 12, message: 99 })).toBe(false);
    expect(isNetworkError({})).toBe(false);
  });
});

describe('isRetryableError', () => {
  it('retries any network error regardless of status', () => {
    expect(isRetryableError(errorWith({ name: 'AbortError' }))).toBe(true);
  });

  it('retries the rate-limit status and the whole 5xx range', () => {
    expect(isRetryableError({ statusCode: RATE_LIMITED_STATUS })).toBe(true);
    expect(isRetryableError({ statusCode: 500 })).toBe(true);
    expect(isRetryableError({ statusCode: 599 })).toBe(true);
  });

  it('does not retry client errors, non-numeric statuses, or missing statuses', () => {
    expect(isRetryableError({ statusCode: 400 })).toBe(false);
    expect(isRetryableError({ statusCode: 404 })).toBe(false);
    expect(isRetryableError({ statusCode: 600 })).toBe(false);
    expect(isRetryableError({ statusCode: '500' })).toBe(false);
    expect(isRetryableError(new Error('validation failed'))).toBe(false);
  });
});

describe('computeBackoffMs', () => {
  it('doubles from the base per attempt with the jitter pinned to zero', () => {
    expect(computeBackoffMs(1, POLICY, () => 0)).toBe(100);
    expect(computeBackoffMs(2, POLICY, () => 0)).toBe(200);
    expect(computeBackoffMs(3, POLICY, () => 0)).toBe(400);
  });

  it('adds jitter scaled by the ceiling', () => {
    expect(computeBackoffMs(1, POLICY, () => 1)).toBe(100 + JITTER_CEILING_MS);
    expect(computeBackoffMs(1, POLICY, () => 0.5)).toBe(
      100 + JITTER_CEILING_MS / 2,
    );
  });

  it('never exceeds the maximum backoff', () => {
    expect(computeBackoffMs(10, POLICY, () => 1)).toBe(POLICY.maxBackoffMs);
  });

  it('defaults to Math.random and stays inside the jitter window', () => {
    const delay = computeBackoffMs(1, POLICY);
    expect(delay).toBeGreaterThanOrEqual(POLICY.baseBackoffMs);
    expect(delay).toBeLessThan(POLICY.baseBackoffMs + JITTER_CEILING_MS);
  });
});

describe('executeWithRetry', () => {
  it('returns the first successful result and reports one success', async () => {
    const seen = observer();
    const sleep = vi.fn(async () => undefined);
    const result = await executeWithRetry(async () => 'ok', {
      policy: POLICY,
      observer: seen,
      sleep,
    });
    expect(result).toBe('ok');
    expect(seen).toMatchObject({ successes: 1, failures: 0 });
    expect(sleep).not.toHaveBeenCalled();
  });

  it('sleeps the computed backoff between retryable failures, then succeeds', async () => {
    const seen = observer();
    const sleep = vi.fn(async () => undefined);
    let calls = 0;
    const operation = async () => {
      calls++;
      if (calls < 3) throw errorWith({ statusCode: RATE_LIMITED_STATUS });
      return 'recovered';
    };

    const result = await executeWithRetry(operation, {
      policy: POLICY,
      observer: seen,
      sleep,
      random: () => 0,
    });

    expect(result).toBe('recovered');
    expect(calls).toBe(3);
    expect(sleep.mock.calls).toEqual([[100], [200]]);
    // Intermediate failures are not verdicts; the breaker counts calls.
    expect(seen).toMatchObject({ successes: 1, failures: 0 });
  });

  it('throws a non-retryable error immediately and reports one failure', async () => {
    const seen = observer();
    const sleep = vi.fn(async () => undefined);
    const fatal = errorWith({ statusCode: 401 });
    let calls = 0;

    await expect(
      executeWithRetry(
        async () => {
          calls++;
          throw fatal;
        },
        { policy: POLICY, observer: seen, sleep },
      ),
    ).rejects.toBe(fatal);

    expect(calls).toBe(1);
    expect(sleep).not.toHaveBeenCalled();
    expect(seen).toMatchObject({ successes: 0, failures: 1 });
  });

  it('gives up after maxRetries retries and rethrows the last error', async () => {
    const seen = observer();
    const sleep = vi.fn(async () => undefined);
    const errors: Error[] = [];

    // Caught by hand rather than `.rejects.toBe(errors.at(-1))`: that argument
    // is evaluated before the loop has run, so it would name the first error.
    let caught: unknown;
    try {
      await executeWithRetry(
        async () => {
          const err = errorWith({ statusCode: 503 });
          errors.push(err);
          throw err;
        },
        { policy: POLICY, observer: seen, sleep, random: () => 0 },
      );
    } catch (err: unknown) {
      caught = err;
    }

    // One initial attempt plus maxRetries retries, with a sleep before each retry.
    expect(errors).toHaveLength(POLICY.maxRetries + 1);
    expect(caught).toBe(errors[errors.length - 1]);
    expect(sleep).toHaveBeenCalledTimes(POLICY.maxRetries);
    expect(seen).toMatchObject({ successes: 0, failures: 1 });
  });

  it('honours maxRetries of zero by never sleeping', async () => {
    const sleep = vi.fn(async () => undefined);
    await expect(
      executeWithRetry(
        async () => {
          throw errorWith({ statusCode: 500 });
        },
        { policy: { ...POLICY, maxRetries: 0 }, sleep },
      ),
    ).rejects.toThrow('opaque');
    expect(sleep).not.toHaveBeenCalled();
  });

  it('works without an observer on both the success and failure paths', async () => {
    const sleep = vi.fn(async () => undefined);
    await expect(
      executeWithRetry(async () => 42, { policy: POLICY, sleep }),
    ).resolves.toBe(42);
    await expect(
      executeWithRetry(
        async () => {
          throw new Error('plain');
        },
        { policy: POLICY, sleep },
      ),
    ).rejects.toThrow('plain');
  });

  it('falls back to a real timer and Math.random when none are injected', async () => {
    // A zero backoff window keeps the default sleep effectively immediate while
    // still exercising the setTimeout path and the default jitter source.
    let calls = 0;
    const result = await executeWithRetry(
      async () => {
        calls++;
        if (calls === 1) throw errorWith({ code: 'ECONNRESET' });
        return 'after-real-sleep';
      },
      { policy: { maxRetries: 1, baseBackoffMs: 0, maxBackoffMs: 0 } },
    );
    expect(result).toBe('after-real-sleep');
    expect(calls).toBe(2);
  });
});
