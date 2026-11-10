import { describe, expect, it } from "@jest/globals";
import type { CarsiBackend } from "../../src/capabilities/pdf-discovery/carsi/types.js";
import { withAutoUpdate } from "../../src/management/carsi/autoUpdate.js";
import { withCliCarsiProgress } from "../../src/management/carsi/cliProgress.js";

/**
 * The wrappers around the backend (auto-update, the CLI's progress) name each
 * method they pass on: one left out is silently gone, as the papers' report was
 * until an integration test missed its calls (2026-11-10).
 */
const METHODS = ["probe", "downloadLegalDoi", "withBatchSession", "reportBatchProgress", "reportBatchPapers"] as const;
// Fails to compile when CarsiBackend gains a method this list does not name.
const unlisted: Record<Exclude<keyof CarsiBackend, (typeof METHODS)[number]>, never> = {};

function backend(calls: string[]): CarsiBackend {
  return {
    probe: async () => {
      calls.push("probe");
      return { state: "available", code: "ready", message: "", missing: [] };
    },
    downloadLegalDoi: async (request) => {
      calls.push("downloadLegalDoi");
      return { kind: "attempt_error", identifier: request.identifier, code: "fixture", message: "" };
    },
    withBatchSession: async (run) => {
      calls.push("withBatchSession");
      return run(backend(calls));
    },
    reportBatchProgress: async () => {
      calls.push("reportBatchProgress");
      return true;
    },
    reportBatchPapers: async () => {
      calls.push("reportBatchPapers");
      return true;
    },
  };
}

async function callEach(wrapped: CarsiBackend, methods: readonly (typeof METHODS)[number][]): Promise<void> {
  for (const method of methods) {
    expect(typeof wrapped[method]).toBe("function");
    if (method === "probe") await wrapped.probe();
    if (method === "downloadLegalDoi") await wrapped.downloadLegalDoi({ identifier: "10.1000/one", outputDir: "/tmp" });
    if (method === "reportBatchProgress") {
      await wrapped.reportBatchProgress!({ id: "b", total: 1, done: 0, succeeded: 0, failed: 0, finished: false });
    }
    if (method === "reportBatchPapers") await wrapped.reportBatchPapers!({ id: "b", folder: "/tmp", papers: [] });
  }
}

describe("backend wrappers", () => {
  it("pass on every method of the backend, also inside a batch's session", async () => {
    expect(unlisted).toEqual({});
    const wrappers: Array<[string, (inner: CarsiBackend) => CarsiBackend]> = [
      ["auto-update", (inner) => withAutoUpdate(inner, async () => undefined)],
      ["CLI progress", withCliCarsiProgress],
      ["both, as the CLI builds them", (inner) => withCliCarsiProgress(withAutoUpdate(inner, async () => undefined))],
    ];
    for (const [name, wrap] of wrappers) {
      const calls: string[] = [];
      const wrapped = wrap(backend(calls));
      await callEach(wrapped, METHODS.filter((method) => method !== "withBatchSession"));
      await wrapped.withBatchSession!((scoped) => callEach(scoped, METHODS.filter((method) => method !== "withBatchSession")));
      expect([name, calls]).toEqual([name, [...METHODS.filter((method) => method !== "withBatchSession"), "withBatchSession",
        ...METHODS.filter((method) => method !== "withBatchSession")]]);
    }
  });
});
