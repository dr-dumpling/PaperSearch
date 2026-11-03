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
    expect(summary.classes).toEqual({ no_access: 2, user_or_external: 0, unsupported: 0, unexplained: 1 });
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
    expect(text).toContain("没权限（有依据）  2");
    expect(text).toContain("    依据：Hong Mu-lan University does not subscribe to this content");
    expect(text).toContain("原因不明（需排查）  1");
    expect(text).toContain("    10.1080/0142159x.2026.2752868  停在 pdf_candidate\n      /runs/download_failed/diagnostic.json");
  });
});
