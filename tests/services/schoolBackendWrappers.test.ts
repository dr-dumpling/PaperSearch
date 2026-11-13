import { describe, expect, it } from "@jest/globals";
import type { SchoolBackend } from "../../src/capabilities/pdf-discovery/school/types.js";
import { withAutoUpdate } from "../../src/management/school/autoUpdate.js";
import { withCliSchoolProgress } from "../../src/management/school/cliProgress.js";

/**
 * The wrappers around the backend (auto-update, the CLI's progress) name each
 * method they pass on: one left out is silently gone, as the papers' report was
 * until an integration test missed its calls (2026-11-10).
 */
const METHODS = ["probe", "downloadLegalDoi", "withBatchSession", "reportBatchProgress", "reportBatchPapers", "keepSession"] as const;
// Fails to compile when SchoolBackend gains a method this list does not name.
const unlisted: Record<Exclude<keyof SchoolBackend, (typeof METHODS)[number]>, never> = {};

function backend(calls: string[]): SchoolBackend {
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
    keepSession: async () => {
      calls.push("keepSession");
      return true;
    },
  };
}

async function callEach(wrapped: SchoolBackend, methods: readonly (typeof METHODS)[number][]): Promise<void> {
  for (const method of methods) {
    expect(typeof wrapped[method]).toBe("function");
    if (method === "probe") await wrapped.probe();
    if (method === "downloadLegalDoi") await wrapped.downloadLegalDoi({ identifier: "10.1000/one", outputDir: "/tmp" });
    if (method === "reportBatchProgress") {
      await wrapped.reportBatchProgress!({ id: "b", total: 1, done: 0, succeeded: 0, failed: 0, finished: false });
    }
    if (method === "reportBatchPapers") await wrapped.reportBatchPapers!({ id: "b", folder: "/tmp", papers: [] });
    if (method === "keepSession") await wrapped.keepSession!();
  }
}

describe("backend wrappers", () => {
  it("pass on every method of the backend, also inside a batch's session", async () => {
    expect(unlisted).toEqual({});
    const wrappers: Array<[string, (inner: SchoolBackend) => SchoolBackend]> = [
      ["auto-update", (inner) => withAutoUpdate(inner, async () => undefined)],
      ["CLI progress", withCliSchoolProgress],
      ["both, as the CLI builds them", (inner) => withCliSchoolProgress(withAutoUpdate(inner, async () => undefined))],
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
