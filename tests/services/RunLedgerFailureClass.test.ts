import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "@jest/globals";
import { RunLedger } from "../../src/infrastructure/runlog/RunLedger.js";

describe("run ledger failure class", () => {
  it("records the class of a failed institutional download with where it stopped", () => {
    const root = mkdtempSync(join(tmpdir(), "ledger-class-"));
    const diagDir = join(root, "out", "diag");
    mkdirSync(diagDir, { recursive: true });
    const diagnostic = join(diagDir, "diagnostic.json");
    writeFileSync(diagnostic, JSON.stringify({
      state: "sso_required", adapter: "TaylorFrancisAdapter",
      browser: { backend: "chrome", app: "Google Chrome", version: "156.0.8078.81", driver: "patchright 1.64.4" },
      final_url: "https://www.tandfonline.com/doi/full/10.1080/01616412.2026.2757106",
      events: [{ state: "sso_entry_clicked" }, { state: "user_wait_expired" }, { state: "login_wait_ended", detail: "publisher" }],
    }));
    const ledger = RunLedger.open({ kind: "download_batch", total: 1 }, { PAPER_SEARCH_RUNLOG_DIR: root })!;
    const item = { index: 1, paperId: "10.1080/01616412.2026.2757106", doi: "10.1080/01616412.2026.2757106" };
    ledger.stage(item, {
      stage: "entitled_access", status: "error", code: "login_not_reached", message: "x",
      startedAt: new Date().toISOString(), durationMs: 1000, trace: { publisher: "Taylor & Francis", diagnostic },
    });
    ledger.item(item, { status: "error", attempts: [] } as never);
    const line = JSON.parse(readFileSync(join(ledger.dir, "items.jsonl"), "utf8"));
    expect(line.stages[0]).toMatchObject({
      failureClass: "unexplained", stoppedAt: "login_wait_ended：publisher",
      backend: { diagnostic: { adapter: "TaylorFrancisAdapter",
        browser: { backend: "chrome", app: "Google Chrome", version: "156.0.8078.81", driver: "patchright 1.64.4" } } },
    });
    expect(readFileSync(join(ledger.dir, "timeline.log"), "utf8")).toContain("login_not_reached class=unexplained");
  });
});
