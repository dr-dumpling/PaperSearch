import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "@jest/globals";

/**
 * PaperSearch Pro's features (src/config/edition.ts): the public edition before 1.0.0 has them off
 * (user, 2026-11-19), and then the command shows no Markdown, no `paper-search pro` and takes none.
 */
const root = mkdtempSync(join(tmpdir(), "papersearch-pro-switch-"));
afterAll(() => rmSync(root, { recursive: true, force: true }));
const runs = join(root, "runs");
mkdirSync(runs, { recursive: true });

function cli(args: string[], pro: "0" | "1" | undefined) {
  return spawnSync(process.execPath, ["--import", "tsx", "src/cli.ts", ...args], {
    env: { ...process.env, HOME: root, XDG_DATA_HOME: join(root, "data"), XDG_CONFIG_HOME: join(root, "config"),
      PAPER_SEARCH_CONFIG_FILE: join(root, "config.json"), PAPER_SEARCH_SKILL_AUTO_UPDATE: "false",
      PAPER_SEARCH_HIDE_SETUP_HINT: "1", PAPER_SEARCH_UPDATE_NOTIFY: "false", PAPER_SEARCH_SCHOOL_AUTO_UPDATE: "false",
      PAPER_SEARCH_RUNLOG_DIR: runs, PAPER_SEARCH_RUNLOG: "1", PAPER_SEARCH_PRO_FEATURES: pro },
    encoding: "utf8", timeout: 20000,
  });
}

describe("PaperSearch Pro's features switched off", () => {
  it("are as package.json says when nothing overrides it", () => {
    const packaged = JSON.parse(readFileSync("package.json", "utf8")).paperSearch?.proFeatures === true;
    expect(cli(["--help"], undefined).stdout.includes("paper-search pro <status")).toBe(packaged);
  });

  it("leaves the Markdown and `paper-search pro` out of the usage and the tools", () => {
    const usage = cli(["--help"], "0").stdout;
    expect(usage).toContain("paper-search download <paper-id>");
    expect(usage).not.toMatch(/markdown|paper-search pro\b/i);
    expect(cli(["--help"], "1").stdout).toMatch(/paper-search pro <status\|check\|install>[\s\S]*--content pdf\|markdown/);
    const tools = cli(["tools"], "0");
    expect(tools.status).toBe(0);
    expect(tools.stdout).toContain("download_batch");
    expect(tools.stdout).not.toMatch(/markdown/i);
  });

  it("takes no `pro` command, no failures --markdown and no markdown content", () => {
    const pro = cli(["pro", "status"], "0");
    expect(pro.status).not.toBe(0);
    expect(pro.stdout + pro.stderr).toContain("Unknown command: pro");
    expect(JSON.parse(cli(["pro", "status"], "1").stdout)).toMatchObject({ installed: false });
    const failures = cli(["failures", "--markdown"], "0");
    expect(failures.status).not.toBe(0);
    expect(failures.stdout + failures.stderr).toContain("这个版本没有 --markdown");
    // Refused as it is read, before any download.
    const download = cli(["download", "10.1000/x", "--platform", "crossref", "--content", "markdown"], "0");
    expect(download.status).not.toBe(0);
    expect(download.stdout + download.stderr).toContain("content: pdf");
    expect(download.stdout + download.stderr).not.toContain("pdf,markdown");
  });
});
