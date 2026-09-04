/**
 * Cross-stack sampling parity, end to end (DEC-036).
 * Requirement Citations:
 * - R-NPW-1: sampling defaults are read from governance-policy.json, never a literal
 * - DEC-036: both stacks send the same sampling parameters to the same endpoint
 *
 * The defect this reproduces: the Node client hard-coded `top_p: 0.7` and the
 * Python bridge omitted `top_p` entirely, so the two stacks sampled differently
 * against one endpoint for as long as the client had existed. The live parity
 * test (`test_wire_format_parity_with_typescript`) could not see it -- it
 * asserts the request *succeeds*, not that the two bodies agree.
 *
 * This test builds both bodies offline and compares them field by field. The
 * Python side is the real `complete_chat`, run in a subprocess with
 * `urllib.request.urlopen` patched to capture the request instead of sending
 * it; the Node side is the real `buildChatRequestBody`. Both read the same
 * shipped `governance-policy.json`, so a divergence here is a divergence on the
 * wire.
 *
 * It lives in the Node suite deliberately. `pnpm`/`tsx` exist only on the
 * `build-full` leg, while the Python regression tier also runs on the three
 * matrix legs -- a Python-side version would have to skip there, and INV-2
 * forbids that. `python` is present wherever this suite runs.
 */

import { describe, it, expect } from 'vitest';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { buildChatRequestBody } from '../../../src/ai/nemotron/request-body.js';
import { loadNemotronPolicy } from '../../../src/ai/nemotron/policy.js';

/** harness/node/tests/ai/e2e -> repository root. */
const REPO_ROOT = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '../../../../..',
);

const MESSAGES = [{ role: 'user' as const, content: 'parity probe' }];
const MODEL = 'parity/model';

/**
 * The exact JSON the Python bridge would POST, captured at the urllib seam.
 * Explicit `model` and `api_key` so no environment variable is consulted; the
 * sampling fields are left to resolve from policy, which is the point.
 */
const PYTHON_PROBE = `
import json, sys, urllib.request
from unittest.mock import MagicMock, patch
from harness.shared.nemotron_bridge import complete_chat

captured = {}
def fake_urlopen(req, timeout=None):
    captured["payload"] = json.loads(req.data.decode("utf-8"))
    resp = MagicMock()
    resp.read.return_value = b'{"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}}'
    resp.__enter__.return_value = resp
    return resp

with patch("urllib.request.urlopen", fake_urlopen):
    complete_chat(json.loads(sys.argv[1]), model=sys.argv[2], api_key="k", timeout_sec=1)
sys.stdout.write(json.dumps(captured["payload"]))
`;

function pythonPayload(): Record<string, unknown> {
  const out = execFileSync(
    process.env['PYTHON'] ?? 'python',
    ['-c', PYTHON_PROBE, JSON.stringify(MESSAGES), MODEL],
    {
      cwd: REPO_ROOT,
      encoding: 'utf-8',
      env: {
        ...process.env,
        PYTHONPATH: REPO_ROOT,
        // The bridge reads these when arguments are omitted; none are omitted
        // here, but a stray value must not be able to change the comparison.
        NVIDIA_API_KEY: '',
        NEMOTRON_DEFAULT_MODEL: '',
      },
    },
  );
  return JSON.parse(out) as Record<string, unknown>;
}

describe('cross-stack sampling parity (DEC-036, R-NPW-1)', () => {
  const python = pythonPayload();
  const node = buildChatRequestBody(
    { messages: MESSAGES },
    MODEL,
    false,
    loadNemotronPolicy(),
  ) as unknown as Record<string, unknown>;

  it('the Python bridge sends top_p at all', () => {
    /** The original defect: the field was absent from the Python payload. */
    expect(python).toHaveProperty('top_p');
  });

  it.each([
    'model',
    'messages',
    'temperature',
    'top_p',
    'max_tokens',
    'stream',
  ])('both stacks agree on %s', (field) => {
    expect(python[field]).toEqual(node[field]);
  });

  it('neither stack sends a sampling field the other does not', () => {
    /**
     * Key-set equality, not just value equality on the fields we thought to
     * name: a field added to one stack and not the other is the shape of the
     * original defect, and enumerating fields by hand is how the live test's
     * docstring came to omit `top_p`.
     */
    const sampling = (body: Record<string, unknown>) =>
      Object.keys(body)
        .filter((k) => !['tools', 'tool_choice', 'stop'].includes(k))
        .sort();
    expect(sampling(python)).toEqual(sampling(node));
  });

  it('the values are the policy values, not coincidence', () => {
    const policy = loadNemotronPolicy();
    expect(python['temperature']).toBe(policy.temperature);
    expect(python['top_p']).toBe(policy.top_p);
    expect(python['max_tokens']).toBe(policy.max_tokens);
  });
});
