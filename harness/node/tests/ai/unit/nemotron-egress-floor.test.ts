/**
 * Egress floor: the client fails closed rather than reaching the vendor (EGF).
 *
 * Requirement Citations:
 * - R-EGF-5: an unset transport mode MUST NOT resolve to the vendor endpoint
 * - R-EGF-3: the Node runtime is guarded independently of the Python suite,
 *   because a Python socket guard cannot observe a `fetch` in this process
 * - DEC-EGF-003: an unset mode fails closed
 *
 * The Python socket floor cannot see this code path at all. That is the whole
 * reason this file exists separately from the pytest guard.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import {
  NemotronClient,
  NemotronEgressRefused,
  resolveNemotronMode,
} from '../../../src/ai/nemotron/nemotron-client.js';

const MODE = 'NEMOTRON_MODE';

function client(customFetch?: typeof fetch) {
  return new NemotronClient(
    {
      apiKey: 'nvapi-mock-key-1234567890',
      defaultModel: 'test-model',
      maxRetries: 0,
      baseBackoffMs: 1,
      maxBackoffMs: 5,
    },
    customFetch,
  );
}

function ask(c: NemotronClient) {
  return c.complete({ messages: [{ role: 'user' as const, content: 'hi' }] });
}

let saved: string | undefined;

beforeEach(() => {
  saved = process.env[MODE];
  delete process.env[MODE];
});

afterEach(() => {
  if (saved === undefined) delete process.env[MODE];
  else process.env[MODE] = saved;
  vi.unstubAllGlobals();
});

describe('transport mode resolution', () => {
  it('recognises only the two declared values', () => {
    process.env[MODE] = 'online';
    expect(resolveNemotronMode()).toBe('online');
    process.env[MODE] = 'offline';
    expect(resolveNemotronMode()).toBe('offline');
    process.env[MODE] = 'yes-please';
    expect(resolveNemotronMode()).toBeUndefined();
    delete process.env[MODE];
    expect(resolveNemotronMode()).toBeUndefined();
  });
});

describe('AC-EGF-5: an unset mode refuses the network', () => {
  it('refuses, and names the missing declaration rather than the vendor host alone', async () => {
    await expect(ask(client())).rejects.toThrow(NemotronEgressRefused);
    await expect(ask(client())).rejects.toThrow(/no transport mode declared/);
  });

  it('refuses under offline mode too, unless a transport is injected', async () => {
    process.env[MODE] = 'offline';
    await expect(ask(client())).rejects.toThrow(/NEMOTRON_MODE=offline/);
  });

  it('does not fall back to the vendor endpoint when the mode is a typo', async () => {
    process.env[MODE] = 'ONLINE'; // not the exact literal
    await expect(ask(client())).rejects.toThrow(NemotronEgressRefused);
  });
});

describe('AC-EGF-6: a declared transport is always honoured', () => {
  it('an injected fetch needs no mode at all', async () => {
    const injected = vi.fn(async () =>
      new Response(
        JSON.stringify({
          id: 'x',
          model: 'test-model',
          choices: [{ message: { role: 'assistant', content: 'ok' } }],
          usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    ) as unknown as typeof fetch;

    const res = await ask(client(injected));
    expect(res.content).toBe('ok');
    expect(injected).toHaveBeenCalledTimes(1);
  });

  it('an injected transport is used even when the mode forbids egress', async () => {
    process.env[MODE] = 'offline';
    const injected = vi.fn(async () =>
      new Response(
        JSON.stringify({
          id: 'x',
          model: 'test-model',
          choices: [{ message: { role: 'assistant', content: 'still ok' } }],
          usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    ) as unknown as typeof fetch;

    const res = await ask(client(injected));
    expect(res.content).toBe('still ok');
  });
});

describe('the guard can fail (mutation check)', () => {
  it('online mode does reach the resolved transport, proving the refusal is conditional', async () => {
    process.env[MODE] = 'online';
    const reached = vi.fn(async () => {
      throw new Error('TRANSPORT_REACHED');
    });
    vi.stubGlobal('fetch', reached);

    // Not a network call: the stub stands in for the vendor. What matters is
    // that the request got past resolveTransport() instead of being refused,
    // which is what makes the refusal above meaningful rather than vacuous.
    await expect(ask(client())).rejects.not.toThrow(NemotronEgressRefused);
    expect(reached).toHaveBeenCalled();
  });
});
