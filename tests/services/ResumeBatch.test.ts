import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";
import { latestPapers, planResume } from "../../src/capabilities/download/batch/resume.js";
import { DownloadBatchSchema } from "../../src/capabilities/download/schemas.js";
import { useMarkdownPro } from "../../src/capabilities/download/content/markdown/pro.js";
import { fakeMarkdownPro } from "../helpers/fakeMarkdownPro.js";

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
      runId: "20261115-143144-1a4de8", folder: "/out", content: "both", fulltext: false, complete: 3,
      retry: [{ doi: "10.1126/b", paperId: "10.1126/b" }], markdown: [],
      files: [{ doi: "10.1126/c", paperId: "10.1126/c", mainPath: "/out/C.pdf" },
        { doi: "10.1126/d", paperId: "10.1126/d", mainPath: "/out/D.pdf" },
        { doi: "10.1126/g", paperId: "10.1126/g", mainPath: "/out/G/G.pdf" }],
    });
  });

  it("goes on as the batch went: through the school alone when it did (user, 2026-11-17)", () => {
    run("20261117-234728-79e2e6", { savePath: "/out", content: "both", fulltext: true, mode: "entitled_only" }, [
      { index: 1, doi: "10.1016/a", paperId: "10.1016/a", status: "error" },
    ]);
    expect(planResume("latest", env())).toMatchObject({ mode: "entitled_only", retry: [{ doi: "10.1016/a" }] });
    // A later run of the Markdown alone records its content as its mode: the batch's stays.
    run("20261118-010000-aaaaaa", { savePath: "/out", content: "markdown", fulltext: true, mode: "markdown",
      resumeOf: "20261117-234728-79e2e6" }, []);
    expect(planResume("20261117-234728-79e2e6", env())).toMatchObject({ mode: "entitled_only" });
    // A batch from before: none recorded, none given.
    run("20261116-120000-bbbbbb", { savePath: "/old", content: "main" }, [{ index: 1, doi: "10.1/x", paperId: "10.1/x", status: "error" }]);
    expect(planResume("20261116-120000-bbbbbb", env())).not.toHaveProperty("mode");
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
    // A file past the old 200 MB limit is asked for again: none on files written to disk now (2026-11-17).
    expect(planResume("latest", env())).toMatchObject({ complete: 2, retry: [],
      files: [{ doi: "10.1136/c", paperId: "10.1136/c", mainPath: "/out/C.pdf" }, { doi: "10.1136/d", paperId: "10.1136/d", mainPath: "/out/D.pdf" }] });
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

  it("gets the Markdown of saved papers it did not reach, failed, or lost to the login, not of those with no source", () => {
    const md = (status: string, code?: string) => ({ stages: [{ stage: "markdown", status, ...(code ? { code } : {}) }] });
    run("20261115-143144-1a4de8", { savePath: "/out", content: "both", fulltext: true }, [
      { index: 1, doi: "10.1126/a", paperId: "10.1126/a", status: "ok", path: "/out/A/A.pdf", supplements: [saved("a1")], ...md("ok") },
      // Not reached (the batch stopped, or its publisher was paused).
      { index: 2, doi: "10.1126/b", paperId: "10.1126/b", status: "ok", path: "/out/B/B.pdf", supplements: [saved("b1")] },
      { index: 3, doi: "10.1126/c", paperId: "10.1126/c", status: "ok", path: "/out/C.pdf",
        supplements: [{ status: "skipped", label: "", reason: "batch_stopped" }] },
      // No source had it: asked for again it would not be there either.
      { index: 4, doi: "10.1126/d", paperId: "10.1126/d", status: "ok", path: "/out/D/D.pdf", supplements: [saved("d1")],
        ...md("skipped", "pdf_only") },
      { index: 5, doi: "10.1126/e", paperId: "10.1126/e", status: "ok", path: "/out/E/E.pdf", supplements: [saved("e1")],
        ...md("skipped", "school_update_needed") },
      { index: 6, doi: "10.1126/f", paperId: "10.1126/f", status: "error" },
      // Missing figures, not kept: fetched again (user, 2026-11-16).
      { index: 7, doi: "10.1126/g", paperId: "10.1126/g", status: "ok", path: "/out/G/G.pdf", supplements: [saved("g1")],
        ...md("error", "figures_missing") },
    ]);
    expect(planResume("latest", env())).toMatchObject({ content: "both", fulltext: true, complete: 2,
      retry: [{ doi: "10.1126/f" }], files: [{ doi: "10.1126/c", mainPath: "/out/C.pdf" }],
      markdown: [{ doi: "10.1126/b", mainPath: "/out/B/B.pdf" }, { doi: "10.1126/c", mainPath: "/out/C.pdf" },
        { doi: "10.1126/e", mainPath: "/out/E/E.pdf" }, { doi: "10.1126/g", mainPath: "/out/G/G.pdf" }] });
    // Gone on with: B's Markdown came, E's failed again (its PDF stands), C got both.
    run("20261115-170000-2b3c4d", { savePath: "/out", content: "markdown", fulltext: true, resumeOf: "20261115-143144-1a4de8" }, [
      { index: 1, doi: "10.1126/b", paperId: "10.1126/b", status: "ok", path: "/out/B/B.pdf", ...md("ok") },
      { index: 2, doi: "10.1126/e", paperId: "10.1126/e", status: "error", path: "/out/E/E.pdf", ...md("error", "fulltext_failed") },
      { index: 3, doi: "10.1126/g", paperId: "10.1126/g", status: "ok", path: "/out/G/G.pdf", ...md("ok") },
    ]);
    run("20261115-170500-3c4d5e", { savePath: "/out", content: "supplements", fulltext: true, resumeOf: "20261115-143144-1a4de8" }, [
      { index: 1, doi: "10.1126/c", paperId: "10.1126/c", status: "ok", path: "/out/C/C.pdf", supplements: [saved("c1")], ...md("ok") },
    ]);
    expect(planResume("latest", env())).toMatchObject({ complete: 5, retry: [{ doi: "10.1126/f" }], files: [],
      markdown: [{ doi: "10.1126/e", mainPath: "/out/E/E.pdf" }] });
  });

  it("gets the Markdown made without PaperSearch Pro once Pro is there", () => {
    // Installed after the batch (the settings window's 安装, 2026-11-18): 接着下 makes the Markdown left out.
    const md = (code: string) => ({ stages: [{ stage: "markdown", status: "skipped", code }] });
    run("20261118-090000-5e6f70", { savePath: "/out", content: "both", fulltext: true }, [
      { index: 1, doi: "10.1016/a", paperId: "10.1016/a", status: "ok", path: "/out/A/A.pdf", supplements: [], ...md("markdown_pro_required") },
      { index: 2, doi: "10.1016/b", paperId: "10.1016/b", status: "ok", path: "/out/B/B.pdf", supplements: [], ...md("markdown_pro_key_required") },
      { index: 3, doi: "10.1016/c", paperId: "10.1016/c", status: "ok", path: "/out/C/C.pdf", supplements: [], ...md("markdown_pro_offline") },
    ]);
    expect(planResume("latest", env())).toMatchObject({ complete: 0, retry: [],
      markdown: [{ doi: "10.1016/a" }, { doi: "10.1016/b" }, { doi: "10.1016/c" }] });
  });

  it("makes again the Markdown saved with a note of what it may lack, when asked to (2026-11-18)", () => {
    // 94 Cell papers saved before the tables' fix were noted "正文可能不全": 接着下 alone leaves them.
    const md = (extra: Record<string, unknown>) => ({ stages: [{ stage: "markdown", status: "ok", ...extra }] });
    run("20261118-090000-6f7a8b", { savePath: "/out", content: "main", fulltext: true }, [
      { index: 1, doi: "10.1016/a", paperId: "10.1016/a", status: "ok", path: "/out/A/A.pdf", ...md({ possiblyMissing: { text: 15 } }) },
      { index: 2, doi: "10.1016/b", paperId: "10.1016/b", status: "ok", path: "/out/B/B.pdf", ...md({}) },
    ]);
    expect(planResume("latest", env())).toMatchObject({ complete: 2, markdown: [] });
    expect(planResume("latest", env(), { markdownAgain: "possibly_short" })).toMatchObject({ complete: 1,
      markdown: [{ doi: "10.1016/a", mainPath: "/out/A/A.pdf" }] });
  });

  it("gets again the Markdown of a page never tried, and of one tried on a site supported since", () => {
    // 432 ARD papers said "网站暂不支持转换" before sites without rules were tried (2026-11-16): every
    // site is tried now. A page tried and not complete waits for its site's rules.
    const md = (code: string, message: string) => ({ stages: [{ stage: "markdown", status: "skipped", code, message }] });
    run("20261116-090000-4d5e6f", { savePath: "/out", content: "both", fulltext: true }, [
      { index: 1, doi: "10.1016/a", paperId: "10.1016/a", status: "ok", path: "/out/A/A.pdf", supplements: [],
        ...md("page_not_supported", "The page the browser saved (ard.eular.org) has no converter yet.") },
      { index: 2, doi: "10.1000/b", paperId: "10.1000/b", status: "ok", path: "/out/B/B.pdf", supplements: [],
        ...md("page_not_supported", "The page the browser saved (journals.example.org) has no converter yet.") },
      { index: 3, doi: "10.1016/c", paperId: "10.1016/c", status: "ok", path: "/out/C/C.pdf", supplements: [],
        ...md("unverified_incomplete", "www.cell.com is not yet supported, and its page did not convert completely (missing 1 reference); it is not kept.") },
      { index: 4, doi: "10.1000/d", paperId: "10.1000/d", status: "ok", path: "/out/D/D.pdf", supplements: [],
        ...md("unverified_incomplete", "journals.example.org is not yet supported, and its page did not convert completely (missing 1 figure); it is not kept.") },
    ]);
    // Pro has rules for www.cell.com now: its paper is tried again.
    useMarkdownPro(fakeMarkdownPro({ hasRulesForUrl: (url) => url.startsWith("https://www.cell.com/") }));
    try {
      expect(planResume("latest", env())).toMatchObject({ retry: [], files: [], complete: 1,
        markdown: [{ doi: "10.1016/a", mainPath: "/out/A/A.pdf" }, { doi: "10.1000/b", mainPath: "/out/B/B.pdf" },
          { doi: "10.1016/c", mainPath: "/out/C/C.pdf" }] });
    } finally {
      useMarkdownPro(undefined);
    }
  });

  it("downloads too the papers of the batch's list no run recorded: a batch killed outright (Windows, 2026-11-19)", () => {
    // Windows restarted for an update mid-batch: 1475 of 1521 papers recorded, the other 46 nowhere
    // in the ledger; 接着下 retried the one failed paper only.
    const folder = join(root, "EClinicalMedicine_2023-2025");
    const first = "20261119-050316-254f9a";
    mkdirSync(join(folder, "_run", first), { recursive: true });
    writeFileSync(join(folder, "_run", first, "batch-args.json"), JSON.stringify({ savePath: folder, content: "main",
      items: [{ doi: "10.1016/a" }, { doi: "10.1016/B", title: "B" }, { doi: " 10.1016/c " }, { doi: "10.1016/d" },
        { paperId: "pmid:1" }, { doi: "10.1016/d" }, {}, "x"] }));
    run(first, { savePath: folder, content: "main" }, [
      { index: 1, doi: "10.1016/a", paperId: "10.1016/a", status: "ok", path: join(folder, "A.pdf") },
      { index: 2, doi: "10.1016/b", paperId: "10.1016/b", status: "error" },
    ]);
    // A later run that went on with it and was killed too: still read from the batch's own list.
    run("20261119-065641-dc27b1", { savePath: folder, content: "main", resumeOf: first }, [
      { index: 1, doi: "10.1016/b", paperId: "10.1016/b", status: "error" },
    ]);
    expect(planResume("latest", env())).toMatchObject({ runId: first, complete: 1, unreached: 3,
      retry: [{ doi: "10.1016/b", paperId: "10.1016/b" }, { doi: "10.1016/c" }, { doi: "10.1016/d" }, { paperId: "pmid:1" }] });
    // A batch whose run recorded every paper: nothing more.
    run("20261119-080000-aaaaaa", { savePath: join(root, "other"), content: "main" }, [
      { index: 1, doi: "10.1016/z", paperId: "10.1016/z", status: "ok", path: "/out/Z.pdf" },
    ]);
    mkdirSync(join(root, "other", "_run", "20261119-080000-aaaaaa"), { recursive: true });
    writeFileSync(join(root, "other", "_run", "20261119-080000-aaaaaa", "batch-args.json"), JSON.stringify({ items: [{ doi: "10.1016/Z" }] }));
    expect(planResume("latest", env())).not.toHaveProperty("unreached");
    expect(planResume("latest", env())).toMatchObject({ retry: [], complete: 1 });
  });

  it("takes where a PDF saved again came from, and keeps it through a run of its Markdown alone (2026-11-19)", () => {
    // IEEE on the Mac: a preprint saved by one batch, the published PDF by the next into the same
    // folder; the list went on saying 预印本.
    run("20261119-084419-aaaaaa", { savePath: "/out", content: "main" }, [
      { index: 1, doi: "10.1109/a", paperId: "10.1109/a", status: "ok", path: "/out/A.pdf", stages: [{ stage: "preprint", status: "ok" }] },
    ]);
    run("20261119-091759-bbbbbb", { savePath: "/out", content: "main" }, [
      { index: 1, doi: "10.1109/a", paperId: "10.1109/a", status: "ok", path: "/out/A/A.pdf",
        stages: [{ stage: "entitled_access", status: "ok" }] },
    ]);
    run("20261119-100000-cccccc", { savePath: "/out", content: "markdown", resumeOf: "20261119-091759-bbbbbb" }, [
      { index: 1, doi: "10.1109/a", paperId: "10.1109/a", status: "ok", path: "/out/A/A.pdf",
        stages: [{ stage: "markdown", status: "ok", path: "/out/A/markdown/article.md" }] },
    ]);
    const dirs = ["20261119-084419-aaaaaa", "20261119-091759-bbbbbb", "20261119-100000-cccccc"].map((name) => join(root, name));
    expect(latestPapers(dirs.slice(0, 1)).get("10.1109/a")).toMatchObject({ source: "preprint" });
    expect(latestPapers(dirs).get("10.1109/a")).toMatchObject({ source: "entitled_access", byVisit: true, path: "/out/A/A.pdf",
      markdownFile: "/out/A/markdown/article.md" });
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
    // No cap on the papers of one batch (user, 2026-11-17: a journal's years in one folder).
    const many = Array.from({ length: 2500 }, (_, at) => ({ doi: `10.1000/${at}` }));
    expect(DownloadBatchSchema.parse({ items: many }).items).toHaveLength(2500);
    expect(DownloadBatchSchema.parse({ items: [{ doi: "10.1126/a" }] }).items).toHaveLength(1);
  });
});
