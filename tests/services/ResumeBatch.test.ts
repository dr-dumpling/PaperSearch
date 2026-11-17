import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";
import { planResume } from "../../src/capabilities/pdf-discovery/resume.js";
import { DownloadBatchSchema } from "../../src/capabilities/pdf-discovery/schemas.js";

// 接着下 (user, 2026-11-15): what an earlier batch left undone, from its run ledger.
describe("going on with a batch", () => {
  let root: string;
  const env = () => ({ PAPER_SEARCH_RUNLOG_DIR: root });
  const run = (name: string, info: Record<string, unknown>, items: Array<Record<string, unknown>>) => {
    mkdirSync(join(root, name), { recursive: true });
    writeFileSync(join(root, name, "run.json"), JSON.stringify({ schema: 1, runId: name, kind: "download_batch", ...info }));
    writeFileSync(join(root, name, "items.jsonl"), items.map((item) => JSON.stringify(item)).join("\n") + "\n");
  };
  const saved = (file: string) => ({ status: "saved", label: file, file: `/out/${file}` });
  beforeEach(() => { root = mkdtempSync(join(tmpdir(), "papersearch-resume-")); });
  afterEach(() => rmSync(root, { recursive: true, force: true }));

  it("downloads again the papers not saved, and gets only the files of those saved without them", () => {
    run("20261115-143144-1a4de8", { savePath: "/out", content: "both" }, [
      { index: 1, doi: "10.1126/a", paperId: "10.1126/a", title: "A", status: "ok", path: "/out/A/A.pdf", supplements: [saved("a1")] },
      { index: 2, doi: "10.1126/b", paperId: "10.1126/b", status: "error" },
      { index: 3, doi: "10.1126/c", paperId: "10.1126/c", status: "ok", path: "/out/C.pdf",
        supplements: [{ status: "skipped", label: "", reason: "batch_stopped" }] },
      { index: 4, doi: "10.1126/d", paperId: "10.1126/d", status: "ok", path: "/out/D.pdf" },
      // A site without a rule for its files, or a page listing none: nothing to go on with.
      { index: 5, doi: "10.1126/e", paperId: "10.1126/e", status: "ok", path: "/out/E.pdf",
        supplements: [{ status: "skipped", label: "", reason: "supplements_not_supported" }] },
      { index: 6, doi: "10.1126/f", paperId: "10.1126/f", status: "ok", path: "/out/F.pdf", supplements: [] },
      { index: 7, doi: "10.1126/g", paperId: "10.1126/g", status: "ok", path: "/out/G/G.pdf",
        supplements: [saved("g1"), { status: "failed", label: "S2", reason: "http_404" }] },
    ]);
    expect(planResume("latest", env())).toEqual({
      runId: "20261115-143144-1a4de8", folder: "/out", content: "both", complete: 3,
      retry: [{ doi: "10.1126/b", paperId: "10.1126/b" }],
      files: [{ doi: "10.1126/c", paperId: "10.1126/c", mainPath: "/out/C.pdf" },
        { doi: "10.1126/d", paperId: "10.1126/d", mainPath: "/out/D.pdf" },
        { doi: "10.1126/g", paperId: "10.1126/g", mainPath: "/out/G/G.pdf" }],
    });
  });

  it("leaves the files the institutional visit checked, and what a stopped run never tried", () => {
    // Windows, 2026-11-16: 76 papers with no record of their files after the visit that saved their
    // PDF were all asked for again; then a run stopped mid-way wrote "stopped" over the others.
    const visit = [{ stage: "entitled_access", status: "ok" }];
    run("20261116-131248-0c9e79", { savePath: "/out", content: "both" }, [
      { index: 1, doi: "10.1136/a", paperId: "10.1136/a", status: "ok", path: "/out/A.pdf", stages: visit },
      { index: 2, doi: "10.1136/b", paperId: "10.1136/b", status: "ok", path: "/out/B.pdf", stages: [{ stage: "unpaywall", status: "ok" }] },
      { index: 3, doi: "10.1136/c", paperId: "10.1136/c", status: "ok", path: "/out/C.pdf", stages: visit,
        supplements: [{ status: "failed", label: "S1", reason: "verification_page" }] },
      { index: 4, doi: "10.1136/d", paperId: "10.1136/d", status: "ok", path: "/out/D.pdf", stages: visit,
        supplements: [{ status: "skipped", label: "S1", reason: "too_large" }] },
    ]);
    run("20261116-203028-64e75e", { savePath: "/out", content: "supplements", resumeOf: "20261116-131248-0c9e79" }, [
      { index: 1, doi: "10.1136/b", paperId: "10.1136/b", status: "ok", supplements: [] },
      { index: 2, doi: "10.1136/c", paperId: "10.1136/c", status: "error",
        supplements: [{ status: "skipped", label: "", reason: "batch_stopped" }] },
    ]);
    expect(planResume("latest", env())).toMatchObject({ complete: 3, retry: [],
      files: [{ doi: "10.1136/c", paperId: "10.1136/c", mainPath: "/out/C.pdf" }] });
  });

  it("reads the batch with the runs that went on with it, the latest record of each paper counting", () => {
    run("20261115-143144-1a4de8", { savePath: "/out", content: "main" }, [
      { index: 1, doi: "10.1126/a", paperId: "10.1126/a", status: "error" },
      { index: 2, doi: "10.1126/b", paperId: "10.1126/b", status: "error" },
    ]);
    run("20261115-170000-2b3c4d", { savePath: "/out", content: "main", resumeOf: "20261115-143144-1a4de8" }, [
      { index: 1, doi: "10.1126/a", paperId: "10.1126/a", status: "ok", path: "/out/A.pdf" },
      { index: 2, doi: "10.1126/b", paperId: "10.1126/b", status: "error" },
    ]);
    // Another batch in between is not part of it.
    run("20261115-160000-9f9f9f", { savePath: "/elsewhere", content: "main" }, [
      { index: 1, doi: "10.1000/z", paperId: "10.1000/z", status: "error" },
    ]);
    const plan = planResume("latest", env());
    expect(plan).toMatchObject({ runId: "20261115-143144-1a4de8", folder: "/out", complete: 1,
      retry: [{ doi: "10.1126/b", paperId: "10.1126/b" }], files: [] });
    expect(planResume("20261115-160000-9f9f9f", env())).toMatchObject({ folder: "/elsewhere", retry: [{ doi: "10.1000/z" }] });
  });

  it("takes an older batch's content from its papers, and says why there is nothing to go on with", () => {
    run("20261115-093557-b50aaa", { savePath: "/out" }, [
      { index: 1, doi: "10.1126/a", paperId: "10.1126/a", status: "ok", path: "/out/A.pdf", supplements: [] },
    ]);
    expect(planResume("latest", env())).toMatchObject({ content: "both", complete: 1, retry: [], files: [] });
    expect(planResume("20991231-000000-000000", env())).toBe("没有找到运行记录 20991231-000000-000000。");
    expect(planResume("latest", { PAPER_SEARCH_RUNLOG: "0" })).toContain("运行记录已关闭");
    rmSync(root, { recursive: true, force: true });
    expect(planResume("latest", env())).toBe("没有找到批量下载的运行记录。");
  });

  it("asks for items or resume", () => {
    expect(DownloadBatchSchema.parse({ resume: "latest" })).toMatchObject({ resume: "latest", items: [] });
    expect(() => DownloadBatchSchema.parse({})).toThrow("items (at least one) or resume is required");
    expect(DownloadBatchSchema.parse({ items: [{ doi: "10.1126/a" }] }).items).toHaveLength(1);
  });
});
