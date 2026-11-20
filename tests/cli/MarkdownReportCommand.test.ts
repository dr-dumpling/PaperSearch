import { spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";
import { markdownPages, markdownSites } from "../../src/management/failures/markdownReport.js";

// PaperSearch Pro's features on, whatever the edition (src/config/edition.ts).
process.env.PAPER_SEARCH_PRO_FEATURES = "1";

const python = join(process.cwd(), "school/.venv/bin/python");
const backend = join(process.cwd(), "school/bin/paper-search-school");

// Pages from sites not yet supported whose Markdown was not kept (user, 2026-11-16).
describe("failures --markdown", () => {
  let root: string;
  const runs = () => join(root, "runs");
  const report = (run: string, doi: string, extra: Record<string, unknown> = {}) => {
    const records = join(runs(), run, "records");
    mkdirSync(records, { recursive: true });
    const name = doi.replace(/[^A-Za-z0-9._-]+/g, "_");
    writeFileSync(join(records, `${name}_markdown-page.html`), "<html><body><main><h2 class=\"t\">Methods</h2></main></body></html>");
    writeFileSync(join(records, `${name}_markdown-report.json`), JSON.stringify({ schemaVersion: 1, doi, host: "ard.eular.org",
      template: "elsevier-journal", shortfall: { references: 1 }, url: `https://ard.eular.org/doi/${doi}`, ...extra }));
  };
  beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), "markdown-report-cli-"));
    const run = "20261116-090000-aaaaaa";
    mkdirSync(join(runs(), run), { recursive: true });
    writeFileSync(join(runs(), run, "run.json"), JSON.stringify({ schema: 1, runId: run, kind: "download_batch", savePath: join(root, "batch") }));
    writeFileSync(join(runs(), run, "items.jsonl"), JSON.stringify({ doi: "10.1016/j.ard.2026.05.001", title: "Predicting progression" }) + "\n");
    report(run, "10.1016/j.ard.2026.05.001");
    report(run, "10.1016/j.ard.2026.05.002", { host: "journals.example.org", template: null, shortfall: {} });
    // Converted completely by another site's rules and saved: in the same report (user, 2026-11-17).
    report(run, "10.1016/j.jacc.2026.06.017", { host: "www.jacc.org", template: "atypon-current", rules: "Atypon", shortfall: undefined, status: "ok" });
  });
  afterEach(() => rmSync(root, { force: true, recursive: true }));

  function cli(args: string[], command = backend) {
    return spawnSync(process.execPath, [join(process.cwd(), "node_modules/tsx/dist/cli.mjs"), "src/cli.ts", "failures", "--markdown", ...args], {
      env: { ...process.env, HOME: root, XDG_DATA_HOME: join(root, "data"), XDG_CONFIG_HOME: join(root, "config"),
        SCHOOL_DATA_DIR: join(root, "school"), SCHOOL_PYTHON: python,
        PAPER_SEARCH_RUNLOG_DIR: runs(), PAPER_SEARCH_RUNLOG: "1",
        PAPER_SEARCH_CONFIG_FILE: join(root, "config.json"), PAPER_SEARCH_SKILL_AUTO_UPDATE: "false",
        PAPER_SEARCH_HIDE_SETUP_HINT: "1", PAPER_SEARCH_SCHOOL_ENABLED: "false", PAPER_SEARCH_SCHOOL_EXECUTABLE: command },
      encoding: "utf8", timeout: 30000,
    });
  }

  it("lists the kept pages by site with what they lacked", () => {
    const pages = markdownPages(runs(), {});
    expect(pages.map((page) => [page.doi, page.title ?? "", page.host, page.saved, page.lacks])).toEqual([
      ["10.1016/j.ard.2026.05.001", "Predicting progression", "ard.eular.org", false, ["参考文献不全"]],
      ["10.1016/j.ard.2026.05.002", "", "journals.example.org", false, ["没有规则能读出正文"]],
      ["10.1016/j.jacc.2026.06.017", "", "www.jacc.org", true, []]]);
    expect(markdownSites(pages)).toEqual([
      { host: "ard.eular.org", papers: 1, saved: 0, rules: [], lacks: { 参考文献不全: 1 } },
      { host: "journals.example.org", papers: 1, saved: 0, rules: [], lacks: { 没有规则能读出正文: 1 } },
      { host: "www.jacc.org", papers: 1, saved: 1, rules: ["Atypon"], lacks: {} }]);
    expect(markdownPages(runs(), { doi: "10.1016/J.ARD.2026.05.002" }).map((page) => page.host)).toEqual(["journals.example.org"]);
    const text = cli(["--format", "text"]);
    expect(text.status).toBe(0);
    expect(text.stdout).toContain("- ard.eular.org：1 篇；完整已保存 0 篇，没保存 1 篇（参考文献不全 1）");
    expect(text.stdout).toContain("- www.jacc.org：1 篇，采用 Atypon 规则；完整已保存 1 篇");
  });

  (process.platform !== "win32" ? it : it.skip)("asks the backend for the ZIP in the batch's folder, and never echoes its errors", () => {
    const seen = join(root, "request.json");
    const fake = join(root, "backend.cjs");
    writeFileSync(fake, `#!/usr/bin/env node
let input = ""; process.stdin.on("data", (c) => { input += c; }); process.stdin.on("end", () => {
  require("fs").writeFileSync(${JSON.stringify(seen)}, JSON.stringify({ args: process.argv.slice(2), input: JSON.parse(input) }));
  console.log(JSON.stringify({ ok: true, path: ${JSON.stringify(join(root, "batch", "r.zip"))}, name: "r.zip", papers: 2, sites: [], bytes: 1,
    issueUrl: "https://github.com/dr-dumpling/PaperSearch/issues/new?template=markdown-site.yml" })); });\n`);
    chmodSync(fake, 0o755);
    const result = cli(["--export"], fake);
    expect(result.status).toBe(0);
    const request = JSON.parse(readFileSync(seen, "utf8"));
    expect(request.args).toEqual(["markdown-report-export", "--folder", join(root, "batch")]);
    expect(request.input.reports.map((r: { doi: string; title?: string }) => [r.doi, r.title ?? ""])).toEqual([
      ["10.1016/j.ard.2026.05.001", "Predicting progression"], ["10.1016/j.ard.2026.05.002", ""], ["10.1016/j.jacc.2026.06.017", ""]]);
    writeFileSync(fake, '#!/usr/bin/env node\nconsole.log(JSON.stringify({ok:false,error:"password=fixture_secret"})); process.exit(1);\n');
    const failed = cli(["--export", join(root, "x.zip")], fake);
    expect(failed.status).not.toBe(0);
    expect(failed.stdout + failed.stderr).toContain("export_failed");
    expect(failed.stdout + failed.stderr).not.toContain("fixture_secret");
  });

  (existsSync(python) && process.platform !== "win32" ? it : it.skip)("exports through the real offline Python command", () => {
    const output = join(root, "md.zip");
    const result = cli(["--export", output]);
    expect(result.status).toBe(0);
    const data = JSON.parse(result.stdout);
    // The page converted whole by borrowed rules goes in too (one report, user 2026-11-17).
    expect(data).toMatchObject({ ok: true, path: output, papers: 3, sites: ["ard.eular.org", "journals.example.org", "www.jacc.org"] });
    expect(data.issueUrl).toContain("template=markdown-site.yml");
    expect(data.issueUrl).not.toContain("10.1016");
  });
});
