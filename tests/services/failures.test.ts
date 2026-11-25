import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "@jest/globals";
import { renderFailuresText, summarizeFailures } from "../../src/management/failures/index.js";

function run(root: string, id: string, items: unknown[]): void {
  mkdirSync(join(root, id), { recursive: true });
  writeFileSync(join(root, id, "items.jsonl"), items.map((item) => JSON.stringify(item)).join("\n") + "\n");
}

const entitled = (code: string, publisher: string, url: string, extra: Record<string, unknown> = {}) => ({
  stage: "entitled_access", status: "error", code, trace: { publisher },
  backend: { diagnostic: { file: `/runs/${code}/diagnostic.json`, final_url: url, ...extra } },
});

describe("paper-search failures", () => {
  const root = mkdtempSync(join(tmpdir(), "failures-"));
  run(root, "20261031-090000-aaaaaa", [
    { doi: "10.1016/old", status: "error", stages: [entitled("entitlement_missing", "Elsevier", "https://www.sciencedirect.com/science/article/pii/X",
      { access_evidence: ["Hong Mu-lan University does not subscribe to this content"] })] },
  ]);
  run(root, "20261101-133400-bbbbbb", [
    { doi: "10.1080/ok", status: "ok", stages: [{ stage: "entitled_access", status: "ok" }] },
    { doi: "10.1080/0142159x.2026.2752868", status: "error", stages: [entitled("download_failed", "Taylor & Francis",
      "https://www.tandfonline.com/doi/pdf/10.1080/0142159x.2026.2752868", { events: [{ state: "pdf_entry_gated" }, { state: "pdf_candidate" }] })] },
    { doi: "10.1177/x", status: "error", stages: [{ ...entitled("institution_federation_unavailable", "SAGE", "https://login.openathens.net/auth"),
      failureClass: "no_access", evidence: "机构列表里找不到 Hong Mu-lan（login.openathens.net）" }] },
    { doi: "10.1/skipped", status: "error", stages: [{ stage: "entitled_access", status: "skipped" }] },
  ]);
  // A line cut off by an interrupted run is skipped.
  writeFileSync(join(root, "20261101-133400-bbbbbb", "items.jsonl"), '{"doi": "10.1/cut", "sta', { flag: "a" });

  it("reads the latest run by default, or the runs asked for", () => {
    expect(summarizeFailures(root).runs).toEqual(["20261101-133400-bbbbbb"]);
    expect(summarizeFailures(root, { since: "2026-10-31" }).runs).toHaveLength(2);
    expect(summarizeFailures(root, { runs: 5 }).runs).toHaveLength(2);
    expect(summarizeFailures(root, { run: "20261031-090000-aaaaaa" }).runs).toEqual(["20261031-090000-aaaaaa"]);
    expect(summarizeFailures(join(root, "missing")).runs).toEqual([]);
  });

  it("counts failures by class and groups them by publisher, site and code", () => {
    const summary = summarizeFailures(root, { since: "2026-10-31" });
    expect(summary.failed).toBe(3);
    expect(summary.notAttempted).toBe(1);
    expect(summary.classes).toEqual({ no_access: 2, user_side: 0, external: 0, unsupported: 0, unexplained: 1 });
    expect(summary.groups.map((g) => [g.failureClass, g.publisher, g.site, g.code, g.count])).toEqual([
      ["no_access", "Elsevier", "www.sciencedirect.com", "entitlement_missing", 1],
      ["no_access", "SAGE", "login.openathens.net", "institution_federation_unavailable", 1],
      ["unexplained", "Taylor & Francis", "www.tandfonline.com", "download_failed", 1],
    ]);
    expect(summary.groups[0].evidence).toBe("Hong Mu-lan University does not subscribe to this content");
    expect(summary.groups[2].items[0]).toEqual({
      doi: "10.1080/0142159x.2026.2752868", runId: "20261101-133400-bbbbbb",
      stoppedAt: "pdf_candidate", diagnostic: "/runs/download_failed/diagnostic.json",
    });
  });

  it("prints the classes, the evidence and each unexplained failure's diagnostic", () => {
    const text = renderFailuresText(summarizeFailures(root, { since: "2026-10-31" }));
    expect(text).toContain("失败汇总：2026-10-31 至 2026-11-01，2 个批次；机构下载失败 3 篇（另有 1 篇没有走到机构下载）");
    expect(text).toContain("没权限（学校用不了这篇，批量最后换下一所学校再试）  2");
    expect(text).toContain("    依据：Hong Mu-lan University does not subscribe to this content");
    expect(text).toContain("原因不明（批量最后再试一次，留诊断记录）  1");
    expect(text).toContain("    10.1080/0142159x.2026.2752868  停在 pdf_candidate\n      /runs/download_failed/diagnostic.json");
    expect(text).toContain("paper-search failures --export <文件.zip>");
  });
});

