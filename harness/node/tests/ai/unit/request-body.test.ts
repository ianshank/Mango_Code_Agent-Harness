/**
 * Chat request-body builder tests (NEXT_STEPS.md NS-16).
 * Requirement Citations:
 * - R-NPW-1: sampling defaults are read from governance-policy.json, never a literal
 * - NS-16: `complete()` and `stream()` build one body, differing only in `stream`
 *
 * The policy is injected rather than read from disk, so these assertions cannot
 * pass by coincidence: the fixture values below deliberately differ from every
 * value in the shipped policy, which is what makes "the body follows policy"
 * falsifiable rather than a restatement of the file.
 */

import { describe, it, expect } from 'vitest';
import {
  buildChatRequestBody,
  clampToBounds,
  SAMPLING_BOUNDS,
} from '../../../src/ai/nemotron/request-body.js';
import type { NemotronPolicy } from '../../../src/ai/nemotron/policy.js';
import type { ChatCompletionOptions } from '../../../src/ai/nemotron/types.js';

/** Distinguishable from the shipped policy (0.2 / 0.7 / 4096) on every key. */
const FIXTURE_POLICY: NemotronPolicy = {
  timeout_ms: 11_000,
  max_retries: 5,
  temperature: 0.33,
  top_p: 0.44,
  max_tokens: 55,
};

const MESSAGES: ChatCompletionOptions['messages'] = [
  { role: 'user', content: 'hello' },
];

const MODEL = 'fixture/model';

describe('buildChatRequestBody (R-NPW-1, NS-16)', () => {
  it('takes every sampling default from the policy it is given', () => {
    const body = buildChatRequestBody(
      { messages: MESSAGES },
      MODEL,
      false,
      FIXTURE_POLICY,
    );
    expect(body.temperature).toBe(FIXTURE_POLICY.temperature);
    expect(body.top_p).toBe(FIXTURE_POLICY.top_p);
    expect(body.max_tokens).toBe(FIXTURE_POLICY.max_tokens);
    expect(body.model).toBe(MODEL);
    expect(body.messages).toBe(MESSAGES);
  });

  it('prefers explicit options over the policy defaults', () => {
    const body = buildChatRequestBody(
      { messages: MESSAGES, temperature: 1.25, top_p: 0.9, max_tokens: 12 },
      MODEL,
      false,
      FIXTURE_POLICY,
    );
    expect(body.temperature).toBe(1.25);
    expect(body.top_p).toBe(0.9);
    expect(body.max_tokens).toBe(12);
  });

  it('is identical for both call sites apart from `stream`', () => {
    /**
     * The invariant the extraction exists to guarantee. Two copies of this
     * literal drifted apart silently before, because `complete()` and
     * `stream()` are exercised by separate tests that each only see their own
     * body.
     */
    const options: ChatCompletionOptions = {
      messages: MESSAGES,
      temperature: 0.9,
      stop: ['END'],
    };
    const nonStreaming = buildChatRequestBody(
      options,
      MODEL,
      false,
      FIXTURE_POLICY,
    );
    const streaming = buildChatRequestBody(
      options,
      MODEL,
      true,
      FIXTURE_POLICY,
    );

    expect(nonStreaming.stream).toBe(false);
    expect(streaming.stream).toBe(true);
    expect({ ...nonStreaming, stream: null }).toEqual({
      ...streaming,
      stream: null,
    });
  });

  it('omits `stop` entirely when the caller supplies none', () => {
    const body = buildChatRequestBody(
      { messages: MESSAGES },
      MODEL,
      false,
      FIXTURE_POLICY,
    );
    expect('stop' in body).toBe(false);
  });

  it('passes `stop` through when supplied', () => {
    const body = buildChatRequestBody(
      { messages: MESSAGES, stop: ['HALT'] },
      MODEL,
      true,
      FIXTURE_POLICY,
    );
    expect(body.stop).toEqual(['HALT']);
  });

  it.each([
    [
      'temperature above the provider maximum',
      { temperature: 99 },
      'temperature',
      SAMPLING_BOUNDS.temperature.max,
    ],
    [
      'temperature below zero',
      { temperature: -4 },
      'temperature',
      SAMPLING_BOUNDS.temperature.min,
    ],
    [
      'top_p above the provider maximum',
      { top_p: 42 },
      'top_p',
      SAMPLING_BOUNDS.top_p.max,
    ],
    ['top_p below zero', { top_p: -1 }, 'top_p', SAMPLING_BOUNDS.top_p.min],
  ])(
    'clamps %s so an out-of-range option never reaches the API',
    (_name, overrides, field, expected) => {
      const body = buildChatRequestBody(
        { messages: MESSAGES, ...overrides },
        MODEL,
        false,
        FIXTURE_POLICY,
      );
      expect(body[field as 'temperature' | 'top_p']).toBe(expected);
    },
  );

  it('does not clamp the policy value itself', () => {
    /**
     * Clamping applies to caller input. A policy outside the provider's range
     * is a policy defect and must surface as an API rejection naming the real
     * cause, not be silently rewritten into a value nobody configured.
     */
    const body = buildChatRequestBody({ messages: MESSAGES }, MODEL, false, {
      ...FIXTURE_POLICY,
      temperature: 9,
      top_p: 9,
    });
    expect(body.temperature).toBe(9);
    expect(body.top_p).toBe(9);
  });
});

describe('clampToBounds', () => {
  it.each([
    [5, { min: 0, max: 1 }, 1],
    [-5, { min: 0, max: 1 }, 0],
    [0.5, { min: 0, max: 1 }, 0.5],
    [0, { min: 0, max: 1 }, 0],
    [1, { min: 0, max: 1 }, 1],
  ])('clamps %s into %o as %s', (value, bounds, expected) => {
    expect(clampToBounds(value, bounds)).toBe(expected);
  });
});

describe('SAMPLING_BOUNDS', () => {
  it('states the provider input domain, not a tunable', () => {
    /**
     * Pinned so a later change has to be deliberate: these are the endpoint's
     * accepted ranges. Making them policy-sourced would invite a policy the
     * API cannot honour, which is why they are not in `NemotronPolicy`.
     */
    expect(SAMPLING_BOUNDS.temperature).toEqual({ min: 0, max: 2.0 });
    expect(SAMPLING_BOUNDS.top_p).toEqual({ min: 0, max: 1.0 });
  });
});
