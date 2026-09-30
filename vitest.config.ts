import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Most specs drive the pure engine and need no DOM. Specs that touch
    // localStorage opt in with a `// @vitest-environment jsdom` first line.
    environment: 'node',
    globals: true,
  },
});
