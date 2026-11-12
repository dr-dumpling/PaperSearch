import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, existsSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";

const python = join(process.cwd(), "school/.venv/bin/python");
const backend = join(process.cwd(), "school/bin/paper-search-school");

describe("failures export CLI", () => {
  let root: string;
  beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), "failure-export-cli-"));
    const run = join(root, "runs/20261106-090000-fixture");
    mkdirSync(run, { recursive: true });
    const source = join(root, "diagnostic.json");
    writeFileSync(source, JSON.stringify({ doi: "10.1234/fixture", state: "login_entry_missing",
      events: [{ state: "login_entry_missing", detail: "a.institution" }],
      final_url: "https://publisher.example/article?token=fixture-secret" }));
    writeFileSync(join(run, "items.jsonl"), JSON.stringify({ doi: "10.1234/fixture", status: "error",
      stages: [{ stage: "entitled_access", status: "error", code: "generic_institution_entry_missing",
        trace: { publisher: "Fixture", diagnostic: source },
        backend: { diagnostic: { file: source, final_url: "https://publisher.example/article" } } }] }) + "\n");
  });
  afterEach(() => rmSync(root, { force: true, recursive: true }));

  function cli(args: string[], command = backend) {
    return spawnSync(process.execPath, [join(process.cwd(), "node_modules/.bin/tsx"), "src/cli.ts", "failures", ...args], {
      env: { ...process.env, HOME: root, XDG_DATA_HOME: join(root, "data"), XDG_CONFIG_HOME: join(root, "config"),
        SCHOOL_DATA_DIR: join(root, "school"), SCHOOL_PYTHON: python,
        PAPER_SEARCH_RUNLOG_DIR: join(root, "runs"), PAPER_SEARCH_RUNLOG: "1",
        PAPER_SEARCH_CONFIG_FILE: join(root, "config.json"), PAPER_SEARCH_SKILL_AUTO_UPDATE: "false",
        PAPER_SEARCH_HIDE_SETUP_HINT: "1", PAPER_SEARCH_SCHOOL_ENABLED: "false", PAPER_SEARCH_SCHOOL_EXECUTABLE: command },
      encoding: "utf8", timeout: 30000,
    });
  }

  // Installation-independent argument and missing-backend behavior always runs.
  it("rejects missing values, conflicting selectors and invalid counts", () => {
    for (const args of [["--export"], ["--doi"], ["--runs", "-1"], ["--runs", "1.5"], ["--run", "latest", "--runs", "2"]]) {
      const result = cli(args);
      expect(result.status).not.toBe(0);
    }
  });

  it("reports an unavailable backend without starting a download", () => {
    const result = cli(["--export", join(root, "report.zip")], join(root, "absent-backend"));
    expect(result.status).not.toBe(0);
    expect(result.stdout + result.stderr).toContain("无法启动学校订阅下载");
    expect(existsSync(join(root, "report.zip"))).toBe(false);
  });

  (process.platform !== "win32" ? it : it.skip)("rejects old backends and never echoes arbitrary backend errors", () => {
    const old = join(root, "old-backend.cjs");
    writeFileSync(old, '#!/usr/bin/env node\nconsole.error("private backend stderr"); console.log("unsupported command"); process.exit(2);\n');
    chmodSync(old, 0o755);
    const result = cli(["--export", join(root, "old.zip")], old);
    expect(result.status).not.toBe(0);
    expect(result.stdout + result.stderr).toContain("更新支持 report-export");
    expect(result.stdout + result.stderr).not.toContain("private backend stderr");
    writeFileSync(old, '#!/usr/bin/env node\nconsole.log(JSON.stringify({ok:false,error:"password=fixture_secret"})); process.exit(1);\n');
    const secret = cli(["--export", join(root, "secret.zip")], old);
    expect(secret.status).not.toBe(0);
    expect(secret.stdout + secret.stderr).toContain("export_failed");
    expect(secret.stdout + secret.stderr).not.toContain("fixture_secret");
  });

  (existsSync(python) && process.platform !== "win32" ? it : it.skip)("exports through the real offline Python command with a private temporary home", () => {
    const source = readFileSync(join(root, "diagnostic.json"));
    const output = join(root, "report.zip");
    const result = cli(["--doi", "https://doi.org/10.1234/FIXTURE", "--export", output]);
    expect(result.status).toBe(0);
    expect(JSON.parse(result.stdout)).toEqual(expect.objectContaining({ ok: true, schemaVersion: 1, papers: 1,
      path: output, reviewRequired: true, incompletePapers: 1 }));
    expect(readFileSync(output).subarray(0, 2).toString()).toBe("PK");
    expect(readFileSync(join(root, "diagnostic.json"))).toEqual(source);
    const again = cli(["--export", output]);
    expect(again.status).not.toBe(0);
    expect(again.stdout + again.stderr).toContain("export_target_exists");
  });
});
