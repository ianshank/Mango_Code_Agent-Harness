/**
 * NVIDIA Nemotron Ultra CLI Runner.
 *
 * Requirement Citations:
 * - R-AI-NEMO-1: CLI invocation of Nemotron reasoning models
 * - C-AI-SEC-1: Safe argument parsing and secret protection
 */

import { NemotronClient } from './nemotron-client.js';

export async function runNemotronCli(
  args: string[] = process.argv.slice(2),
): Promise<void> {
  const promptIdx = args.indexOf('--prompt');
  const prompt =
    promptIdx !== -1 && args[promptIdx + 1] ? args[promptIdx + 1] : null;

  if (!prompt || args.includes('--help') || args.includes('-h')) {
    console.log(`
NVIDIA Nemotron Ultra CLI Runner
Usage:
  npx tsx src/ai/nemotron/cli.ts --prompt "Your question" [options]

Options:
  --prompt <string>       Prompt to send to Nemotron Ultra
  --system <string>       System instruction prompt
  --model <string>        Target model identifier (default: from NEMOTRON_DEFAULT_MODEL env)
  --temperature <number>  Sampling temperature (0.0 - 2.0, default: 0.2)
  --stream                Enable streaming response output
  --json                  Output full JSON response with telemetry
  --help, -h              Show this help message
`);
    return;
  }

  const systemIdx = args.indexOf('--system');
  const systemPrompt =
    systemIdx !== -1 && args[systemIdx + 1]
      ? args[systemIdx + 1]
      : 'You are an expert AI architect and reasoning assistant.';

  const modelIdx = args.indexOf('--model');
  const model =
    modelIdx !== -1 && args[modelIdx + 1] ? args[modelIdx + 1] : undefined;

  const tempIdx = args.indexOf('--temperature');
  const rawTemp = tempIdx !== -1 ? args[tempIdx + 1] : undefined;
  const temperature = rawTemp ? parseFloat(rawTemp) : 0.2;

  const isStream = args.includes('--stream');
  const isJson = args.includes('--json');

  const client = new NemotronClient();

  const messages = [
    ...(systemPrompt
      ? [{ role: 'system' as const, content: systemPrompt }]
      : []),
    { role: 'user' as const, content: prompt },
  ];

  try {
    if (isStream) {
      process.stdout.write('\n--- Nemotron Streaming Response ---\n');
      for await (const chunk of client.stream({
        ...(model !== undefined ? { model } : {}),
        messages,
        temperature,
      })) {
        process.stdout.write(chunk.delta);
      }
      process.stdout.write('\n\n');
    } else {
      const response = await client.complete({
        ...(model !== undefined ? { model } : {}),
        messages,
        temperature,
      });
      if (isJson) {
        console.log(JSON.stringify(response, null, 2));
      } else {
        console.log(
          `\n--- Nemotron Response [${response.model}] (${response.latencyMs}ms) ---\n`,
        );
        console.log(response.content);
        console.log(
          `\nTokens: ${response.usage.promptTokens} prompt + ${response.usage.completionTokens} completion = ${response.usage.totalTokens} total\n`,
        );
      }
    }
  } catch (err: any) {
    console.error(`\n[Nemotron CLI Error]: ${err.message}\n`);
    process.exitCode = 1;
  }
}

// Auto-run if executed directly as entrypoint
if (
  import.meta.url === `file://${process.argv[1]}` ||
  process.argv[1]?.endsWith('cli.ts') ||
  process.argv[1]?.endsWith('cli.js')
) {
  runNemotronCli();
}
