import { describe, expect, it } from "@jest/globals";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { checkSelf, compareVersions, globalPrefixOf, installedCopies, installSelf, npmCommand, updateSourceOf } from "../../src/management/updates/selfUpdate.js";
import { renderDoctorTextReport } from "../../src/management/reports/index.js";

// The settings window's 更新 (user, 2026-11-21: one version, one button).
describe("PaperSearch's own update", () => {
  it("updates from where its package says: the private install from its repository, any other from npm", () => {
    expect(updateSourceOf({ paperSearch: { updateFrom: "github:dr-dumpling/PaperSearch-Private#main" } }))
      .toEqual({ kind: "github", owner: "dr-dumpling", repo: "PaperSearch-Private", branch: "main" });
    expect(updateSourceOf({ paperSearch: { updateFrom: "github:o/r" } })).toEqual({ kind: "github", owner: "o", repo: "r", branch: "main" });
    expect(updateSourceOf({ paperSearch: { proFeatures: true } })).toEqual({ kind: "npm" });
    expect(updateSourceOf({ paperSearch: { updateFrom: "https://example.com/x.tgz" } })).toEqual({ kind: "npm" });
    expect(updateSourceOf(undefined)).toEqual({ kind: "npm" });
  });

  it("orders versions as releases go, previews numbered", () => {
    expect(compareVersions("0.7.2-preview.10", "0.7.2-preview.9")).toBe(1);
    expect(compareVersions("0.7.2", "0.7.2-preview.4")).toBe(1);
    expect(compareVersions("0.7.2-preview.4", "0.7.3")).toBe(-1);
    expect(compareVersions("0.7.2-preview.4", "0.7.2-preview.4")).toBe(0);
    expect(compareVersions("0.10.0", "0.9.9")).toBe(1);
    expect(compareVersions("latest", "0.7.2")).toBeUndefined();
  });

  it("checks npm's stable release for a public install", async () => {
    const result = await checkSelf({ current: "0.7.2", source: { kind: "npm" }, queryNpm: async () => "0.7.3" });
    expect(result).toMatchObject({ ok: true, source: "npm", latest: "0.7.3", update: true });
    expect(await checkSelf({ current: "0.7.3", source: { kind: "npm" }, queryNpm: async () => "0.7.3" }))
      .toMatchObject({ ok: true, update: false });
    expect(await checkSelf({ current: "0.7.3", source: { kind: "npm" }, queryNpm: async () => { throw new Error("down"); } }))
      .toMatchObject({ ok: false, code: "update_check_failed" });
  });

  it("reads the private repository's package.json with the computer's GitHub login, and asks for one without it", async () => {
    const source = { kind: "github" as const, owner: "o", repo: "r", branch: "main" };
    const asked: Array<{ url: string; auth?: string }> = [];
    const get = (async (url: string, config: { headers: Record<string, string> }) => {
      asked.push({ url, auth: config.headers.Authorization });
      return { data: JSON.stringify({ version: "0.7.2-preview.5" }) };
    }) as never;
    const result = await checkSelf({ current: "0.7.2-preview.4", source, env: { GH_TOKEN: "t0ken" }, get });
    expect(result).toMatchObject({ ok: true, source: "github", latest: "0.7.2-preview.5", update: true,
      releaseNotesUrl: "https://github.com/o/r/blob/main/CHANGELOG.md" });
    expect(asked).toEqual([{ url: "https://api.github.com/repos/o/r/contents/package.json?ref=main", auth: "Bearer t0ken" }]);
    // No login: gh is looked for too; with none found (an empty PATH, no gh in its usual places) the answer says so.
    const none = await checkSelf({ current: "0.7.2-preview.4", source, env: { PATH: "" }, get });
    if (!none.ok) expect(none.code).toMatch(/^github_login_(required|unreadable)$/);
    // None at all: sign in. One gh has but cannot read here (macOS over SSH, the keychain shut; user 2026-11-21:
    // "我已经login了，还要我再login"): not to sign in again, but to do it on the computer itself.
    expect(await checkSelf({ current: "0.7.2-preview.4", source, githubToken: "", ghStatus: () => "You are not logged into any GitHub hosts.", get }))
      .toEqual({ ok: false, source: "github", current: "0.7.2-preview.4", code: "github_login_required", message: "请先在终端运行 gh auth login 登录 GitHub" });
    const shut = "github.com\n  X Timeout trying to log in to github.com account someone (default)\n  - Active account: true";
    expect(await checkSelf({ current: "0.7.2-preview.4", source, githubToken: "", ghStatus: () => shut, get }))
      .toEqual({ ok: false, source: "github", current: "0.7.2-preview.4", code: "github_login_unreadable",
        message: "读不到 GitHub 登录（远程连接读不到），请在这台电脑上直接操作" });
    expect(await installSelf({ ok: true, source: "github", current: "0.7.2-preview.4", latest: "0.7.2-preview.5", update: true, releaseNotesUrl: "" },
      { source, githubToken: "", ghStatus: () => shut, run: () => { throw new Error("no install"); } }))
      .toMatchObject({ ok: false, code: "github_login_unreadable" });
  });

  it("installs with the npm beside node: npm's release by its version, the repository's tarball as a file", async () => {
    const runs: string[][] = [];
    const run = (argv: string[]) => { runs.push(argv); return { status: 0, stderr: "" }; };
    const npm = ["node", "npm-cli.js"];
    expect(await installSelf({ ok: true, source: "npm", current: "0.7.2", latest: "0.7.3", update: true, releaseNotesUrl: "" },
      { source: { kind: "npm" }, npm, run })).toEqual({ ok: true, from: "0.7.2", to: "0.7.3" });
    expect(runs[0]).toEqual(["node", "npm-cli.js", "install", "-g", "--no-audit", "--no-fund", "papersearch@0.7.3"]);
    let kept = "";
    const get = (async () => ({ data: new TextEncoder().encode("tarball").buffer })) as never;
    const github = { kind: "github" as const, owner: "o", repo: "r", branch: "main" };
    const result = await installSelf({ ok: true, source: "github", current: "0.7.2-preview.4", latest: "0.7.2-preview.5", update: true, releaseNotesUrl: "" },
      { source: github, env: { GH_TOKEN: "t" }, npm, get, run: (argv) => { kept = argv.at(-1)!; return { status: 0, stderr: "" }; } });
    expect(result).toEqual({ ok: true, from: "0.7.2-preview.4", to: "0.7.2-preview.5" });
    expect(kept).toMatch(/papersearch-0\.7\.2-preview\.5\.tgz$/);
    expect(existsSync(kept)).toBe(false);  // the file gone once installed
    expect(await installSelf({ ok: true, source: "npm", current: "0.7.2", latest: "0.7.3", update: true, releaseNotesUrl: "" },
      { source: { kind: "npm" }, npm, run: () => ({ status: 243, stderr: "npm ERR! code EACCES" }) }))
      .toMatchObject({ ok: false, code: "npm_permission_denied" });
  });

  it("updates the copy that runs, where it is installed: not a second one beside another node (two on one Mac)", async () => {
    const root = mkdtempSync(join(tmpdir(), "ps-prefix-"));
    try {
      // Homebrew's or fnm's layout: <prefix>/lib/node_modules/papersearch, its command in <prefix>/bin.
      mkdirSync(join(root, "lib", "node_modules", "papersearch"), { recursive: true });
      mkdirSync(join(root, "bin"));
      writeFileSync(join(root, "bin", "paper-search"), "");
      expect(globalPrefixOf(join(root, "lib", "node_modules", "papersearch"), "darwin")).toBe(root);
      // Windows: <prefix>\node_modules\papersearch beside <prefix>\paper-search.cmd.
      mkdirSync(join(root, "win", "node_modules", "papersearch"), { recursive: true });
      writeFileSync(join(root, "win", "paper-search.cmd"), "");
      expect(globalPrefixOf(join(root, "win", "node_modules", "papersearch"), "win32")).toBe(join(root, "win"));
      // A checkout, or a project's own node_modules: no prefix, npm's own place as before.
      expect(globalPrefixOf(root, "darwin")).toBe("");
      mkdirSync(join(root, "project", "node_modules", "papersearch"), { recursive: true });
      expect(globalPrefixOf(join(root, "project", "node_modules", "papersearch"), "darwin")).toBe("");
      const runs: string[][] = [];
      await installSelf({ ok: true, source: "npm", current: "0.7.2", latest: "0.7.3", update: true, releaseNotesUrl: "" },
        { source: { kind: "npm" }, npm: ["node", "npm-cli.js"], prefix: root, run: (argv) => { runs.push(argv); return { status: 0, stderr: "" }; } });
      expect(runs[0]).toEqual(["node", "npm-cli.js", "install", "-g", "--prefix", root, "--no-audit", "--no-fund", "papersearch@0.7.3"]);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("finds each PaperSearch copy on the PATH once, and doctor says when there is more than one", () => {
    const root = mkdtempSync(join(tmpdir(), "ps-copies-"));
    try {
      const copy = (prefix: string, version: string) => {
        const pkg = join(root, prefix, "lib", "node_modules", "papersearch");
        mkdirSync(join(pkg, "dist"), { recursive: true });
        writeFileSync(join(pkg, "package.json"), JSON.stringify({ name: "papersearch", version, bin: { "paper-search": "dist/cli.js" } }));
        writeFileSync(join(pkg, "dist", "cli.js"), "");
        mkdirSync(join(root, prefix, "bin"));
        symlinkSync(join(pkg, "dist", "cli.js"), join(root, prefix, "bin", "paper-search"));
      };
      copy("fnm", "0.7.1-preview.1");
      copy("brew", "0.7.2-preview.5");
      // fnm's shell links to its node's bin: the same copy found twice counts once.
      symlinkSync(join(root, "fnm", "bin"), join(root, "shell-bin"));
      // Another program's paper-search is not PaperSearch.
      mkdirSync(join(root, "other", "bin"), { recursive: true });
      writeFileSync(join(root, "other", "bin", "paper-search"), "");
      const path = [join(root, "shell-bin"), join(root, "fnm", "bin"), join(root, "other", "bin"), join(root, "brew", "bin")].join(":");
      const copies = installedCopies(path, "darwin");
      const real = (prefix: string) => realpathSync(join(root, prefix, "lib", "node_modules", "papersearch"));
      expect(copies).toEqual([{ command: join(root, "shell-bin", "paper-search"), version: "0.7.1-preview.1", root: real("fnm") },
        { command: join(root, "brew", "bin", "paper-search"), version: "0.7.2-preview.5", root: real("brew") }]);
      const text = renderDoctorTextReport({ config: { path: "/c", configured: 0, missing: [], entries: [] },
        capabilityProfile: { entries: [] } as never, platformStatus: {}, copies });
      expect(text).toContain("PaperSearch copies on the PATH: 2");
      expect(text).toContain(`0.7.1-preview.1  ${real("fnm")}`);
      expect(renderDoctorTextReport({ config: { path: "/c", configured: 0, missing: [], entries: [] },
        capabilityProfile: { entries: [] } as never, platformStatus: {}, copies: copies.slice(1) })).not.toContain("copies on the PATH");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("finds node's own npm", () => {
    const found = npmCommand();
    expect(found.length === 2 ? readFileSync(found[1], "utf8").length > 0 : ["npm", "npm.cmd"].includes(found[0])).toBe(true);
  });
});
