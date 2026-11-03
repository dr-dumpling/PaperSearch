/**
 * Jest Test Setup
 * Global setup for all tests
 */

import { jest, beforeAll, afterAll, afterEach } from '@jest/globals';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// Set test environment
process.env.NODE_ENV = 'test';
// Run ledgers from tests never land in the user's data directory.
process.env.PAPER_SEARCH_RUNLOG_DIR = mkdtempSync(join(tmpdir(), 'paper-search-runlog-'));
// CLI runs from tests never update the user's installed Skill; the sync's own tests turn it on.
process.env.PAPER_SEARCH_SKILL_AUTO_UPDATE = 'false';

// Increase timeout for API tests
jest.setTimeout(30000);

// Mock console.error to reduce noise in tests
const originalConsoleError = console.error;
beforeAll(() => {
  console.error = jest.fn() as typeof console.error;
});

afterAll(() => {
  console.error = originalConsoleError;
});

// Clean up environment variables after each test
afterEach(() => {
  // Reset specific env vars that tests might modify
  delete process.env.WOS_API_VERSION;
  delete process.env.CROSSREF_MAILTO;
  delete process.env.WOS_VERBOSE_LOGGING;
  delete process.env.IEEE_API_KEY;
  delete process.env.GOOGLE_SCHOLAR_PROXY_URL;
  delete process.env.SCHOLAR_RATE_LIMIT_RPS;
  delete process.env.SCHOLAR_MAX_RETRIES;
  delete process.env.SCHOLAR_TIMEOUT_MS;
});

export {};