it("takes a publisher page without its login entry for a site not supported yet, its screenshots listed", () => {
  // Thieme's Thrombosis and Haemostasis, 2026-11-22: recorded as download_failed, the state kept what it was.
  const root = mkdtempSync(join(tmpdir(), "failures-adaptation-"));
  const shots = ["/runs/x/diagnostics/a_screenshot.png", "/runs/x/diagnostics/a_snapshot-1-login-entry-missing.jpg"];
  run(root, "20261122-153624-1b396c", [
    { doi: "10.1160/TH12-05-0346", status: "error", stages: [{
      ...entitled("download_failed", "Thieme", "https://www.thieme-connect.de/products/ejournals/abstract/10.1160/th12-05-0346",
        { screenshots: [...shots, shots[0]], events: [{ state: "publisher_institution_entry_missing" }] }),
      failureClass: "unexplained",
      trace: { publisher: "Thieme", state: "publisher_institution_entry_missing" } }] },
  ]);
  const summary = summarizeFailures(root);
  // Its own class 网站适配问题 until 2026-11-22, now with the sites not supported yet (user: five classes).
  expect(summary.classes.unsupported).toBe(1);
  expect(summary.groups.map((g) => [g.failureClass, g.code])).toEqual([["unsupported", "publisher_institution_entry_missing"]]);
  expect(summary.groups[0].items[0].screenshots).toEqual(shots);
  const text = renderFailuresText(summary);
  expect(text).toContain("待适配（PaperSearch 的规则还没覆盖这个网站，我们来补）  1");
  expect(text).toContain("/runs/download_failed/diagnostic.json\n      截图：" + shots[0] + "\n      截图：" + shots[1]);
  expect(text).toContain("paper-search failures --export <文件.zip>");
});

it("groups the papers a verification stopped by its kind, when the record names it (user, 2026-11-25)", () => {
  const root = mkdtempSync(join(tmpdir(), "failures-challenge-"));
  const stopped = (doi: string, challengeType?: string) => ({ doi, status: "error", stages: [{
    ...entitled("captcha_required", "SAGE", "https://journals.sagepub.com/doi/" + doi),
    trace: { publisher: "SAGE", ...(challengeType ? { challengeType } : {}) } }] });
  run(root, "20261125-170000-cccccc", [
    stopped("10.1177/a", "recaptcha_v2_image"), stopped("10.1177/b", "recaptcha_v2_image"),
    stopped("10.1177/c", "cloudflare"), stopped("10.1177/d"), stopped("10.1177/e", "not-a-kind"),
  ]);
  const summary = summarizeFailures(root);
  expect(summary.groups.map((g) => [g.code, g.challengeType, g.count])).toEqual([
    ["captcha_required", "recaptcha_v2_image", 2],
    // Records before 2026-11-25, and a word the CLI does not know, stay as they were.
    ["captcha_required", undefined, 2],
    ["captcha_required", "cloudflare", 1],
  ]);
  const text = renderFailuresText(summary);
  expect(text).toContain("  SAGE · journals.sagepub.com · captcha_required · reCAPTCHA v2 图像识别  2");
  expect(text).toContain("  SAGE · journals.sagepub.com · captcha_required · Cloudflare 5 秒盾  1");
  expect(text).toContain("  SAGE · journals.sagepub.com · captcha_required  2");
});

it("includes partial attachments and filters DOI without counting completed empty checks", () => {
  const root = mkdtempSync(join(tmpdir(), "failures-supplements-"));
  run(root, "20261106-090000-aaaaaa", [
    { doi: "10.1234/partial", status: "ok", supplements: [{ status: "saved" }, { status: "failed", reason: "challenge_timeout" }],
      stages: [{ ...entitled("", "Fixture", "https://publisher.example/article"), stage: "supplements", status: "ok" }] },
    { doi: "10.1234/none", status: "ok", supplements: [], stages: [{ stage: "supplements", status: "skipped", code: "no_supplements" }] },
    { doi: "10.1234/unsupported", status: "ok", supplements: [{ status: "skipped", reason: "supplements_not_supported" }],
      stages: [{ ...entitled("", "Fixture", "https://publisher.example/article"), status: "ok" }] },
  ]);
  // Saved papers short of files are not failures (the batch counts them succeeded): told apart.
  const all = summarizeFailures(root);
  expect([all.failed, all.supplementsMissing]).toEqual([0, 2]);
  const selected = summarizeFailures(root, { doi: "10.1234/PARTIAL" });
  expect([selected.failed, selected.supplementsMissing, selected.groups]).toEqual([0, 1, []]);
  expect(selected.supplementGroups[0]).toMatchObject({ code: "challenge_timeout", reason: "被网站拦截", failureClass: "external" });
  expect(selected.supplementGroups[0].items[0].part).toBe("supplements");
});

