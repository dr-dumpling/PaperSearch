import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "@jest/globals";
import { downloadBatch } from "../../src/capabilities/pdf-discovery/batch.js";
import type { DownloadTier } from "../../src/capabilities/pdf-discovery/DownloadTier.js";
import { normalizeDownloadResult } from "../../src/capabilities/pdf-discovery/carsi/CarsiResultNormalizer.js";
import { selectCarsiBatchSupport } from "../../src/capabilities/pdf-discovery/carsi/CarsiReadiness.js";
import type { CarsiBackend, CarsiDownloadRequest } from "../../src/capabilities/pdf-discovery/carsi/index.js";
import { fetchSupplementsOnly } from "../../src/capabilities/pdf-discovery/tiers/entitledAccess.js";
import { decodeCarsiProgress } from "../../src/capabilities/pdf-discovery/carsi/CarsiProgress.js";

const toolResult = (payload: unknown) => ({ content: [{ type: "text", text: JSON.stringify(payload) }] });

describe("supplementary files", () => {
  it("reports a completed attachment check without claiming a PDF was saved", () => {
    expect(decodeCarsiProgress({ message: "carsi.stage:supplements_checked" }, "10.1000/example")).toEqual({
      identifier: "10.1000/example", stage: "supplements_checked",
      message: "补充材料检查已完成，正在整理文件结果。",
    });
  });
  it("keeps a confirmed empty discovery through normalization and the supplements-only flow", async () => {
    const outcome = normalizeDownloadResult(toolResult({
      success: false, error_type: "supplements_only", supplements: [],
    }), "10.3389/fbioe.2022.905869", "/out");
    const backend: CarsiBackend = {
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
      const backend: CarsiBackend = {
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
    const tool = (props: Record<string, unknown>) => [{ name: "carsi_download", inputSchema: { type: "object", properties: props } }];
    expect(selectCarsiBatchSupport(tool({ ...base, supplements: { type: "string", enum: ["with", "only"] } }), "legal_only").supplementsField).toBe(true);
    expect(selectCarsiBatchSupport(tool(base), "legal_only").supplementsField).toBe(false);
  });

  it("two_phase: entitled items ask for supplements, open items get a supplements-only visit", async () => {
    const requests: CarsiDownloadRequest[] = [];
    const backend: CarsiBackend = {
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
    expect(requests).toEqual([expect.objectContaining({ identifier: "10.1000/oa", supplements: "only", outputDir: expect.stringContaining("/tmp/out/papers/") })]);
    const ledger = readFileSync(join(result.runLog!, "items.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
    expect(ledger.find((i) => i.doi === "10.1000/oa").supplements[0].label).toBe("S1");
    expect(ledger.find((i) => i.doi === "10.1000/oa").stages.map((s: { stage: string }) => s.stage)).toContain("supplements");
  });

  it("stops during supplements without losing saved main texts or visiting later items", async () => {
    for (const mode of ["two_phase", "per_item"] as const) {
      for (const content of ["both", "supplements"] as const) {
        const visited: string[] = [];
        const backend: CarsiBackend = {
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

  it("does nothing extra when supplements are not requested", async () => {
    const backend = { probe: async () => ({ state: "available", code: "", message: "", missing: [] }), downloadLegalDoi: async () => { throw new Error("must not be called"); } } as unknown as CarsiBackend;
    const tiers = (): DownloadTier[] => [{ id: "oa", stage: "unpaywall", run: async () => ({ status: "ok", verified: true, path: "/tmp/oa.pdf", message: "ok" }) }];
    const result = await downloadBatch({} as never, { items: [{ doi: "10.1000/oa" }] }, backend, () => {}, tiers);
    expect(result.items[0].supplements).toBeUndefined();
  });
});

describe("content switch", () => {
  const backendWith = (requests: CarsiDownloadRequest[]): CarsiBackend => ({
    probe: async () => ({ state: "available", code: "ok", message: "", missing: [] }),
    downloadLegalDoi: async (request) => {
      requests.push(request);
      return { kind: "attempt_error", identifier: request.identifier, code: "supplements_only", message: "",
        supplements: request.identifier === "10.1000/none" ? [] : [{ status: "saved", file: `${request.outputDir}/s.pdf`, label: "S1" }] };
    },
    reportBatchProgress: async () => true,
  });

  it("supplements: an empty completed check is not counted as a failure", async () => {
    const requests: CarsiDownloadRequest[] = [];
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
    const requests: CarsiDownloadRequest[] = [];
    const tiers = (): DownloadTier[] => [
      { id: "oa", stage: "unpaywall", run: async () => ({ status: "skipped", message: "no" }) },
      { id: "entitled_access", stage: "entitled_access", run: async (c) => { expect(c.withSupplements).toBeUndefined(); return { status: "ok", verified: true, path: "/tmp/e.pdf", message: "ok" }; } },
    ];
    const result = await downloadBatch({} as never, { items: [{ doi: "10.1000/a" }] }, backendWith(requests), () => {}, tiers);
    expect(result.content).toBe("main");
    expect(requests).toEqual([]);
  });
});
