import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "@jest/globals";
import {
  collapseEvents,
  pruneOldRuns,
  resolveRunLogRoot,
  RUN_KEEP_DAYS,
  RunLedger,
} from "../../src/infrastructure/runlog/RunLedger.js";
import { normalizeDownloadResult } from "../../src/capabilities/pdf-discovery/school/SchoolResultNormalizer.js";

function toolResult(payload: unknown) {
  return { content: [{ type: "text", text: JSON.stringify(payload) }] };
}

describe("run ledger", () => {
  it("resolves its root from the override, XDG or the home data dir, and can be turned off", () => {
    expect(resolveRunLogRoot({ PAPER_SEARCH_RUNLOG_DIR: "/x/runs" }, "/home/u")).toBe("/x/runs");
    expect(resolveRunLogRoot({ XDG_DATA_HOME: "/data" }, "/home/u")).toBe("/data/paper-search-cli/runs");
    expect(resolveRunLogRoot({}, "/home/u")).toBe("/home/u/.local/share/paper-search-cli/runs");
    expect(resolveRunLogRoot({ PAPER_SEARCH_RUNLOG: "0", PAPER_SEARCH_RUNLOG_DIR: "/x" })).toBeNull();
    expect(RunLedger.open({ kind: "download", total: 1 }, { PAPER_SEARCH_RUNLOG: "0" })).toBeNull();
  });

  it("keeps its records and diagnostics in its own folder, nothing in the download folder", () => {
    // The download folder holds only papers (user, 2026-11-11).
    const root = mkdtempSync(join(tmpdir(), "ledger-"));
    const downloads = join(root, "downloads");
    mkdirSync(downloads);
    const ledger = RunLedger.open({ kind: "download", total: 1, savePath: downloads }, { PAPER_SEARCH_RUNLOG_DIR: join(root, "runs") })!;
    expect(ledger.records).toBe(join(ledger.dir, "records"));
    expect(ledger.diagnostics).toBe(join(ledger.dir, "diagnostics"));
    ledger.close();
    expect(readdirSync(downloads)).toEqual([]);
    expect(existsSync(join(ledger.dir, "run.json"))).toBe(true);
  });

  it(`removes run folders started more than ${RUN_KEEP_DAYS} days ago as a new run starts, and nothing else`, () => {
    const root = mkdtempSync(join(tmpdir(), "ledger-"));
    const now = new Date(2026, 10, 11, 12, 0, 0);
    // Folder names in local time, days before ``now``: a clock change between them does not matter.
    const pad = (n: number) => String(n).padStart(2, "0");
    const run = (days: number, id: string) => {
      const at = new Date(now.getTime() - days * 86_400_000);
      return `${at.getFullYear()}${pad(at.getMonth() + 1)}${pad(at.getDate())}-${pad(at.getHours())}${pad(at.getMinutes())}${pad(at.getSeconds())}-${id}`;
    };
    const [old, recent, today] = [run(RUN_KEEP_DAYS + 1, "aaaaaa"), run(RUN_KEEP_DAYS - 1, "bbbbbb"), run(0.04, "cccccc")];
    for (const name of [old, recent, today, "notes", "20261001-000000"]) {
      mkdirSync(join(root, name));
      writeFileSync(join(root, name, "run.json"), "{}");
    }
    writeFileSync(join(root, "batch-folders.json"), "{}");
    expect(pruneOldRuns(root, now)).toEqual([old]);
    expect(readdirSync(root).sort()).toEqual(["20261001-000000", recent, today, "batch-folders.json", "notes"].sort());
    // Opening a run does it, silently.
    mkdirSync(join(root, run(60, "dddddd")));
    const ledger = RunLedger.open({ kind: "download", total: 1 }, { PAPER_SEARCH_RUNLOG_DIR: root }, now)!;
    expect(existsSync(join(root, run(60, "dddddd")))).toBe(false);
    expect(existsSync(ledger.dir)).toBe(true);
    expect(pruneOldRuns(join(root, "missing"), now)).toEqual([]);
  });

  it("records stages, the backend's collapsed events and screenshots, and the final counts", () => {
    const root = mkdtempSync(join(tmpdir(), "ledger-"));
    const diagDir = join(root, "out", ".browser_runs", "diagnostics", "10.1_x");
    mkdirSync(diagDir, { recursive: true });
    const diagnostic = join(diagDir, "diagnostic.json");
    writeFileSync(diagnostic, JSON.stringify({
      state: "sso_required",
      final_url: "https://publisher.example/login",
      access_evidence: ["Institutional Login"],
      phases: { open: 12.3, verification: 22, login: 300.5 },
      browser_start: { holder: "free", waited: 0, released: true, seconds: 3.1 },
      pdf_attempts: [{ how: "url", url: "https://publisher.example/pdf", outcome: "html page", seconds: 4.2 }],
      snapshots: [{ why: "login entry missing", url: "https://publisher.example/a", title: "A" }],
      events: [
        { state: "article_open", at: "10:00:00", detail: "https://doi.org/10.1/x" },
        { state: "challenge_wait", at: "10:00:01", detail: "1" },
        { state: "challenge_wait", at: "10:00:02", detail: "2" },
        { state: "challenge_wait", at: "10:00:03", detail: "3" },
        { state: "login_state", at: "10:00:09", detail: "x".repeat(900) },
      ],
    }));
    writeFileSync(join(diagDir, "screenshot.png"), "png");

    const ledger = RunLedger.open(
      { kind: "download_batch", mode: "two_phase", total: 2, batchId: "b1" },
      { PAPER_SEARCH_RUNLOG_DIR: root },
    )!;
    const first = { index: 1, paperId: "10.1/x", doi: "10.1/x", title: "A title" };
    ledger.phase("开放来源 2 篇");
    ledger.stage(first, { stage: "unpaywall", status: "error", message: "none", code: "not_found", startedAt: new Date().toISOString(), durationMs: 1200 });
    ledger.stage(first, {
      stage: "entitled_access", status: "error", message: "login", code: "login_required",
      startedAt: new Date().toISOString(), durationMs: 90_000,
      trace: { driver: "publisher", publisher: "Karger", state: "sso_required", diagnostic },
    });
    ledger.item(first, { status: "error", attempts: [] });
    const second = { index: 2, paperId: "10.1/y", doi: "10.1/y" };
    ledger.stage(second, { stage: "primary", status: "ok", message: "ok", path: "/tmp/y.pdf", startedAt: new Date().toISOString(), durationMs: 10 });
    ledger.item(second, { status: "ok", path: "/tmp/y.pdf", attempts: [] });
    ledger.close({ entitledAccessItems: 1 });

    const run = JSON.parse(readFileSync(join(ledger.dir, "run.json"), "utf8"));
    expect(run).toEqual(expect.objectContaining({ kind: "download_batch", mode: "two_phase", total: 2, succeeded: 1, failed: 1, entitledAccessItems: 1 }));
    expect(run.endedAt).toEqual(expect.any(String));

    const items = readFileSync(join(ledger.dir, "items.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
    expect(items.map((i) => [i.index, i.status, i.stages.length])).toEqual([[1, "error", 2], [2, "ok", 1]]);
    const backend = items[0].stages[1].backend.diagnostic;
    expect(backend).toEqual(expect.objectContaining({ file: diagnostic, state: "sso_required", final_url: "https://publisher.example/login" }));
    expect(backend.screenshots).toEqual([join(diagDir, "screenshot.png")]);
    expect(backend.phases).toEqual({ open: 12.3, verification: 22, login: 300.5 });
    expect(backend.browser_start.holder).toBe("free");
    expect(backend.pdf_attempts[0].outcome).toBe("html page");
    expect(backend.snapshots[0].why).toBe("login entry missing");
    expect(backend.events.map((e: { state: string; count?: number }) => [e.state, e.count])).toEqual([
      ["article_open", undefined], ["challenge_wait", 3], ["login_state", undefined],
    ]);
    expect(backend.events[1].lastAt).toBe("10:00:03");
    expect(backend.events[2].detail.length).toBeLessThan(520);

    const timeline = readFileSync(join(ledger.dir, "timeline.log"), "utf8");
    expect(timeline).toContain("== 开放来源 2 篇");
    expect(timeline).toMatch(/#1 10\.1\/x entitled_access error login_required class=unexplained 90\.0s \[Karger\/publisher state=sso_required last=login_state url=https:\/\/publisher\.example\/login\]/);
    expect(timeline).toContain("#2 10.1/y => ok /tmp/y.pdf");
    expect(timeline).toContain("end succeeded=1 failed=1");
  });

  it("records an unreadable backend file instead of dropping it", () => {
    const root = mkdtempSync(join(tmpdir(), "ledger-"));
    const ledger = RunLedger.open({ kind: "download", total: 1 }, { PAPER_SEARCH_RUNLOG_DIR: root })!;
    const item = { index: 1, paperId: "10.1/x" };
    ledger.stage(item, { stage: "entitled_access", status: "error", message: "x", startedAt: new Date().toISOString(), durationMs: 1, trace: { record: join(root, "missing.json") } });
    ledger.item(item, { status: "error", attempts: [] });
    const line = JSON.parse(readFileSync(join(ledger.dir, "items.jsonl"), "utf8"));
    expect(line.stages[0].backend.record.error).toMatch(/ENOENT/);
  });

  it("collapses only consecutive repeats", () => {
    expect(collapseEvents([{ state: "a" }, { state: "b" }, { state: "a" }, { state: "a" }]).map((e) => [e.state, e.count]))
      .toEqual([["a", undefined], ["b", undefined], ["a", 2]]);
  });
});

describe("backend trace for the ledger", () => {
  const out = "/data/out";
  it("keeps validated labels and record files inside the request's output directory", () => {
    const outcome = normalizeDownloadResult(toolResult({
      success: false, error_type: "login_required", action: "review_browser",
      artifacts: {
        driver: "publisher", publisher: "Karger", state: "sso_required",
        record: "/data/out/.browser_runs/run.json",
        diagnostic: "/elsewhere/diagnostic.json",
      },
    }), "10.1/x", out);
    expect(outcome).toEqual(expect.objectContaining({
      kind: "attempt_error",
      trace: { driver: "publisher", publisher: "Karger", state: "sso_required", record: "/data/out/.browser_runs/run.json" },
    }));
  });

  it("drops free text, traversal and files when no output directory is known", () => {
    const payload = {
      success: false, error_type: "paywall",
      artifacts: { publisher: "see https://x.example/?token=abc", state: "Not A Code", record: "/data/out/../secret.json" },
    };
    expect(normalizeDownloadResult(toolResult(payload), "10.1/x", out)).not.toHaveProperty("trace");
    const withFile = { success: true, file: "/data/out/x.pdf", artifacts: { record: "/data/out/r.json" } };
    expect(normalizeDownloadResult(toolResult(withFile), "10.1/x")).not.toHaveProperty("trace");
    expect(normalizeDownloadResult(toolResult(withFile), "10.1/x", out)).toEqual(expect.objectContaining({ trace: { record: "/data/out/r.json" } }));
  });
});
