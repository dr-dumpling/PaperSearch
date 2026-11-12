import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "@jest/globals";
import { downloadBatch } from "../../src/capabilities/pdf-discovery/batch.js";
import type { DownloadTier } from "../../src/capabilities/pdf-discovery/DownloadTier.js";
import { normalizeDownloadResult } from "../../src/capabilities/pdf-discovery/school/SchoolResultNormalizer.js";
import { selectSchoolBatchSupport } from "../../src/capabilities/pdf-discovery/school/SchoolReadiness.js";
import type { SchoolBackend, SchoolBatchUpdate, SchoolDownloadRequest } from "../../src/capabilities/pdf-discovery/school/index.js";
import { fetchSupplementsOnly } from "../../src/capabilities/pdf-discovery/tiers/entitledAccess.js";
import { decodeSchoolProgress } from "../../src/capabilities/pdf-discovery/school/SchoolProgress.js";

const toolResult = (payload: unknown) => ({ content: [{ type: "text", text: JSON.stringify(payload) }] });

describe("supplementary files", () => {
  it.each([
    ["supplements", "two_phase"], ["both", "two_phase"], ["both", "per_item"],
  ] as Array<["supplements" | "both", "two_phase" | "per_item"]>)("%s / %s keeps a serial attachment batch and finishes only after its last visit", async (content, mode) => {
    const root = mkdtempSync(join(tmpdir(), "supplement-progress-"));
    const requests: SchoolDownloadRequest[] = [];
    const updates: SchoolBatchUpdate[] = [];
    const sequence: string[] = [];
    const backend: SchoolBackend = {
      probe: async () => ({ state: "available", code: "ready", message: "", missing: [] }),
      downloadLegalDoi: async (request) => {
        requests.push(request);
        sequence.push(`visit:${request.identifier}`);
        return { kind: "attempt_error", identifier: request.identifier, code: "supplements_only", message: "",
          supplements: request.identifier === "10.1000/b" ? [{ label: "S1", status: "failed", reason: "http_404" }] : [] };
      },
      reportBatchProgress: async (update) => {
        updates.push(update);
        if (update.finished) sequence.push("finished");
        return true;
      },
    };
    const tiers = (): DownloadTier[] => [{ id: "oa", stage: "unpaywall", run: async () => {
      expect(content).toBe("both");
      return { status: "ok", verified: true, path: join(root, "main.pdf"), message: "fixture" };
    }}];
    try {
      const result = await downloadBatch({} as never, {
        content, mode, savePath: root, items: ["a", "b", "c"].map(id => ({ doi: `10.1000/${id}` })),
      }, backend, () => {}, tiers);
      expect(requests.map(r => r.batch)).toEqual([
        { id: result.batchId, index: 1, total: 3, done: 0, succeeded: 0, failed: 0 },
        { id: result.batchId, index: 2, total: 3, done: 1, succeeded: 1, failed: 0 },
        { id: result.batchId, index: 3, total: 3, done: 2,
          succeeded: mode === "per_item" ? 2 : 1, failed: mode === "per_item" ? 0 : 1 },
      ]);
      expect(requests.every(r => r.supplements === "only")).toBe(true);
      // The last visit ends the attachment stretch; then the batch's outcome for the finished window.
      expect(sequence).toEqual(["visit:10.1000/a", "visit:10.1000/b", "visit:10.1000/c", "finished", "finished"]);
      expect(updates.at(-2)).toEqual(expect.objectContaining({ total: 3, done: 3, finished: true,
        succeeded: mode === "per_item" ? 3 : 2, failed: mode === "per_item" ? 0 : 1 }));
      expect(updates.at(-1)?.results).toEqual(content === "supplements"
        ? expect.objectContaining({ content, main: 0, supplements: 0, no_supplements: 2,
            failures: [{ cls: "unexplained", reason: "附录没下载成功", doi: "10.1000/b" }] })
        : expect.objectContaining({ content, main: 3, failures: [] }));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("reports a completed attachment check without claiming a PDF was saved", () => {
    expect(decodeSchoolProgress({ message: "school.stage:supplements_checked" }, "10.1000/example")).toEqual({
      identifier: "10.1000/example", stage: "supplements_checked",
      message: "补充材料检查已完成，正在整理文件结果。",
    });
  });
  it("keeps a confirmed empty discovery through normalization and the supplements-only flow", async () => {
    const outcome = normalizeDownloadResult(toolResult({
      success: false, error_type: "supplements_only", supplements: [],
    }), "10.3389/fbioe.2022.905869", "/out");
    const backend: SchoolBackend = {
      probe: async () => ({ state: "available", code: "ok", message: "", missing: [] }),
      downloadLegalDoi: async () => outcome,
    };
    expect(await fetchSupplementsOnly(backend, { identifier: "10.3389/fbioe.2022.905869", outputDir: "/out" })).toEqual([]);
    for (const invalid of [undefined, [{ status: "saved", file: "/elsewhere/s.pdf" }], [{ status: "invalid" }]]) {
      const unknown = normalizeDownloadResult(toolResult({
        success: false, error_type: "source_exception", supplements: invalid,
      }), "10.1000/unknown", "/out");
      expect(unknown).not.toHaveProperty("supplements");
      expect(await fetchSupplementsOnly({ ...backend, downloadLegalDoi: async () => unknown },
        { identifier: "10.1000/unknown", outputDir: "/out" })).toEqual([
          { label: "", status: "failed", reason: "source_exception" },
        ]);
    }
  });

  it("does not turn an unrelated backend error or an absent list into a successful empty check", async () => {
    for (const payload of [
      { success: false, error_type: "source_exception", supplements: [] },
      { success: true, file: "/out/main.pdf" },
    ]) {
      const outcome = normalizeDownloadResult(toolResult(payload), "10.1000/unknown", "/out");
      const backend: SchoolBackend = {
        probe: async () => ({ state: "available", code: "ok", message: "", missing: [] }),
        downloadLegalDoi: async () => outcome,
      };
      expect(await fetchSupplementsOnly(backend, { identifier: "10.1000/unknown", outputDir: "/out" }))
        .toEqual([{ label: "", status: "failed", reason: payload.success ? "supplements_not_reported" : "source_exception" }]);
    }
  });

  it("keeps saved files inside the output directory and code-like reasons only", () => {
    const outcome = normalizeDownloadResult(
      toolResult({
        success: true,
        file: "/out/x.pdf",
        supplements: [
          { status: "saved", file: "/out/10.1_x_supplements/S1.pdf", size: 1200.4, label: "Table S1 https://x.example/a\n data" },
          { status: "saved", file: "/elsewhere/S2.pdf", label: "outside" },
          { status: "failed", reason: "http_404", label: "S3" },
          { status: "failed", reason: "TimeoutError: waited 60 s for https://x", label: "S4" },
          { status: "weird", label: "dropped" },
        ],
      }),
      "10.1/x",
      "/out",
    );
    expect(outcome).toEqual(
      expect.objectContaining({
        supplements: [
          { status: "saved", file: "/out/10.1_x_supplements/S1.pdf", size: 1200, label: "Table S1 data" },
          { status: "failed", reason: "http_404", label: "S3" },
          { status: "failed", reason: "TimeoutError", label: "S4" },
        ],
      }),
    );
  });

  it("sends the supplements field only to a backend that declares it", () => {
    const base = {
      identifier: { type: "string" }, output_dir: { type: "string" }, scihub_enabled: { type: "boolean" },
      use_tor: { type: "boolean" }, use_vpnsci: { type: "boolean" }, bibtex: { type: "boolean" },
      strategy: { type: "string", enum: ["legal_only", "institutional_only"] },
    };
    const tool = (props: Record<string, unknown>) => [{ name: "school_download", inputSchema: { type: "object", properties: props } }];
    expect(selectSchoolBatchSupport(tool({ ...base, supplements: { type: "string", enum: ["with", "only"] } }), "legal_only").supplementsField).toBe(true);
    expect(selectSchoolBatchSupport(tool(base), "legal_only").supplementsField).toBe(false);
  });

  it("two_phase: entitled items ask for supplements, open items get a supplements-only visit", async () => {
    const requests: SchoolDownloadRequest[] = [];
    const backend: SchoolBackend = {
      probe: async () => ({ state: "available", code: "ok", message: "", missing: [] }),
      downloadLegalDoi: async (request) => {
        requests.push(request);
        return {
          kind: "attempt_error", identifier: request.identifier, code: "supplements_only", message: "",
          supplements: [{ status: "saved", file: `${request.outputDir}/s.pdf`, label: "S1" }],
        };
      },
      reportBatchProgress: async () => true,
    };
    const tiers = (): DownloadTier[] => [
      { id: "oa", stage: "unpaywall", run: async (c) => (c.doi === "10.1000/oa" ? { status: "ok", verified: true, path: "/tmp/oa.pdf", message: "ok" } : { status: "skipped", message: "no" }) },
      {
        id: "entitled_access", stage: "entitled_access",
        run: async (c) => {
          expect(c.withSupplements).toBe(true);
          return { status: "ok", verified: true, path: "/tmp/ent.pdf", message: "ok", supplements: [{ status: "saved", file: "/tmp/e/s.pdf", label: "E1" }] };
        },
      },
    ];
    const result = await downloadBatch(
      {} as never,
      { items: [{ doi: "10.1000/oa" }, { doi: "10.1000/closed" }], savePath: "/tmp/out", content: "both" },
      backend, () => {}, tiers,
    );
    expect(result.items.map((i) => i.supplements?.[0]?.label)).toEqual(["S1", "E1"]);
    expect(requests).toEqual([expect.objectContaining({ identifier: "10.1000/oa", supplements: "only", outputDir: expect.stringMatching(/^\/tmp\/out\/[^/]+_[0-9a-f]{10}$/) })]);
    const ledger = readFileSync(join(result.runLog!, "items.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
    expect(ledger.find((i) => i.doi === "10.1000/oa").supplements[0].label).toBe("S1");
    expect(ledger.find((i) => i.doi === "10.1000/oa").stages.map((s: { stage: string }) => s.stage)).toContain("supplements");
  });

  it("stops during supplements without losing saved main texts or visiting later items", async () => {
    for (const mode of ["two_phase", "per_item"] as const) {
      for (const content of ["both", "supplements"] as const) {
        const visited: string[] = [];
        const backend: SchoolBackend = {
          probe: async () => ({ state: "available", code: "ready", message: "", missing: [] }),
          downloadLegalDoi: async (request) => {
            visited.push(request.identifier);
            return { kind: "attempt_error", identifier: request.identifier, code: "batch_stopped", message: "stopped" };
          },
        };
        const tiers = (): DownloadTier[] => [{ id: "oa", stage: "unpaywall",
          run: async (c) => ({ status: "ok", verified: true, path: `/tmp/${c.doi}.pdf`, message: "ok" }) }];
        const result = await downloadBatch({} as never, {
          items: [{ doi: "10.1000/a" }, { doi: "10.1000/b" }], content, mode,
        }, backend, () => {}, tiers);
        expect(visited).toEqual(["10.1000/a"]);
        expect(result.items[0].supplements?.[0]?.reason).toBe("batch_stopped");
        if (content === "both") {
          expect(result.items[0].status).toBe("ok");
          expect(result.items[0].path).toBe("/tmp/10.1000/a.pdf");
          if (mode === "two_phase") {
            expect(result.items[1].status).toBe("ok");
            expect(result.items[1].supplements?.[0]?.reason).toBe("batch_stopped");
          } else expect(result.items[1].status).toBe("error");
        } else expect(result.items.every((item) => item.status === "error")).toBe(true);
      }
    }
  });

  it.each(["two_phase", "per_item"] as const)("%s keeps the last saved files when stop arrives during backend cleanup", async (mode) => {
    const visited: string[] = [];
    const tiers = (): DownloadTier[] => [{ id: "entitled_access", stage: "entitled_access",
      run: async (context) => {
        visited.push(context.doi!);
        return { status: "ok", verified: true, path: "/tmp/saved.pdf", message: "saved",
          code: "batch_stopped",
          supplements: [{ status: "saved", label: "S1", file: "/tmp/supplement.txt" }] };
      } }];
    const result = await downloadBatch({} as never, {
      items: [{ doi: "10.1000/a" }, { doi: "10.1000/b" }], content: "both", mode,
    }, undefined, () => {}, tiers);
    expect(visited).toEqual(["10.1000/a"]);
    expect(result.items[0].status).toBe("ok");
    expect(result.items[0].path).toBe("/tmp/saved.pdf");
    expect(result.items[0].supplements?.[0].status).toBe("saved");
    expect(result.items[1].attempts.some(a => a.code === "batch_stopped")).toBe(true);
  });

  it("does nothing extra when supplements are not requested", async () => {
    const backend = { probe: async () => ({ state: "available", code: "", message: "", missing: [] }), downloadLegalDoi: async () => { throw new Error("must not be called"); } } as unknown as SchoolBackend;
    const tiers = (): DownloadTier[] => [{ id: "oa", stage: "unpaywall", run: async () => ({ status: "ok", verified: true, path: "/tmp/oa.pdf", message: "ok" }) }];
    const result = await downloadBatch({} as never, { items: [{ doi: "10.1000/oa" }] }, backend, () => {}, tiers);
    expect(result.items[0].supplements).toBeUndefined();
  });
});

describe("content switch", () => {
  const backendWith = (requests: SchoolDownloadRequest[]): SchoolBackend => ({
    probe: async () => ({ state: "available", code: "ok", message: "", missing: [] }),
    downloadLegalDoi: async (request) => {
      requests.push(request);
      return { kind: "attempt_error", identifier: request.identifier, code: "supplements_only", message: "",
        supplements: request.identifier === "10.1000/none" ? [] : [{ status: "saved", file: `${request.outputDir}/s.pdf`, label: "S1" }] };
    },
    reportBatchProgress: async () => true,
  });

  it("supplements: an empty completed check is not counted as a failure", async () => {
    const requests: SchoolDownloadRequest[] = [];
    const tiers = (): DownloadTier[] => [{ id: "oa", stage: "unpaywall", run: async () => { throw new Error("main text must not be fetched"); } }];
    const result = await downloadBatch(
      {} as never,
      { items: [{ doi: "10.1000/a" }, { doi: "10.1000/none" }], savePath: "/tmp/out", content: "supplements" },
      backendWith(requests), () => {}, tiers,
    );
    expect(result.content).toBe("supplements");
    expect(result.items.map((i) => [i.status, i.attempts.map((a) => a.stage)])).toEqual([["ok", ["supplements"]], ["ok", ["supplements"]]]);
    expect(result.succeeded).toBe(2);
    expect(result.failed).toBe(0);
    expect(result.items[1].attempts[0].status).toBe("skipped");
    expect(result.items[1].attempts[0].code).toBe("no_supplements");
    expect(requests.map((r) => r.supplements)).toEqual(["only", "only"]);
  });

  it("main (default): supplementary files are never requested", async () => {
    const requests: SchoolDownloadRequest[] = [];
    const tiers = (): DownloadTier[] => [
      { id: "oa", stage: "unpaywall", run: async () => ({ status: "skipped", message: "no" }) },
      { id: "entitled_access", stage: "entitled_access", run: async (c) => { expect(c.withSupplements).toBeUndefined(); return { status: "ok", verified: true, path: "/tmp/e.pdf", message: "ok" }; } },
    ];
    const result = await downloadBatch({} as never, { items: [{ doi: "10.1000/a" }] }, backendWith(requests), () => {}, tiers);
    expect(result.content).toBe("main");
    expect(requests).toEqual([]);
  });
});