it("tells a saved paper short of a file apart from the failures, as the batch counts it (AHA, 2026-11-22)", () => {
  const root = mkdtempSync(join(tmpdir(), "failures-shortfall-"));
  const events = [{ state: "pdf_saved" }, { state: "publisher_session_saved" }, { state: "supplements_listed_on_article", detail: "2" },
    { state: "supplements_found", detail: "2" }, { state: "supplements_saved", detail: "1/2" }];
  run(root, "20261123-022637-c8baa6", [
    // The PDF saved, one of its two files answered 404: the batch counted it succeeded.
    { doi: "10.1161/circoutcomes.125.012945", status: "ok",
      supplements: [{ status: "failed", label: "Download, SUPPL-1-DESCRIPTION (pdf 450.85)", reason: "http_404" },
        { status: "saved", label: "Download, DOCX (1.08 MB)" }],
      stages: [{ stage: "entitled_access", status: "ok", trace: { publisher: "AHA Journals" },
        backend: { record: { file: "/runs/x/diagnostics/circoutcomes_record.json", status: "success",
          final_url: "https://www.ahajournals.org/doi/10.1161/CIRCOUTCOMES.125.012945", events } } }] },
    { doi: "10.1161/atvbaha.125.000001", status: "error", stages: [entitled("entitlement_missing", "AHA Journals",
      "https://www.ahajournals.org/doi/10.1161/ATVBAHA.125.000001")] },
    // A file without a phrasing of its own (a PLOS paper's Figshare file, the same sweep): 附录没下载成功.
    { doi: "10.1371/journal.pone.0000001", status: "ok", supplements: [{ status: "failed", reason: "figshare_request_failed" }],
      stages: [{ stage: "entitled_access", status: "ok", trace: { publisher: "PLOS" },
        backend: { record: { final_url: "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0000001" } } }] },
  ]);
  const summary = summarizeFailures(root);
  // The run counted 1 failed; so does the summary.
  expect([summary.failed, summary.classes.unexplained, summary.classes.external]).toEqual([1, 0, 0]);
  expect(summary.groups.map((g) => [g.failureClass, g.code])).toEqual([["no_access", "entitlement_missing"]]);
  expect(summary.supplementsMissing).toBe(2);
  expect(summary.supplementGroups.map((g) => [g.failureClass, g.reason, g.code, g.count])).toEqual([
    // A file the page links that the site answers 404 for: the site's (外部原因), not 原因不明.
    ["external", "出版社网站出错", "http_404", 1],
    ["unexplained", "附录没下载成功", "figshare_request_failed", 1],
  ]);
  // Where the paper's visit stopped is not where its file failed.
  expect(summary.supplementGroups[0].items[0]).toEqual({ doi: "10.1161/circoutcomes.125.012945", runId: "20261123-022637-c8baa6",
    part: "supplements" });
  const text = renderFailuresText(summary);
  expect(text).toContain("机构下载失败 1 篇");
  expect(text).not.toContain("停在 pdf_saved");
  expect(text).toContain("附录未下全  2（正文已保存，不算失败）\n"
    + "  AHA Journals · www.ahajournals.org · 出版社网站出错 · http_404  1\n    10.1161/circoutcomes.125.012945");
  expect(text).toContain("  PLOS · journals.plos.org · 附录没下载成功 · figshare_request_failed  1\n    10.1371/journal.pone.0000001");
  // One left to look into (附录没下载成功 is 原因不明): the export's hint.
  expect(text).toContain("paper-search failures --export <文件.zip>");
});


it("reclassifies legacy subscription labels when the known failure code was corrected", () => {
  const root = mkdtempSync(join(tmpdir(), "failures-legacy-"));
  run(root, "20261106-090000-fixture", [{ doi: "10.1234/login", status: "error", stages: [
    { ...entitled("institution_not_registered", "Fixture", "https://publisher.example/login"),
      failureClass: "no_access", evidence: "old subscription inference" },
  ] }]);
  const summary = summarizeFailures(root);
  // No access by that entry (2026-11-19), said as such: never the old inference of no subscription.
  expect(summary.classes.no_access).toBe(1);
  expect(summary.groups[0].evidence).toBe("这个登录入口没有开通");
});
