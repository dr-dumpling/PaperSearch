import { tmpdir } from "node:os";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "@jest/globals";
import { asWindowBatch, batchPaper, batchResults } from "../../src/capabilities/pdf-discovery/batchSummary.js";
import type { DownloadBatchItemResult, DownloadBatchResult } from "../../src/capabilities/pdf-discovery/batch.js";
import type { CarsiBackend, CarsiBatchUpdate } from "../../src/capabilities/pdf-discovery/carsi/types.js";
import type { DownloadBatchPosition } from "../../src/capabilities/pdf-discovery/types.js";

function fakeBackend(updates: CarsiBatchUpdate[]): CarsiBackend {
  return {
    probe: async () => ({ state: "available", code: "ready", message: "", missing: [] }),
    downloadLegalDoi: async () => {
      throw new Error("downloads are faked");
    },
    reportBatchProgress: async (update) => {
      updates.push(update);
      return true;
    },
  };
}

describe("a lone download as a batch of one", () => {
  const roots: string[] = [];
  const root = () => {
    const dir = mkdtempSync(join(tmpdir(), "lone-download-"));
    roots.push(dir);
    return dir;
  };
  afterEach(() => roots.splice(0).forEach((dir) => rmSync(dir, { recursive: true, force: true })));

  it("ends the window with its reason once it reached the backend", async () => {
    const updates: CarsiBatchUpdate[] = [];
    const seen: Array<DownloadBatchPosition | undefined> = [];
    const savePath = root();
    await asWindowBatch({ source: "crossref", paperId: "10.1000/x", doi: "10.1000/x", savePath }, fakeBackend(updates),
      async (options) => {
        seen.push(options.batch);
        return { status: "error", title: "A Paper", journal: "Spine",
          attempts: [{ stage: "entitled_access", status: "error", code: "login_timeout", message: "" }] };
      });
    expect(seen).toEqual([{ id: expect.any(String), index: 1, total: 1, done: 0, succeeded: 0, failed: 0 }]);
    expect(updates).toEqual([expect.objectContaining({
      id: seen[0]!.id, total: 1, done: 1, succeeded: 0, failed: 1, finished: true,
      results: expect.objectContaining({
        folder: savePath,
        failures: [{ cls: "user_or_external", reason: "等学校登录超时", title: "A Paper", journal: "Spine", doi: "10.1000/x" }],
      }),
    })]);
  });

  it("points a saved paper's folder button at its own folder", async () => {
    const updates: CarsiBatchUpdate[] = [];
    const savePath = root();
    const paperDir = join(savePath, "Spine_2026_A Paper_abc");
    await asWindowBatch({ source: "crossref", paperId: "10.1000/x", doi: "10.1000/x", savePath }, fakeBackend(updates),
      async () => ({ status: "ok", path: join(paperDir, "A Paper.pdf"),
        attempts: [{ stage: "entitled_access", status: "ok", message: "" }] }));
    expect(updates.at(-1)?.results).toEqual(expect.objectContaining({ folder: paperDir, main: 1, sources: [["机构下载", 1]] }));
  });

  it("opens no window for a copy that never reached the backend", async () => {
    const updates: CarsiBatchUpdate[] = [];
    await asWindowBatch({ source: "crossref", paperId: "10.1000/x", doi: "10.1000/x", savePath: root() }, fakeBackend(updates),
      async () => ({ status: "ok", path: "/tmp/x.pdf", attempts: [
        { stage: "unpaywall", status: "ok", message: "" },
        { stage: "entitled_access", status: "skipped", message: "" },
      ] }));
    expect(updates).toEqual([]);
  });
});

describe("main text and supplementary files apart", () => {
  const ok = { stage: "entitled_access", status: "ok", message: "" } as const;
  const item = (index: number, extra: Partial<DownloadBatchItemResult>): DownloadBatchItemResult => ({
    index, paperId: `10.1000/${index}`, doi: `10.1000/${index}`, title: `Paper ${index}`, journal: "APL",
    status: "ok", path: `/out/${index}.pdf`, attempts: [ok], ...extra,
  });
  const batch = (items: DownloadBatchItemResult[], content: DownloadBatchResult["content"] = "both"): DownloadBatchResult => ({
    status: "partial", mode: "entitled_only", content, batchId: "b", total: items.length,
    succeeded: items.filter((i) => i.status === "ok").length, failed: items.filter((i) => i.status !== "ok").length, items,
  });

  it("lists the papers whose main text was saved but not every file, by the first real reason", () => {
    const summary = batchResults(batch([
      // A firewall's verification page answered for one file: listed, not the site without a rule.
      item(1, { supplements: [
        { label: "", status: "skipped", reason: "supplements_not_supported" },
        { label: "SM.pdf", status: "failed", reason: "verification_page" },
        { label: "SM2.pdf", status: "saved" }] }),
      item(2, { supplements: [{ label: "", status: "skipped", reason: "supplements_not_supported" }] }),
      item(3, { supplements: [{ label: "S1.pdf", status: "saved" }] }),
      item(4, { supplements: [{ label: "", status: "skipped", reason: "batch_stopped" }] }),
      // No main text: told by its main text's reason only.
      item(5, { status: "error", path: undefined, supplements: [{ label: "x", status: "failed", reason: "html_page" }],
        attempts: [{ stage: "entitled_access", status: "error", code: "login_timeout", message: "" }] }),
    ]), 0, "/out");
    expect(summary.supplement_failures).toEqual([
      { cls: "user_or_external", reason: "网站人机验证拦截", title: "Paper 1", journal: "APL", doi: "10.1000/1" },
      { cls: "unsupported", reason: "网站暂不支持附录", title: "Paper 2", journal: "APL", doi: "10.1000/2" },
    ]);
    expect(summary.failures).toEqual([expect.objectContaining({ reason: "等学校登录超时", title: "Paper 5" })]);
    expect(summary.supplements).toBe(2);
  });

  it("lists none when only the main text was asked for", () => {
    const summary = batchResults(batch([item(1, { supplements: [{ label: "x", status: "failed", reason: "html_page" }] })], "main"), 0, "/out");
    expect(summary.supplement_failures).toEqual([]);
  });

  it("tells the window's 失败 list while the batch runs, in the finished card's words", () => {
    const missing = item(1, { supplements: [{ label: "SM.pdf", status: "failed", reason: "verification_page" }] });
    const request = { doi: "10.1000/1" } as Parameters<typeof batchPaper>[0];
    expect(batchPaper(request, missing, undefined, "both")).toMatchObject({
      state: "ok", path: "/out/1.pdf", supplement_cls: "user_or_external", supplement_reason: "网站人机验证拦截" });
    expect(batchPaper(request, missing, undefined, "main")).not.toHaveProperty("supplement_reason");
    expect(batchPaper(request, item(1, { supplements: [{ label: "S1.pdf", status: "saved" }] }), undefined, "both"))
      .not.toHaveProperty("supplement_reason");
  });
});
