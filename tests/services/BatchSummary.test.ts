import { tmpdir } from "node:os";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "@jest/globals";
import { asWindowBatch, batchPaper, batchResults } from "../../src/capabilities/download/batch/batchSummary.js";
import type { DownloadBatchItemResult, DownloadBatchResult } from "../../src/capabilities/download/batch/batch.js";
import type { SchoolBackend, SchoolBatchUpdate } from "../../src/infrastructure/school/types.js";
import type { DownloadBatchPosition } from "../../src/capabilities/download/types.js";
import { useMarkdownPro } from "../../src/capabilities/download/content/markdown/pro.js";
import { fakeMarkdownPro } from "../helpers/fakeMarkdownPro.js";

function fakeBackend(updates: SchoolBatchUpdate[]): SchoolBackend {
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
    const updates: SchoolBatchUpdate[] = [];
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
        failures: [{ cls: "user_side", reason: "等学校登录超时", title: "A Paper", journal: "Spine", doi: "10.1000/x" }],
      }),
    })]);
  });

  it("points a saved paper's folder button at its own folder", async () => {
    const updates: SchoolBatchUpdate[] = [];
    const savePath = root();
    const paperDir = join(savePath, "Spine_2026_A Paper_abc");
    await asWindowBatch({ source: "crossref", paperId: "10.1000/x", doi: "10.1000/x", savePath }, fakeBackend(updates),
      async () => ({ status: "ok", path: join(paperDir, "A Paper.pdf"),
        attempts: [{ stage: "entitled_access", status: "ok", message: "" }] }));
    expect(updates.at(-1)?.results).toEqual(expect.objectContaining({ folder: paperDir, main: 1, sources: [["机构下载", 1]] }));
  });

  it("opens no window for a copy that never reached the backend", async () => {
    const updates: SchoolBatchUpdate[] = [];
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
      { cls: "publisher_or_network", reason: "网站人机验证拦截", title: "Paper 1", journal: "APL", doi: "10.1000/1" },
      { cls: "unsupported", reason: "网站暂不支持自动下载附录", title: "Paper 2", journal: "APL", doi: "10.1000/2" },
    ]);
    expect(summary.failures).toEqual([expect.objectContaining({ reason: "等学校登录超时", title: "Paper 5" })]);
    expect(summary.supplements).toBe(2);
  });

  it("counts the papers whose Markdown was saved, when the Markdown was asked for beside them", () => {
    const withMarkdown = batchResults(batch([
      item(1, { markdown: { status: "ok", source: "pmc", message: "" } }),
      item(2, { markdown: { status: "unavailable", code: "pdf_only", message: "" } }),
    ], "both"), 0, "/out");
    expect(withMarkdown.markdown).toBe(1);
    // The one without it is listed, with why (user, 2026-11-15).
    expect(withMarkdown.markdown_failures).toEqual([
      { cls: "unsupported", reason: "没有可转换的全文", title: "Paper 2", journal: "APL", doi: "10.1000/2" },
    ]);
    const why = batchResults(batch([
      item(1, { markdown: { status: "unavailable", code: "page_not_supported", message: "" } }),
      item(2, { markdown: { status: "abstract_only", code: "abstract_only", message: "" } }),
      item(3, { markdown: { status: "unavailable", code: "school_update_needed", message: "" } }),
      item(4, { markdown: { status: "error", code: "fulltext_failed", message: "" } }),
      // Missing figures, to the institutional download: its reason, named as a PDF's (user, 2026-11-16).
      item(5, { markdown: { status: "incomplete", code: "access_blocked", message: "" } }),
      item(6, { markdown: { status: "incomplete", code: "figures_missing", message: "" } }),
      item(7, { markdown: { status: "incomplete", code: "institutional_not_run", message: "" } }),
      item(8, { markdown: { status: "unavailable", code: "page_not_entitled", message: "" } }),
      item(9, { markdown: { status: "unavailable", code: "login_timeout", message: "" } }),
      item(10, { markdown: { status: "error", code: "pmc_failed", message: "" } }),
      // A table neither fetched nor as an image (BMJ's "View inline"): not kept either.
      item(11, { markdown: { status: "incomplete", code: "tables_missing", message: "" } }),
      // The PDF came through the school, the page had no full text: not 学校没有订阅 (Windows, 2026-11-17).
      item(12, { markdown: { status: "unavailable", code: "page_no_fulltext", message: "" } }),
    ], "both"), 0, "/out").markdown_failures?.map((entry) => [entry.cls, entry.reason]);
    expect(why).toEqual([["unsupported", "网站暂不支持转换"], ["unsupported", "网页只有摘要"],
      ["user_side", "学校订阅下载扩展需要更新"], ["unexplained", "转换出错"],
      ["publisher_or_network", "网站拦截了当前网络"], ["publisher_or_network", "图片没下载成功"], ["user_side", "没有进行机构下载"],
      ["no_access", "学校没有订阅"], ["user_side", "等学校登录超时"], ["publisher_or_network", "PubMed Central 没响应"],
      ["publisher_or_network", "表格没取到"], ["unsupported", "文章页没有正文"]]);
    // The Markdown alone: a paper without it is a failure, by the same reasons (no PDF in its place).
    const alone = batchResults(batch([
      item(1, { markdown: { status: "ok", source: "publisher_page", message: "" } }),
      { ...item(2, { markdown: { status: "incomplete", code: "access_blocked", message: "" } }), status: "error" },
    ], "markdown"), 0, "/out");
    expect([alone.main, alone.failures.map((entry) => [entry.cls, entry.reason])]).toEqual([1, [["publisher_or_network", "网站拦截了当前网络"]]]);
    // Not asked for: no count at all (the window shows none).
    expect(batchResults(batch([item(1, {})], "main"), 0, "/out")).not.toHaveProperty("markdown");
    expect(batchResults(batch([item(1, {})], "main"), 0, "/out")).not.toHaveProperty("markdown_failures");
  });

  it("counts a page that listed no files, and the papers the stop left undone apart from the failed", () => {
    // Windows, 2026-11-16: the visit for the PDF found none (an empty list); a stopped batch said 失败 69.
    const stop = { stage: "entitled_access", status: "skipped", message: "", code: "batch_stopped" } as const;
    const summary = batchResults(batch([
      item(1, { supplements: [] }),
      item(2, { status: "error", path: undefined, attempts: [stop] }),
      item(3, { status: "error", path: undefined, attempts: [stop] }),
    ]), 0, "/out");
    expect(summary).toMatchObject({ no_supplements: 1, stopped: true, stopped_count: 2, failures: [] });
  });

  it("lists a batch of the files alone by what each got, at its PDF saved before", () => {
    const request = { doi: "10.1000/1" } as Parameters<typeof batchPaper>[0];
    const none = item(1, { path: undefined, supplements: [] });
    expect(batchPaper(request, none, undefined, "supplements", "/out/1.pdf"))
      .toMatchObject({ state: "ok", path: "/out/1.pdf", supplements_saved: 0 });
    expect(batchPaper(request, none, undefined, "supplements", "relative.pdf")).not.toHaveProperty("path");
    expect(batchPaper(request, item(1, { path: undefined, supplements: [{ label: "S1", status: "saved", file: "/out/1/S1.pdf" }] }),
      undefined, "supplements", "/out/1.pdf")).toMatchObject({ path: "/out/1/S1.pdf", supplements_saved: 1 });
    expect(batchPaper(request, item(1, { supplements: [] }), undefined, "both")).not.toHaveProperty("supplements_saved");
    const stopped = item(2, { status: "error", path: undefined, attempts: [{ stage: "entitled_access", status: "skipped", message: "", code: "batch_stopped" }] });
    expect(batchPaper(request, stopped, undefined, "supplements")).toMatchObject({ state: "stopped" });
  });

  it("lists none when only the main text was asked for", () => {
    const summary = batchResults(batch([item(1, { supplements: [{ label: "x", status: "failed", reason: "html_page" }] })], "main"), 0, "/out");
    expect(summary.supplement_failures).toEqual([]);
  });

  it("says where a site not yet supported fell short, in the list and for the window, with its kept report", () => {
    // ard.eular.org before it was supported (user, 2026-11-16): the page converted, short of a reference.
    const unverified = { host: "journals.example.org", template: "highwire", shortfall: { references: 1, figures: 2, text: 15 },
      report: "/runs/r1/records/10.1000_1_markdown-report.json" };
    const short = item(1, { markdown: { status: "incomplete", code: "unverified_incomplete", message: "", unverified } });
    const kept = item(2, { markdown: { status: "ok", source: "publisher_page", message: "", unverified: { host: "journals.example.org", template: "highwire" } } });
    const lost = item(3, { markdown: { status: "incomplete", code: "unverified_incomplete", message: "",
      unverified: { host: "other.example.org" } } });
    expect(batchResults(batch([short, kept, lost], "both"), 0, "/out").markdown_failures).toEqual([
      { cls: "unsupported", reason: "内容不完整", title: "Paper 1", doi: "10.1000/1", unverified: true,
        note: "journals.example.org · 不完整：参考文献少 1 条，少 2 张图，正文缺约 15%" },
      { cls: "unsupported", reason: "内容不完整", title: "Paper 3", doi: "10.1000/3", unverified: true,
        note: "other.example.org · 不完整：核对没通过" },
    ]);
    const request = { doi: "10.1000/1" } as Parameters<typeof batchPaper>[0];
    expect(batchPaper(request, short, undefined, "both")).toMatchObject({ state: "ok", markdown_cls: "unsupported", markdown_reason: "内容不完整",
      markdown_host: "journals.example.org", markdown_saved: false, markdown_report: unverified.report,
      markdown_note: "journals.example.org · 不完整：参考文献少 1 条，少 2 张图，正文缺约 15%" });
    // Whose rules converted it: the window says which were borrowed (user, 2026-11-17); the rules' names are Pro's.
    const names: Record<string, string> = { "atypon-current": "Atypon", highwire: "HighWire" };
    useMarkdownPro(fakeMarkdownPro({ rulesName: (template) => (template ? names[template] : undefined) }));
    const byPlatform = item(9, { markdown: { status: "ok", source: "publisher_page", message: "",
      unverified: { host: "www.journal.example.org", template: "atypon-current", matchedBy: "platform", basis: "Atypon" } } });
    expect(batchPaper(request, byPlatform, undefined, "both")).toMatchObject({ markdown_host: "www.journal.example.org", markdown_rules: "Atypon" });
    expect(batchPaper(request, kept, undefined, "both")).toMatchObject({ markdown_rules: "HighWire" });
    // No rules read the page: none named.
    expect(batchPaper(request, lost, undefined, "both")).not.toHaveProperty("markdown_rules");
    useMarkdownPro(undefined);
    // Saved: counted for the site's tally, nothing missing.
    const saved = batchPaper(request, kept, undefined, "both");
    expect(saved).toMatchObject({ state: "ok", markdown_host: "journals.example.org", markdown_saved: true });
    expect(saved).not.toHaveProperty("markdown_reason");
    // The Markdown alone: the paper failed, with the same site fields.
    expect(batchPaper(request, { ...short, status: "error", path: undefined }, undefined, "markdown"))
      .toMatchObject({ state: "failed", reason: "内容不完整", markdown_host: "journals.example.org", markdown_saved: false });
    // A page none of the rules read, and one not tried after the site was given up.
    const unread = item(4, { markdown: { status: "unavailable", code: "page_not_supported", message: "", unverified: { host: "c.example.org" } } });
    const skipped = item(5, { markdown: { status: "unavailable", code: "page_not_supported", message: "", unverified: { host: "c.example.org", skipped: true } } });
    expect(batchResults(batch([unread, skipped], "both"), 0, "/out").markdown_failures?.map((entry) => [entry.reason, entry.note])).toEqual([
      ["网站暂不支持转换", "c.example.org · 没有规则能读出正文"], ["网站暂不支持转换", "c.example.org · 本批前 3 篇都没转换完整，未再尝试"]]);
    expect(batchPaper(request, skipped, undefined, "both")).toMatchObject({ markdown_host: "c.example.org", markdown_saved: false, markdown_skipped: true });
    expect(batchPaper(request, unread, undefined, "both")).not.toHaveProperty("markdown_skipped");
    // The Markdown alone: the failed paper carries the same note.
    expect(batchResults(batch([{ ...short, status: "error", path: undefined }], "markdown"), 0, "/out").failures).toEqual([
      { cls: "unsupported", reason: "内容不完整", title: "Paper 1", doi: "10.1000/1", unverified: true,
        note: "journals.example.org · 不完整：参考文献少 1 条，少 2 张图，正文缺约 15%" }]);
    // A report path not absolute is not handed to the window.
    expect(batchPaper(request, item(1, { markdown: { ...short.markdown!, unverified: { ...unverified, report: "r.json" } } }), undefined, "both"))
      .not.toHaveProperty("markdown_report");
  });

  it("tells the way a PDF came by its own step, not by the Markdown's or the files' after it", () => {
    // JAMA Netw Open, pdf,markdown (Windows, 2026-11-19): 329 of 330 listed as 开放下载 · 开放获取,
    // 288 of them through the school, their Markdown from PubMed Central.
    const markdown = { stage: "markdown", status: "ok", message: "" } as const;
    const files = { stage: "supplements", status: "ok", message: "" } as const;
    const pmc = { status: "ok", source: "pmc", message: "" } as const;
    const request = { doi: "10.1000/1" } as Parameters<typeof batchPaper>[0];
    const paper = (attempts: DownloadBatchItemResult["attempts"], extra: Partial<DownloadBatchItemResult> = {}) =>
      batchPaper(request, item(1, { attempts, markdown: pmc, ...extra }), undefined, "main");
    expect(paper([ok, markdown])).toMatchObject({ via: "机构下载" });
    expect(paper([ok, markdown])).not.toHaveProperty("detail");
    expect(paper([ok, files, markdown])).toMatchObject({ via: "机构下载" });
    // Open access shows no detail (the window says 开放获取); an API does.
    expect(paper([{ stage: "unpaywall", status: "ok", message: "" }, markdown])).toMatchObject({ via: "开放下载" });
    expect(paper([{ stage: "publisher_api", status: "ok", message: "" }, markdown])).toMatchObject({ via: "开放下载", detail: "出版社 API" });
    expect(paper([{ stage: "unpaywall", status: "error", message: "" }, ok, markdown])).toMatchObject({ via: "机构下载" });
    // The Markdown alone: by its source.
    expect(paper([markdown])).toMatchObject({ via: "开放下载" });
    expect(paper([markdown], { markdown: { status: "ok", source: "publisher_page", message: "" } })).toMatchObject({ via: "机构下载" });
    // The card's counts the same way.
    expect(batchResults(batch([item(1, { attempts: [ok, markdown], markdown: pmc }),
      item(2, { attempts: [{ stage: "repositories", status: "ok", message: "" }, markdown], markdown: pmc })], "main"), 0, "/out").sources)
      .toEqual([["机构下载", 1], ["开放下载", 1]]);
  });

  it("tells the window's 失败 list while the batch runs, in the finished card's words", () => {
    const missing = item(1, { supplements: [{ label: "SM.pdf", status: "failed", reason: "verification_page" }] });
    const request = { doi: "10.1000/1" } as Parameters<typeof batchPaper>[0];
    expect(batchPaper(request, missing, undefined, "both")).toMatchObject({
      state: "ok", path: "/out/1.pdf", supplement_cls: "publisher_or_network", supplement_reason: "网站人机验证拦截" });
    expect(batchPaper(request, missing, undefined, "main")).not.toHaveProperty("supplement_reason");
    expect(batchPaper(request, item(1, { supplements: [{ label: "S1.pdf", status: "saved" }] }), undefined, "both"))
      .not.toHaveProperty("supplement_reason");
  });
});
