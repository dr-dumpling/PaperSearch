import { spawnSync } from "child_process";
import { mkdtempSync, rmSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";

// Windows PowerShell drops the double quotes inside an argument and writes UTF-8 files with a BOM
// (DeepSeek on Windows, 2026-11-11): --json-args from a file must work, and a broken argument must say how.
describe("paper-search run --json-args", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(join(tmpdir(), "paper-search-json-args-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });
  const run = (...args: string[]) => {
    const env: NodeJS.ProcessEnv = { ...process.env, PAPER_SEARCH_CONFIG_DIR: dir };
    delete env.EASYSCHOLAR_KEY;
    const result = spawnSync(process.execPath, ["--import", "tsx", "src/cli.ts", "run", "query_journal_metrics", ...args],
      { cwd: process.cwd(), env, encoding: "utf8", timeout: 60_000 });
    return `${result.stdout}\n${result.stderr}`;
  };

  it("reads a file written with a byte order mark", () => {
    const file = join(dir, "args.json");
    writeFileSync(file, "\uFEFF" + JSON.stringify({ journal: "Nature" }), "utf8");
    const out = run("--json-args", `@${file}`);
    expect(out).not.toContain("INVALID_JSON_ARGS");
    expect(out).not.toContain("SyntaxError");
  });

  it("says how to pass JSON when the quotes were dropped", () => {
    const out = run("--json-args", "{journal:Nature}");
    expect(out).toContain("INVALID_JSON_ARGS");
    expect(out).toContain("--json-args '@<file>'");
  });
});
