import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "@jest/globals";
import { handleDownloadBatch } from "../../src/capabilities/download/handler.js";
import { loadMarkdownPro } from "../../src/capabilities/download/content/markdown/pro.js";
import { DownloadBatchSchema, DownloadPaperSchema, DownloadWithFallbackSchema } from "../../src/capabilities/download/schemas.js";

// The public edition before 1.0.0 (user, 2026-11-19): PaperSearch Pro's features off (src/config/edition.ts).
process.env.PAPER_SEARCH_PRO_FEATURES = "0";

const root = mkdtempSync(join(tmpdir(), "papersearch-pro-off-"));
afterAll(() => rmSync(root, { recursive: true, force: true }));

describe("without PaperSearch Pro's features", () => {
  it("takes pdf and supplements, and refuses markdown however it is asked for", () => {
    const fallback = { source: "crossref", paperId: "10.1000/x" };
    expect(DownloadWithFallbackSchema.parse({ ...fallback, content: "pdf,supplements" })).toMatchObject({ content: "both", fulltext: false });
    const kind = DownloadWithFallbackSchema.safeParse({ ...fallback, content: "supplements,markdown" });
    expect(kind.success).toBe(false);
    expect(JSON.stringify(kind.error?.issues)).toContain('content: pdf, supplements or several of them such as \\"pdf,supplements\\"');
    const flag = DownloadBatchSchema.safeParse({ items: [{ doi: "10.1000/x" }], markdown: true });
    expect(JSON.stringify(flag.success ? "" : flag.error.issues)).toContain("markdown: not offered by this version");
    const single = DownloadPaperSchema.safeParse({ paperId: "10.1000/x", platform: "crossref", content: "markdown" });
    expect(JSON.stringify(single.success ? "" : single.error.issues)).toContain("content: pdf");
  });

  it("does not load PaperSearch Pro even when it is installed", async () => {
    const entry = join(root, "pro", "index.js");
    mkdirSync(join(root, "pro"), { recursive: true });
    writeFileSync(entry, "throw new Error('Pro was loaded');\n");
    process.env.PAPER_SEARCH_PRO_PATH = entry;
    await expect(loadMarkdownPro()).resolves.toBeUndefined();
  });

  it("接着下 leaves out an earlier batch's Markdown: papers missing only it are complete", async () => {
    // A batch from a version with the Markdown: both PDFs saved, the Markdown of one not made.
    const runs = join(root, "runs");
    const run = "20261119-090000-a1b2c3";
    mkdirSync(join(runs, run), { recursive: true });
    writeFileSync(join(runs, run, "run.json"), JSON.stringify({ schema: 1, runId: run, kind: "download_batch",
      savePath: join(root, "batch"), content: "main", fulltext: true }));
    const md = (status: string, code?: string) => ({ stages: [{ stage: "markdown", status, ...(code ? { code } : {}) }] });
    writeFileSync(join(runs, run, "items.jsonl"), [
      { index: 1, doi: "10.1016/a", paperId: "10.1016/a", status: "ok", path: join(root, "batch", "A.pdf"), ...md("ok") },
      { index: 2, doi: "10.1016/b", paperId: "10.1016/b", status: "ok", path: join(root, "batch", "B.pdf"), ...md("skipped", "markdown_pro_required") },
    ].map((item) => JSON.stringify(item)).join("\n") + "\n");
    process.env.PAPER_SEARCH_RUNLOG_DIR = runs;
    const response = await handleDownloadBatch(DownloadBatchSchema.parse({ resume: "latest" }), {} as never);
    const text = response.content[0].text;
    expect(text).toContain("every paper of it is complete");
    expect(JSON.parse(text.slice(text.indexOf("{")))).toMatchObject({ resume: { content: "pdf", complete: 2, retried: 0, markdownOnly: 0 } });
  });
});
