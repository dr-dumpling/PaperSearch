import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";

describe("CLI update notices", () => {
  let root: string;
  let guard: string;
  beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), "papersearch-update-cli-"));
    const data = join(root, "data/paper-search-cli");
    mkdirSync(data, { recursive: true });
    const now = Date.now();
    writeFileSync(join(data, "update-check.json"), JSON.stringify({
      schemaVersion: 1, checkedAt: now, latest: "99.0.0", latestCheckedAt: now,
    }));
    guard = join(root, "transport.cjs");
    writeFileSync(guard, 'globalThis.fetch = async () => { console.error("UNEXPECTED_NETWORK"); throw new Error("blocked in test"); };');
  });
  afterEach(() => rmSync(root, { recursive: true, force: true }));

  function cli(args: string[], env: Record<string, string | undefined> = {}) {
    return spawnSync(process.execPath, ["--require", guard, "--import", "tsx", "src/cli.ts", ...args], {
      env: { ...process.env, HOME: root, XDG_DATA_HOME: join(root, "data"), XDG_CONFIG_HOME: join(root, "config"),
        PAPER_SEARCH_CONFIG_FILE: join(root, "config.json"), PAPER_SEARCH_SKILL_AUTO_UPDATE: "false",
        PAPER_SEARCH_HIDE_SETUP_HINT: "1", PAPER_SEARCH_UPDATE_NOTIFY: "true", CI: "", ...env },
      encoding: "utf8", timeout: 10000,
    });
  }

  it("prints a cached reminder each time without changing JSON or exit status", () => {
    for (let i = 0; i < 2; i += 1) {
      const result = cli(["tools"]);
      expect(result.status).toBe(0);
      expect(JSON.parse(result.stdout).ok).toBe(true);
      expect(result.stderr.match(/PaperSearch update available:/g)).toHaveLength(1);
      expect(result.stderr).toContain("99.0.0");
      expect(result.stderr).not.toContain("UNEXPECTED_NETWORK");
    }
    const result = cli(["not-a-command"]);
    expect(result.status).toBe(1);
    expect(JSON.parse(result.stdout).ok).toBe(false);
    expect(result.stderr).toContain("PaperSearch update available:");
  });

  it("honors the switch, CI and informational-command exemptions", () => {
    for (const [args, env] of [
      [["tools"], { PAPER_SEARCH_UPDATE_NOTIFY: "false" }],
      [["tools"], { CI: "true" }],
      [["--help"], {}], [["--version"], {}], [["config", "keys"], {}],
    ] as [string[], Record<string, string>][]) {
      const result = cli(args, env);
      expect(result.status).toBe(0);
      expect(result.stderr).not.toContain("PaperSearch update available:");
      expect(result.stderr).not.toContain("UNEXPECTED_NETWORK");
    }
    writeFileSync(join(root, "config.json"), JSON.stringify({ PAPER_SEARCH_UPDATE_NOTIFY: "false" }));
    expect(cli(["tools"], { PAPER_SEARCH_UPDATE_NOTIFY: undefined }).stderr).not.toContain("PaperSearch update available:");
  });

  it("checks explicitly even with automatic checks disabled and reports bounded failure", () => {
    writeFileSync(guard, `globalThis.fetch = async () => new Response(JSON.stringify({
      name: "papersearch", version: "99.0.0", dist: {tarball: "https://registry.npmjs.org/papersearch/-/papersearch-99.0.0.tgz"}
    }));`);
    const success = cli(["update", "check"], { PAPER_SEARCH_UPDATE_NOTIFY: "false" });
    expect(success.status).toBe(0);
    expect(JSON.parse(success.stdout)).toEqual(expect.objectContaining({ ok: true, latestVersion: "99.0.0", updateAvailable: true }));
    expect(success.stderr).not.toContain("PaperSearch update available:");
    writeFileSync(guard, 'globalThis.fetch = async () => { throw new Error("private proxy credentials"); };');
    const failure = cli(["update", "check"]);
    expect(failure.status).toBe(1);
    expect(JSON.parse(failure.stdout)).toEqual(expect.objectContaining({ ok: false, status: "unavailable", latestVersion: null }));
    expect(failure.stdout + failure.stderr).not.toContain("private proxy credentials");
  });
});
