import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { dirname, join } from "path";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";
import { runUninstall, uninstallPlan } from "../../src/management/uninstall/index.js";

// Everything PaperSearch keeps on the computer, removed in one go (user, 2026-11-11).
describe("paper-search uninstall", () => {
  let home: string;
  const at = (...parts: string[]) => join(home, ...parts);
  const write = (path: string, text = "x") => {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, text);
  };
  const skill = (folder: string, name = "paper-search") => write(join(folder, "SKILL.md"), `---\nname: ${name}\ndescription: test\n---\n`);
  const gone = (path: string) => {
    try {
      lstatSync(path);
      return false;
    } catch {
      return true;
    }
  };

  beforeEach(() => {
    home = mkdtempSync(join(tmpdir(), "paper-search-uninstall-"));
    write(at(".local", "share", "paper-search-cli", "carsi-runtime", "venv", "python"));
    write(at(".local", "share", "paper-search-cli", "carsi", "browser_profiles", "Cookies"));
    write(at(".local", "share", "paper-search-cli", "runs", "1", "run.json"));
    write(at(".local", "share", "paper-search-cli", "skill-sync.json"));
    write(at(".config", "paper-search-cli", "config.json"), '{"EASYSCHOLAR_KEY":"k"}');
    skill(at(".agents", "skills", "paper-search"));
    skill(at(".agents", "skills", "other"), "other");
    // npx skills: Claude Code's copy is a link to the shared one.
    mkdirSync(at(".claude", "skills"), { recursive: true });
    symlinkSync(at(".agents", "skills", "paper-search"), at(".claude", "skills", "paper-search"));
    skill(at(".codex", "skills", "paper-search"));
    skill(at(".gemini", "antigravity", "skills", "paper-search"));
    // Another tool reaching the shared folder through a linked parent (Windows: .claude\skills).
    mkdirSync(at(".qwen"), { recursive: true });
    symlinkSync(at(".agents", "skills"), at(".qwen", "skills"));
    // A link left behind when its folder went, and someone else's Skill of a similar name.
    mkdirSync(at(".kimi", "skills"), { recursive: true });
    symlinkSync(at("gone", "paper-search"), at(".kimi", "skills", "paper-search"));
    skill(at(".cursor", "skills", "paper-search"), "paper-search-cli-debug");
    write(at(".agents", ".skill-lock.json"), JSON.stringify({ version: 3, skills: { "paper-search": { source: "dr-dumpling/PaperSearch" }, qa: { source: "x" } } }));
    write(at("Downloads", "papers", "a.pdf"));
  });

  afterEach(() => rmSync(home, { recursive: true, force: true }));

  it("lists PaperSearch's data, config, every copy of the Skill once and its lock entry; nothing else", () => {
    const plan = uninstallPlan({}, home, { downloads: at("Downloads", "papers") });
    const listed = plan.items.map((item) => [item.path, item.kind]).sort();
    expect(listed).toEqual([
      [at(".agents", ".skill-lock.json"), "entry"],
      [at(".agents", "skills", "paper-search"), "folder"],
      [at(".claude", "skills", "paper-search"), "link"],
      [at(".codex", "skills", "paper-search"), "folder"],
      [at(".config", "paper-search-cli"), "folder"],
      [at(".gemini", "antigravity", "skills", "paper-search"), "folder"],
      [at(".kimi", "skills", "paper-search"), "link"],
      [at(".local", "share", "paper-search-cli"), "folder"],
    ].sort());
    const data = plan.items.find((item) => item.path === at(".local", "share", "paper-search-cli"))!;
    expect(data.label).toBe("数据（学校订阅下载程序、学校设置和登录状态、运行记录、其他记录）");
    expect(plan.kept[0]).toBe(`下载的论文：${at("Downloads", "papers")}`);
    expect(plan.kept.at(-1)).toContain("npm uninstall -g papersearch");
    // Listing changes nothing.
    expect(existsSync(at(".config", "paper-search-cli", "config.json"))).toBe(true);
  });

  it("removes what it listed, links without what they point to, and leaves the rest", () => {
    const result = runUninstall(uninstallPlan({}, home));
    expect(result.failed).toEqual([]);
    for (const path of [at(".local", "share", "paper-search-cli"), at(".config", "paper-search-cli"),
      at(".agents", "skills", "paper-search"), at(".claude", "skills", "paper-search"), at(".codex", "skills", "paper-search"),
      at(".gemini", "antigravity", "skills", "paper-search"), at(".kimi", "skills", "paper-search")]) {
      expect(gone(path)).toBe(true);
    }
    expect(existsSync(at(".agents", "skills", "other", "SKILL.md"))).toBe(true);
    expect(existsSync(at(".cursor", "skills", "paper-search", "SKILL.md"))).toBe(true);
    expect(lstatSync(at(".qwen", "skills")).isSymbolicLink()).toBe(true);
    expect(existsSync(at("Downloads", "papers", "a.pdf"))).toBe(true);
    expect(JSON.parse(readFileSync(at(".agents", ".skill-lock.json"), "utf8"))).toEqual({ version: 3, skills: { qa: { source: "x" } } });
    expect(uninstallPlan({}, home).items).toEqual([]);
  });

  it("takes only the config file when its place was set by hand", () => {
    write(at("shared", "my-config.json"), "{}");
    write(at("shared", "notes.txt"));
    const plan = uninstallPlan({ PAPER_SEARCH_CONFIG_FILE: at("shared", "my-config.json") }, home);
    expect(plan.items.filter((item) => item.label.startsWith("配置"))).toEqual([
      expect.objectContaining({ path: at("shared", "my-config.json"), kind: "file" })]);
    runUninstall(plan);
    expect(existsSync(at("shared", "my-config.json"))).toBe(false);
    expect(existsSync(at("shared", "notes.txt"))).toBe(true);
    // The default folder is left to its own: it was not where this config lived.
    expect(existsSync(at(".config", "paper-search-cli", "config.json"))).toBe(true);
  });

  it("lists run records kept elsewhere", () => {
    write(at("records", "runs", "1", "run.json"));
    const plan = uninstallPlan({ PAPER_SEARCH_RUNLOG_DIR: at("records", "runs") }, home);
    expect(plan.items).toContainEqual(expect.objectContaining({ label: "运行记录", path: at("records", "runs") }));
  });
});
