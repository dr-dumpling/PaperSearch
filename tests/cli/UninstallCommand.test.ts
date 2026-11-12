import { spawnSync } from "child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";

describe("paper-search uninstall (command)", () => {
  let tempRoot: string;
  const data = () => join(tempRoot, "data", "paper-search-cli");

  beforeEach(() => {
    tempRoot = mkdtempSync(join(tmpdir(), "paper-search-uninstall-cli-"));
    mkdirSync(join(data(), "school"), { recursive: true });
    writeFileSync(join(data(), "school", "access.json"), "{}");
    writeFileSync(join(tempRoot, "config.json"), '{"DEFAULT_DOWNLOAD_PATH":"/papers"}');
    mkdirSync(join(tempRoot, ".agents", "skills", "paper-search"), { recursive: true });
    writeFileSync(join(tempRoot, ".agents", "skills", "paper-search", "SKILL.md"), "---\nname: paper-search\n---\n");
  });

  afterEach(() => rmSync(tempRoot, { recursive: true, force: true }));

  it("lists first, asks, and removes only once the user agrees", () => {
    const planned = runCli(["uninstall", "--dry-run"]);
    expect(planned.status).toBe(0);
    const plan = JSON.parse(planned.stdout);
    expect(plan.status).toBe("planned");
    // Never anything outside the temporary home in this test.
    expect(plan.items.length).toBe(3);
    for (const item of plan.items) expect(item.path.startsWith(tempRoot)).toBe(true);
    expect(plan.kept[0]).toBe("下载的论文：/papers");
    expect(plan.next).toBe("npm uninstall -g papersearch");

    const refused = runCli(["uninstall"], "n\n");
    expect(refused.status).toBe(1);
    expect(JSON.parse(refused.stdout).status).toBe("cancelled");
    expect(refused.stderr).toContain("将要删除 PaperSearch 的以下内容");
    expect(existsSync(data())).toBe(true);

    const done = runCli(["uninstall", "--yes", "--format", "text"]);
    expect(done.status).toBe(0);
    expect(done.stdout).toContain("已删除 PaperSearch 的数据、配置和 Skill。");
    expect(done.stdout).toContain("最后运行 npm uninstall -g papersearch");
    for (const path of [data(), join(tempRoot, "config.json"), join(tempRoot, ".agents", "skills", "paper-search")]) {
      expect(existsSync(path)).toBe(false);
    }
    expect(JSON.parse(runCli(["uninstall", "--dry-run"]).stdout).status).toBe("nothing");
  });

  it("still lists a broken config file, which goes with the rest", () => {
    writeFileSync(join(tempRoot, "config.json"), "{broken");
    const planned = runCli(["uninstall", "--dry-run"]);
    expect(planned.status).toBe(0);
    expect(JSON.parse(planned.stdout).items.map((item: { path: string }) => item.path)).toContain(join(tempRoot, "config.json"));
  });

  function runCli(args: string[], input = "") {
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      // A temporary home: never the user's skills, data or config.
      HOME: tempRoot,
      USERPROFILE: tempRoot,
      XDG_DATA_HOME: join(tempRoot, "data"),
      PAPER_SEARCH_CONFIG_FILE: join(tempRoot, "config.json"),
    };
    for (const key of ["PAPER_SEARCH_CONFIG_DIR", "PAPER_SEARCH_RUNLOG_DIR", "PAPER_SEARCH_RUNLOG", "DEFAULT_DOWNLOAD_PATH"]) delete env[key];
    return spawnSync(process.execPath, [join(process.cwd(), "node_modules/.bin/tsx"), "src/cli.ts", ...args], {
      cwd: process.cwd(), input, env, encoding: "utf8",
    });
  }
});
