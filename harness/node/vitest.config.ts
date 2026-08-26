import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts', 'src/**/*.test.ts'],
    dangerouslyIgnoreUnhandledErrors: false,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'cobertura'],
      reportsDirectory: './coverage',
      // Vitest 4 removed coverage.all. Explicit include is what causes matching
      // uncovered files to appear at 0%.
      include: ['src/**/*.ts'],
      exclude: ['src/**/*.d.ts'],
      thresholds: {
        lines: 90,
        statements: 90,
        branches: 80,
        functions: 90,
        perFile: true,
      },
    },
  },
});
