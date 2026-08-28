/**
 * NVIDIA Nemotron Environment Resolution Unit Tests.
 * Requirement Citations:
 * - R-AI-NEMO-1: OpenAI-compatible wire protocol with endpoint abstraction
 * - C-AI-SEC-1: Secret sanitization and fail-closed configuration contracts
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { NemotronClient } from '../../../src/ai/nemotron/nemotron-client.js';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

const ENV_KEYS = [
  'NVIDIA_API_KEY',
  'NVIDIA_BASE_URL',
  'NEMOTRON_DEFAULT_MODEL',
  'NEMOTRON_TIMEOUT_MS',
] as const;

describe('Nemotron Environment Resolution (R-AI-NEMO-1, C-AI-SEC-1)', () => {
  const savedEnv: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const key of ENV_KEYS) {
      savedEnv[key] = process.env[key];
      delete process.env[key];
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
    for (const key of ENV_KEYS) {
      if (savedEnv[key] !== undefined) {
        process.env[key] = savedEnv[key];
      } else {
        delete process.env[key];
      }
    }
  });

  it('loads API key, base URL, and model from a .env file when env vars are unset', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'nemo-env-'));
    fs.writeFileSync(
      path.join(tmpDir, '.env'),
      [
        '# comment line must be ignored',
        '',
        'NOISE_LINE_WITHOUT_EQUALS',
        'UNRELATED_KEY=unrelated-value',
        'NVIDIA_BASE_URL=https://dotenv.example.com/v1',
        'NEMOTRON_DEFAULT_MODEL=dotenv/test-model',
        'NVIDIA_API_KEY=nvapi-dotenv-file-key-1234567890',
      ].join('\n'),
      'utf-8',
    );

    const spyCwd = vi.spyOn(process, 'cwd').mockReturnValue(tmpDir);
    try {
      const client = new NemotronClient({});
      expect(client.config.apiKey).toBe('nvapi-dotenv-file-key-1234567890');
      expect(client.config.baseUrl).toBe('https://dotenv.example.com/v1');
      expect(client.config.defaultModel).toBe('dotenv/test-model');
    } finally {
      spyCwd.mockRestore();
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('leaves the API key unset when the .env file does not declare one', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'nemo-env-'));
    fs.writeFileSync(
      path.join(tmpDir, '.env'),
      'SOME_OTHER_SETTING=value\n',
      'utf-8',
    );

    const spyCwd = vi.spyOn(process, 'cwd').mockReturnValue(tmpDir);
    try {
      const client = new NemotronClient({});
      // Fail-closed: no key means requests must be refused, not sent bare.
      expect(client.config.apiKey).toBeUndefined();
    } finally {
      spyCwd.mockRestore();
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('reads endpoint, model, and timeout directly from process.env when present', () => {
    process.env['NVIDIA_API_KEY'] = 'nvapi-process-env-key-1234567890';
    process.env['NVIDIA_BASE_URL'] = 'https://env.example.com/v1';
    process.env['NEMOTRON_DEFAULT_MODEL'] = 'env/test-model';
    process.env['NEMOTRON_TIMEOUT_MS'] = '12345';

    const client = new NemotronClient({});
    expect(client.config.apiKey).toBe('nvapi-process-env-key-1234567890');
    expect(client.config.baseUrl).toBe('https://env.example.com/v1');
    expect(client.config.defaultModel).toBe('env/test-model');
    expect(client.config.timeoutMs).toBe(12345);
  });

  it('rejects complete() with a configuration error when no model is resolvable', async () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'nemo-env-'));
    const spyCwd = vi.spyOn(process, 'cwd').mockReturnValue(tmpDir);
    try {
      const client = new NemotronClient({
        apiKey: 'nvapi-mock-key-1234567890',
      });
      await expect(
        client.complete({ messages: [{ role: 'user', content: 'hi' }] }),
      ).rejects.toThrow(/Target model is not configured/);
    } finally {
      spyCwd.mockRestore();
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('rejects stream() with a configuration error when no model is resolvable', async () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'nemo-env-'));
    const spyCwd = vi.spyOn(process, 'cwd').mockReturnValue(tmpDir);
    try {
      const client = new NemotronClient({
        apiKey: 'nvapi-mock-key-1234567890',
      });
      await expect(async () => {
        for await (const chunk of client.stream({
          messages: [{ role: 'user', content: 'hi' }],
        })) {
          void chunk;
        }
      }).rejects.toThrow(/Target model is not configured/);
    } finally {
      spyCwd.mockRestore();
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
