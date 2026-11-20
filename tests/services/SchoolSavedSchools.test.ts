import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "@jest/globals";
import { createSchoolDownloadArguments, selectSchoolBatchSupport } from "../../src/infrastructure/school/SchoolReadiness.js";
import { createEntitledAccessTier } from "../../src/capabilities/download/content/pdf/school.js";
import { fulltextPageVisit } from "../../src/capabilities/download/content/markdown/pageVisit.js";
import { planResume } from "../../src/capabilities/download/batch/resume.js";
import { DownloadBatchSchema } from "../../src/capabilities/download/schemas.js";
import type { SchoolBackend, SchoolDownloadRequest } from "../../src/infrastructure/school/index.js";

// Several saved schools (user, 2026-11-17): a batch may use another saved school for itself
// alone, only when the user names it; the configured school is not changed.
describe("another saved school for a batch", () => {
  it("is sent to a backend whose download tool declares school, and only then", () => {
    const declared = (school: boolean) => [{
      name: "school_download",
      inputSchema: {
        type: "object",
        properties: Object.fromEntries(Object.keys({ ...createSchoolDownloadArguments("10.1/x", "out", "legal_only"),
          ...(school ? { school: "x" } : {}) }).map((name) => [name, {}])),
        required: ["identifier"],
      },
    }];
    expect(selectSchoolBatchSupport(declared(true) as never, "legal_only").schoolField).toBe(true);
    expect(selectSchoolBatchSupport(declared(false) as never, "legal_only").schoolField).toBeUndefined();
    expect(createSchoolDownloadArguments("10.1/x", "out", "legal_only", undefined, undefined, undefined, undefined, undefined, undefined, "Red Magnolia University"))
      .toMatchObject({ school: "Red Magnolia University" });
    expect(createSchoolDownloadArguments("10.1/x", "out")).not.toHaveProperty("school");
  });

  it("goes with the PDF's visit and a visit for the page alone", async () => {
    const requests: SchoolDownloadRequest[] = [];
    const backend = {
      downloadLegalDoi: async (request: SchoolDownloadRequest) => {
        requests.push(request);
        return { kind: "attempt_error", identifier: request.identifier, code: "download_failed", message: "" };
      },
    } as unknown as SchoolBackend;
    await createEntitledAccessTier(backend).run({
      useEntitledAccess: true, useSciHub: false, doi: "10.1126/x", paperId: "10.1126/x", savePath: "/tmp/out",
      source: "crossref", searchers: {} as never, school: "Red Magnolia University",
    });
    await fulltextPageVisit(backend, { school: "Red Magnolia University" })!("10.1126/y", "/tmp/out", "/tmp/out/diagnostics");
    expect(requests.map((request) => [request.identifier, request.school])).toEqual([
      ["10.1126/x", "Red Magnolia University"], ["10.1126/y", "Red Magnolia University"]]);
  });

  it("is a batch's option, and 接着下 uses the school the batch last used", () => {
    expect(DownloadBatchSchema.parse({ items: [{ doi: "10.1/x" }], school: "Red Magnolia University" }).school).toBe("Red Magnolia University");
    const root = mkdtempSync(join(tmpdir(), "saved-schools-"));
    try {
      const run = (id: string, info: Record<string, unknown>) => {
        mkdirSync(join(root, id), { recursive: true });
        writeFileSync(join(root, id, "run.json"), JSON.stringify({ schema: 1, runId: id, kind: "download_batch", total: 1, content: "main", ...info }));
        writeFileSync(join(root, id, "items.jsonl"), JSON.stringify({ index: 1, doi: "10.1/x", status: "error", stages: [] }) + "\n");
      };
      run("20261117-200000-aaaaaa", { savePath: join(root, "batch"), school: "Red Magnolia University" });
      const plan = planResume("20261117-200000-aaaaaa", { PAPER_SEARCH_RUNLOG_DIR: root });
      expect(typeof plan === "string" ? plan : plan.school).toBe("Red Magnolia University");
      // A later run of the chain with another school: that one.
      run("20261117-210000-bbbbbb", { savePath: join(root, "batch"), resumeOf: "20261117-200000-aaaaaa", school: "Grey Heron College" });
      const later = planResume("20261117-200000-aaaaaa", { PAPER_SEARCH_RUNLOG_DIR: root });
      expect(typeof later === "string" ? later : later.school).toBe("Grey Heron College");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

