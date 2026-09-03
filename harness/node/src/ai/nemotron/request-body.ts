/**
 * The chat-completions request body, built once for both call sites.
 *
 * `complete()` and `stream()` each carried a verbatim copy of this literal,
 * differing only in `stream: false` / `stream: true`. One branch edited both
 * copies identically three times — which is the cost this module removes: a
 * change applied to one copy and not the other produces a client whose
 * streaming and non-streaming paths disagree about sampling, and nothing in
 * the suite would say so, because each path is exercised separately.
 *
 * Written as a pure function rather than a private method so the policy is an
 * argument: a test can prove the body follows the policy it is given, without
 * the shipped `governance-policy.json` having to agree with the assertion
 * (`R-NPW-1`, the reason `loadNemotronPolicy` takes a path at all).
 */

import type { NemotronPolicy } from './policy.js';
import type { ChatCompletionOptions } from './types.js';

/**
 * The provider's accepted range for each sampling parameter.
 *
 * Deliberately NOT policy-sourced: these are the API's documented input
 * domain, not a knob this repository tunes. Sending `temperature: 3` is
 * rejected by the endpoint whatever a policy file says, so treating the bound
 * as configurable would invite a policy that cannot be honoured. The values a
 * caller may *choose* within that range are policy-sourced; see
 * `NemotronPolicy`.
 */
export const SAMPLING_BOUNDS = {
  temperature: { min: 0, max: 2.0 },
  top_p: { min: 0, max: 1.0 },
} as const;

/** The wire shape sent to `/chat/completions`. */
export interface ChatRequestBody {
  readonly model: string;
  readonly messages: readonly unknown[];
  readonly temperature: number;
  readonly top_p: number;
  readonly max_tokens: number;
  readonly stream: boolean;
  readonly stop?: readonly string[];
}

/** Clamp `value` into `bounds`, so an out-of-range option cannot reach the API. */
export function clampToBounds(
  value: number,
  bounds: { readonly min: number; readonly max: number },
): number {
  return Math.max(bounds.min, Math.min(bounds.max, value));
}

/**
 * Build the request body for one call.
 *
 * @param options  the caller's request; every sampling field is optional and
 *                 falls back to the policy value when omitted.
 * @param model    the already-resolved model id (resolution needs client
 *                 config, so it stays with the client).
 * @param stream   the only field that differs between the two call sites.
 * @param policy   the `nemotron` policy block supplying every default.
 */
export function buildChatRequestBody(
  options: ChatCompletionOptions,
  model: string,
  stream: boolean,
  policy: NemotronPolicy,
): ChatRequestBody {
  return {
    model,
    messages: options.messages,
    temperature:
      options.temperature !== undefined
        ? clampToBounds(options.temperature, SAMPLING_BOUNDS.temperature)
        : policy.temperature,
    top_p:
      options.top_p !== undefined
        ? clampToBounds(options.top_p, SAMPLING_BOUNDS.top_p)
        : policy.top_p,
    max_tokens: options.max_tokens ?? policy.max_tokens,
    stream,
    ...(options.stop ? { stop: options.stop } : {}),
  };
}
