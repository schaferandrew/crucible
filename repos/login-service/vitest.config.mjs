import os from 'node:os';
import path from 'node:path';
import { defineConfig } from 'vitest/config';

// Tests write their audit trail to a temp file, not to .crucible/audit.jsonl
export default defineConfig({
  test: {
    env: { AUDIT_LOG: path.join(os.tmpdir(), `login-service-tests-${process.pid}.jsonl`) },
    testTimeout: 15000,
  },
});
