import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "@jest/globals";
import {
  InstallError,
  installCarsi,
  carsiStatus,
  renderStatusText,
  uninstallCarsi,
  updateCarsi,
  type CommandResult,
  type InstallContext,
  type InstallerHost,
  type InstallOptions,
} from "../../src/management/carsi/installer.js";
import { UV_ARCHIVES } from "../../src/management/carsi/runtime.js";

const ARCHIVE = UV_ARCHIVES["darwin-arm64"];

interface Fake {
  host: InstallerHost;
  calls: string[];
  config: Record<string, string>;
  context: InstallContext;
  root: string;
  logs: string[];
  /** The user's Google Chrome (in ~/Applications, so the machine running the test does not matter). */
  chrome: string;
  /** Where an install from before Chrome left its Camoufox build. */
  camoufoxDir: string;
}

const CHROME_CHECK = { browser: "Google Chrome", version: "156.0.8078.81", tested: "156.0.8078.80", outdated: false,
  driver: "patchright 1.64.4" };

/** A Mac without uv: every command answers as a working install would. */
function fakeMachine(overrides: {
  platform?: NodeJS.Platform;
  respond?: (command: string, args: string[]) => CommandResult | undefined;
  sha256?: string;
  answers?: string[];
  config?: Record<string, string>;
  notifications?: boolean;
  chrome?: Partial<typeof CHROME_CHECK>;
} = {}): Fake {
  const base = mkdtempSync(join(tmpdir(), "psc-install-"));
  const home = join(base, "home");
  const data = join(base, "data");
  const packageRoot = join(base, "package");
  mkdirSync(join(packageRoot, "carsi", "paper_search_carsi", "__pycache__"), { recursive: true });
  mkdirSync(join(packageRoot, "carsi", "tests"), { recursive: true });
  writeFileSync(join(packageRoot, "carsi", "pyproject.toml"), "[project]\nname = 'paper-search-carsi'\n");
  writeFileSync(join(packageRoot, "carsi", "paper_search_carsi", "__init__.py"), "");
  writeFileSync(join(packageRoot, "carsi", "paper_search_carsi", "__pycache__", "x.pyc"), "");
  writeFileSync(join(packageRoot, "carsi", "tests", "test_x.py"), "");
  const root = join(data, "paper-search-cli", "carsi-runtime");
  const chrome = join(home, "Applications", "Google Chrome.app", "Contents", "MacOS", "Google Chrome");
  mkdirSync(join(chrome, ".."), { recursive: true });
  writeFileSync(chrome, "");
  const camoufoxDir = join(home, "Library", "Caches", "camoufox", "browsers", "official", "156.0.1-beta.36-0ad5663e");
  const calls: string[] = [];
  const logs: string[] = [];
  const answers = [...(overrides.answers ?? ["红木兰大学"])];
  const config: Record<string, string> = { ...(overrides.config ?? {}) };
  const host: InstallerHost = {
    platform: overrides.platform ?? "darwin",
    arch: "arm64",
    home,
    env: { XDG_DATA_HOME: data },
    async run(command, args) {
      const name = command.split("/").pop()!;
      calls.push(`${name} ${args.join(" ")}`.replace(root, "<root>").replace(root, "<root>"));
      const custom = overrides.respond?.(name, args);
      if (custom) return custom;
      if (name === "paper-search-carsi" && args.join(" ") === "config get progress_notify") {
        return { code: 0, stdout: JSON.stringify({ progress_notify: overrides.notifications ?? false }), stderr: "" };
      }
      if (name === "uv" && args[0] === "--version" && command === "uv") return { code: 1, stdout: "", stderr: "not found" };
      if (name === "uv" && args[0] === "venv") {
        mkdirSync(join(args[1], "bin"), { recursive: true });
        writeFileSync(join(args[1], "bin", "python"), "");
      }
      if (name === "uv" && args[0] === "pip") {
        mkdirSync(join(root, "venv", "bin"), { recursive: true });
        writeFileSync(join(root, "venv", "bin", "paper-search-carsi"), "");
      }
      if (name === "tar") {
        const dir = join(root, "bin", "uv-aarch64-apple-darwin");
        mkdirSync(dir, { recursive: true });
        writeFileSync(join(dir, "uv"), "");
      }
      if (name === "python" && args[0] === "--version") return { code: 0, stdout: "Python 3.12.7\n", stderr: "" };
      if (name === "python" && args[1]?.includes("importlib.metadata")) return { code: 0, stdout: "0.1.0\n", stderr: "" };
      if (name === "python" && args[1]?.includes("browser_check")) {
        const found = existsSync(chrome) ? { ...CHROME_CHECK, path: chrome, ...overrides.chrome }
          : { browser: "", path: "", version: "", tested: "156.0.8078.80", outdated: false, driver: "patchright 1.64.4" };
        return { code: 0, stdout: JSON.stringify({ chrome: found, ego: "" }), stderr: "" };
      }
      if (name === "python" && args[1]?.includes("_any_institutional_configured")) {
        return { code: 0, stdout: JSON.stringify({ configured: false, school: "" }), stderr: "" };
      }
      return { code: 0, stdout: "", stderr: "" };
    },
    async download(_url, file) {
      writeFileSync(file, "archive");
    },
    sha256: async () => overrides.sha256 ?? ARCHIVE.sha256,
    freeBytes: () => 100 * 1024 ** 3,
    confirm: async () => (answers.shift() ?? "") === "y",
    ask: async () => answers.shift() ?? "",
    log: (line) => logs.push(line),
  };
  const context: InstallContext = {
    packageRoot,
    paperSearchVersion: "0.3.4",
    dataDir: join(data, "paper-search-cli", "carsi"),
    getConfig: (key) => config[key] ?? "",
    setConfig: (key, value) => {
      config[key] = value;
    },
    unsetConfig: (key) => {
      delete config[key];
    },
    readiness: async () => ({ state: "available" }),
    now: () => new Date("2026-11-01T15:00:00Z"),
  };
  return { host, calls, config, context, root, logs, chrome, camoufoxDir };
}

const YES: InstallOptions = { browser: "chrome", yes: true, force: false, skipSchool: false };

/** An install finished by an earlier PaperSearch with Camoufox (before ADR 0016). */
function legacyInstall(m: Fake): void {
  mkdirSync(join(m.root, "venv", "bin"), { recursive: true });
  writeFileSync(join(m.root, "venv", "bin", "python"), "");
  writeFileSync(join(m.root, "venv", "bin", "paper-search-carsi"), "");
  mkdirSync(m.camoufoxDir, { recursive: true });
  writeFileSync(join(m.root, "install.json"), JSON.stringify({
    schema: 1, paperSearchVersion: "0.3.3", browser: "camoufox", startedAt: "2026-11-01T10:00:00.000Z",
    finishedAt: "2026-11-01T10:30:00.000Z", uv: "uv", python: "Python 3.12.7", backend: "0.1.0",
    camoufoxBrowser: "156.0.1-beta.36-0ad5663e", school: "红木兰大学", notifications: false,
    steps: Object.fromEntries(["preflight", "uv", "python", "backend", "browser", "config", "school", "notifications", "check"]
      .map((step) => [step, "2026-11-01T10:00:00.000Z"])),
  }));
  m.config.PAPER_SEARCH_CARSI_EXECUTABLE = join(m.root, "venv", "bin", "paper-search-carsi");
  m.config.PAPER_SEARCH_CARSI_ENABLED = "true";
}

describe("paper-search carsi install", () => {
  it.each([
    { answer: "y", previous: false, expected: true },
    { answer: "n", previous: true, expected: false },
    { answer: "", previous: true, expected: true },
    { answer: "", previous: false, expected: false },
  ])("records the notification choice $answer without forcing it on", async ({ answer, previous, expected }) => {
    const m = fakeMachine({ answers: ["示例大学", answer], notifications: previous });
    const result = await installCarsi(m.host, YES, m.context);
    expect(result.record?.notifications).toBe(expected);
    const writes = m.calls.filter(call => call.includes("config set progress_notify"));
    expect(writes).toEqual(answer ? [`paper-search-carsi config set progress_notify ${expected}`] : []);
    const before = [...m.calls];
    expect((await installCarsi(m.host, YES, m.context)).status).toBe("already_installed");
    expect(m.calls).toEqual(before);
  });

  it("rejects invalid notification choices instead of treating them as consent", async () => {
    const m = fakeMachine({ answers: ["示例大学", "maybe", "y"] });
    expect((await installCarsi(m.host, YES, m.context)).record?.notifications).toBe(true);
    expect(m.logs).toContain("请输入 y（开启）或 n（关闭），也可以回车保留当前设置。");
  });

  it("installs step by step and records each step", async () => {
    const m = fakeMachine();
    const outcome = await installCarsi(m.host, YES, m.context);
    expect(outcome.status).toBe("installed");
    expect(m.calls).toEqual([
      "uv --version",
      "tar -xzf <root>/bin/uv-aarch64-apple-darwin.tar.gz -C <root>/bin",
      "uv --version",
      "uv python install 3.12",
      "uv venv <root>/venv --python 3.12",
      "python --version",
      "uv pip install --python <root>/venv/bin/python <root>/src[ego]",
      expect.stringMatching(/^python -c import importlib\.metadata/),
      expect.stringMatching(/^python -c import json\nfrom paper_search_carsi\.browser/),
      "paper-search-carsi config set browser_backend chrome",
      expect.stringMatching(/^python -c import json\nfrom paper_search_carsi\.config/),
      "paper-search-carsi setup --carsi --institution 红木兰大学",
      "paper-search-carsi config get progress_notify",
      "python -c import tkinter",
    ]);
    const record = JSON.parse(readFileSync(join(m.root, "install.json"), "utf8"));
    expect(Object.keys(record.steps)).toEqual(["preflight", "uv", "python", "backend", "browser", "config", "school", "notifications", "check"]);
    expect(record).toMatchObject({
      browser: "chrome", python: "Python 3.12.7", backend: "0.1.0", chrome: { path: m.chrome, version: "156.0.8078.81" },
      school: "红木兰大学", finishedAt: "2026-11-01T15:00:00.000Z",
    });
    expect(record.camoufoxBrowser).toBeUndefined();
    expect(m.logs).toContain("== 检查 Google Chrome");
    expect(m.logs).toContain(`  Google Chrome 156.0.8078.81：${m.chrome}；patchright 1.64.4`);
    expect(m.config).toEqual({
      PAPER_SEARCH_CARSI_EXECUTABLE: join(m.root, "venv", "bin", "paper-search-carsi"),
      PAPER_SEARCH_CARSI_ENABLED: "true",
    });
    // The backend is built from a copy, without caches or tests.
    expect(existsSync(join(m.root, "src", "pyproject.toml"))).toBe(true);
    expect(existsSync(join(m.root, "src", "tests"))).toBe(false);
    expect(existsSync(join(m.root, "src", "paper_search_carsi", "__pycache__"))).toBe(false);
    expect(existsSync(join(m.root, "bin", "uv-aarch64-apple-darwin.tar.gz"))).toBe(false);
    expect(readFileSync(join(m.root, "install.log"), "utf8")).toContain("uv python install 3.12\n");
    // Installed: a second run changes nothing.
    m.calls.length = 0;
    expect((await installCarsi(m.host, YES, m.context)).status).toBe("already_installed");
    expect(m.calls).toEqual([]);
  });

  it("continues from the step that failed", async () => {
    let failing = true;
    const m = fakeMachine({
      respond: (name, args) => (name === "uv" && args[0] === "pip" && failing
        ? { code: 1, stdout: "", stderr: "error: network unreachable" } : undefined),
    });
    await expect(installCarsi(m.host, YES, m.context)).rejects.toMatchObject({
      name: "InstallError", step: "backend", message: "安装后端和依赖失败：error: network unreachable",
    });
    const record = JSON.parse(readFileSync(join(m.root, "install.json"), "utf8"));
    expect(Object.keys(record.steps)).toEqual(["preflight", "uv", "python"]);
    failing = false;
    m.calls.length = 0;
    expect((await installCarsi(m.host, YES, m.context)).status).toBe("installed");
    expect(m.calls[0]).toBe("uv pip install --python <root>/venv/bin/python <root>/src[ego]");
    expect(m.calls).not.toContain("uv python install 3.12");
  });

  it("refuses a uv archive whose checksum differs", async () => {
    const m = fakeMachine({ sha256: "0".repeat(64) });
    const error = await installCarsi(m.host, YES, m.context).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(InstallError);
    expect((error as InstallError).step).toBe("uv");
    expect(existsSync(join(m.root, "bin", ARCHIVE.file))).toBe(false);
    expect(m.calls).not.toContain("tar -xzf <root>/bin/uv-aarch64-apple-darwin.tar.gz -C <root>/bin");
  });

  it("needs Google Chrome and says where to get it", async () => {
    const m = fakeMachine({ platform: "win32" });
    m.host.env = { ...m.host.env, PROGRAMFILES: join(m.host.home, "Program Files"), LOCALAPPDATA: join(m.host.home, "AppData") };
    const missing = `没有找到 Google Chrome：请先从 https://www.google.com/chrome/ 安装 Chrome，再运行 paper-search carsi install`;
    await expect(installCarsi(m.host, YES, m.context)).rejects.toMatchObject({ step: "preflight", message: missing });
    expect(m.calls).toEqual([]);
    // Installed at the usual place, or where the backend's chrome_executable says.
    const chrome = join(m.host.home, "AppData", "Google", "Chrome", "Application", "chrome.exe");
    mkdirSync(join(chrome, ".."), { recursive: true });
    writeFileSync(chrome, "");
    await expect(installCarsi(m.host, YES, m.context)).rejects.not.toMatchObject({ step: "preflight" });
    const elsewhere = fakeMachine({ platform: "win32" });
    elsewhere.host.env = { ...elsewhere.host.env, PROGRAMFILES: join(elsewhere.host.home, "none") };
    mkdirSync(elsewhere.context.dataDir, { recursive: true });
    writeFileSync(join(elsewhere.context.dataDir, "config.json"), JSON.stringify({ chrome_executable: elsewhere.chrome }));
    await expect(installCarsi(elsewhere.host, YES, elsewhere.context)).rejects.not.toMatchObject({ step: "preflight" });
  });

  it("stops at the browser step when the backend finds no Chrome, and reports an old one", async () => {
    const m = fakeMachine({ chrome: { version: "155.0.7000.1", outdated: true } });
    const outcome = await installCarsi(m.host, YES, m.context);
    expect(outcome.status).toBe("installed");
    const outdated = "Google Chrome 155.0.7000.1 低于测试过的 156.0.8078.80：请先更新 Chrome（菜单 → 帮助 → 关于 Google Chrome）";
    expect(m.logs).toContain(`  注意：${outdated}`);
    const status = await carsiStatus(m.host, m.context);
    expect(status.notes).toContain(outdated);
    expect(renderStatusText(status)).toContain(`  Google Chrome：155.0.7000.1（${m.chrome}；测试过的版本 156.0.8078.80）`);
    expect(renderStatusText(status)).toContain("  驱动：patchright 1.64.4");
    const gone = fakeMachine();
    const run = gone.host.run;
    gone.host.run = async (command, args, options) => {
      if (args[0] === "-c" && args[1]?.includes("browser_check")) rmSync(gone.chrome, { force: true });
      return run(command, args, options);
    };
    await expect(installCarsi(gone.host, YES, gone.context)).rejects.toMatchObject({
      step: "browser", message: "没有找到 Google Chrome：请先从 https://www.google.com/chrome/ 安装 Chrome，再运行 paper-search carsi install",
    });
  });

  it("writes nothing when the user does not confirm", async () => {
    const m = fakeMachine({ answers: ["n"] });
    expect((await installCarsi(m.host, { ...YES, yes: false }, m.context)).status).toBe("cancelled");
    expect(existsSync(m.root)).toBe(false);
    expect(m.logs[0]).toBe("将要安装 PaperSearch 学校订阅下载（CARSI）：");
  });

  it("offers ego lite only on macOS, and only when it is there", async () => {
    const linux = fakeMachine({ platform: "linux" });
    await expect(installCarsi(linux.host, { ...YES, browser: "ego" }, linux.context))
      .rejects.toMatchObject({ step: "preflight", message: "ego lite 目前只支持 macOS；请用 --browser chrome" });
    const mac = fakeMachine();
    await expect(installCarsi(mac.host, { ...YES, browser: "ego" }, mac.context))
      .rejects.toMatchObject({ step: "preflight" });
    mkdirSync(join(mac.host.home, "Applications", "ego lite.app"), { recursive: true });
    mac.calls.length = 0;
    expect((await installCarsi(mac.host, { ...YES, browser: "ego" }, mac.context)).status).toBe("installed");
    expect(mac.calls).toContain("uv pip install --python <root>/venv/bin/python <root>/src[ego]");
    expect(mac.logs).toContain("== 检测 ego lite");
    expect(mac.calls).toContain("paper-search-carsi config set browser_backend ego");
    expect(renderStatusText(await carsiStatus(mac.host, mac.context))).toContain("  浏览器：ego lite");
  });

  it("asks before replacing another configured backend", async () => {
    const m = fakeMachine({
      answers: ["y", "n", ""],
      config: { PAPER_SEARCH_CARSI_EXECUTABLE: "/repo/carsi/bin/paper-search-carsi" },
    });
    const outcome = await installCarsi(m.host, { ...YES, yes: false }, m.context);
    expect(outcome.status).toBe("installed");
    expect(m.config.PAPER_SEARCH_CARSI_EXECUTABLE).toBe("/repo/carsi/bin/paper-search-carsi");
    // No school given and no institutional access yet: CARSI is turned on, the school left to the chooser.
    expect(m.calls).toContain("paper-search-carsi setup --carsi");
    expect(outcome.record?.warnings).toEqual([
      "保留原来的后端配置：/repo/carsi/bin/paper-search-carsi",
      "还没有配置学校：机构登录时需要你在选校页自己选",
    ]);
  });

  it("does not ask to start again once setup confirmed it, but still asks before replacing a backend", async () => {
    const m = fakeMachine({
      answers: ["n", ""],
      config: { PAPER_SEARCH_CARSI_EXECUTABLE: "/repo/carsi/bin/paper-search-carsi" },
    });
    const outcome = await installCarsi(m.host, { ...YES, yes: false, confirmed: true }, m.context);
    expect(outcome.status).toBe("installed");
    expect(m.config.PAPER_SEARCH_CARSI_EXECUTABLE).toBe("/repo/carsi/bin/paper-search-carsi");
  });

  it("lets the user pick one of several CARSI schools, saved by its entityID", async () => {
    const candidates = [
      { name: "示例大学", name_en: "Example University", domain: "example.edu.cn", entity_id: "https://idp.example.edu.cn/idp/shibboleth" },
      { name: "示例师范大学", name_en: "Example Normal University", domain: "example-normal.edu.cn", entity_id: "https://idp.example-normal.edu.cn/idp/shibboleth" },
    ];
    const m = fakeMachine({
      answers: ["示例", "2"],
      respond: (name, args) => {
        if (name !== "paper-search-carsi" || args[0] !== "setup" || args[1] !== "--carsi" || !args[3]) return undefined;
        if (args[3] === "示例") return { code: 1, stdout: JSON.stringify({ error: "carsi_school_ambiguous", count: 2, candidates }), stderr: "" };
        return { code: 0, stdout: JSON.stringify({ updated: true, settings: { carsi_institution_hint: "示例师范大学" } }), stderr: "" };
      },
    });
    const outcome = await installCarsi(m.host, YES, m.context);
    expect(outcome.record?.school).toBe("示例师范大学");
    expect(m.calls).toContain("paper-search-carsi setup --carsi --institution https://idp.example-normal.edu.cn/idp/shibboleth");
    expect(m.logs).toContain("  2. 示例师范大学（Example Normal University，example-normal.edu.cn）");
  });

  it("asks again for a school that is not a CARSI member, and stops on an unreachable list", async () => {
    const m = fakeMachine({
      answers: ["Nowhere", "示例大学"],
      respond: (name, args) => {
        if (name !== "paper-search-carsi" || args[0] !== "setup" || !args[3]) return undefined;
        return args[3] === "Nowhere"
          ? { code: 1, stdout: JSON.stringify({ error: "carsi_school_not_found", query: "Nowhere" }), stderr: "" }
          : { code: 0, stdout: JSON.stringify({ settings: { carsi_institution_hint: "示例大学" } }), stderr: "" };
      },
    });
    expect((await installCarsi(m.host, YES, m.context)).record?.school).toBe("示例大学");
    const offline = fakeMachine({
      respond: (name, args) => (name === "paper-search-carsi" && args[0] === "setup" && args[3]
        ? { code: 1, stdout: JSON.stringify({ error: "carsi_school_list_unavailable", detail: "ConnectionError: timed out" }), stderr: "" }
        : undefined),
    });
    await expect(installCarsi(offline.host, YES, offline.context)).rejects.toMatchObject({
      step: "school", message: "取不到 CARSI 学校列表（ConnectionError: timed out）：稍后再运行本命令，或加 --skip-school 先跳过",
    });
  });

  it("reports an install that has not finished", async () => {
    const m = fakeMachine({ respond: (name) => (name === "tar" ? { code: 1, stdout: "", stderr: "bad archive" } : undefined) });
    await installCarsi(m.host, YES, m.context).catch(() => undefined);
    const status = await carsiStatus(m.host, m.context);
    expect(status).toMatchObject({ installed: true, complete: false });
    expect(renderStatusText(status)).toContain("→ 安装没有完成（1/9 步）：再运行 paper-search carsi install 接着装");
  });

  it("updates the backend after PaperSearch moved on, and only then", async () => {
    const m = fakeMachine();
    await installCarsi(m.host, YES, m.context);
    m.calls.length = 0;
    expect((await updateCarsi(m.host, { force: false }, m.context)).status).toBe("up_to_date");
    expect(m.calls).toEqual([]);
    m.context.paperSearchVersion = "0.3.5";
    expect(renderStatusText(await carsiStatus(m.host, m.context)))
      .toContain("→ PaperSearch 已是 0.3.5，扩展是 0.3.4 时装的：运行 paper-search carsi update");
    m.calls.length = 0;
    const outcome = await updateCarsi(m.host, { force: false }, m.context);
    expect(outcome.status).toBe("updated");
    expect(m.calls).toEqual([
      "uv pip install --python <root>/venv/bin/python --reinstall-package paper-search-carsi <root>/src[ego]",
      expect.stringMatching(/^python -c import importlib\.metadata/),
      expect.stringMatching(/^python -c import json\nfrom paper_search_carsi\.browser/),
      "python -c import tkinter",
    ]);
    expect(outcome.record).toMatchObject({ paperSearchVersion: "0.3.5", updatedAt: "2026-11-01T15:00:00.000Z", school: "红木兰大学" });
    // Not installed: nothing to update.
    const fresh = fakeMachine();
    await expect(updateCarsi(fresh.host, { force: false }, fresh.context))
      .rejects.toMatchObject({ step: "update", message: "还没有装好：先运行 paper-search carsi install" });
  });

  it("uninstalls, keeping Chrome and the user's data unless asked", async () => {
    const m = fakeMachine();
    await installCarsi(m.host, YES, m.context);
    mkdirSync(m.context.dataDir, { recursive: true });
    const kept = await uninstallCarsi(m.host, { yes: false, removeData: false },
      { ...m.context, now: m.context.now });
    expect(kept.status).toBe("cancelled");
    expect(existsSync(m.root)).toBe(true);
    // Confirmed, then "no" to the data.
    const answers = ["y", "n"];
    m.host.confirm = async () => answers.shift() === "y";
    const outcome = await uninstallCarsi(m.host, { yes: false, removeData: false }, m.context);
    expect(outcome.status).toBe("uninstalled");
    expect(existsSync(m.root)).toBe(false);
    expect(m.config).toEqual({});
    expect(existsSync(m.chrome)).toBe(true);
    expect(existsSync(m.context.dataDir)).toBe(true);
    expect(outcome.kept).toEqual([m.context.dataDir]);
    expect(m.logs).toContain("  Google Chrome 是你自己的浏览器，不受影响");
    expect((await uninstallCarsi(m.host, { yes: true, removeData: false }, m.context)).status)
      .toBe("not_installed");
  });

  it("removes the data only when told to", async () => {
    const m = fakeMachine();
    await installCarsi(m.host, YES, m.context);
    mkdirSync(m.context.dataDir, { recursive: true });
    const outcome = await uninstallCarsi(m.host, { yes: true, removeData: true }, m.context);
    expect(outcome.removed).toEqual([m.root, expect.stringContaining("PAPER_SEARCH_CARSI_ENABLED"), m.context.dataDir]);
    expect([m.root, m.context.dataDir, m.chrome].map((path) => existsSync(path))).toEqual([false, false, true]);
  });

  it("moves a Camoufox install to Chrome on update, leaving the old build for the user", async () => {
    const m = fakeMachine();
    legacyInstall(m);
    const before = await carsiStatus(m.host, m.context);
    expect(before.notes).toContain("机构下载已改用 Google Chrome，不再用 Camoufox：运行 paper-search carsi update");
    expect(renderStatusText(before)).toContain("  浏览器：camoufox（已停用，运行 paper-search carsi update 改用 Google Chrome）");
    m.calls.length = 0;
    const outcome = await updateCarsi(m.host, { force: false }, m.context);
    expect(outcome.status).toBe("updated");
    expect(m.calls).toEqual([
      "uv python install 3.12",
      "uv venv <root>/venv --python 3.12",
      "python --version",
      "uv pip install --python <root>/venv/bin/python --reinstall-package paper-search-carsi <root>/src[ego]",
      expect.stringMatching(/^python -c import importlib\.metadata/),
      expect.stringMatching(/^python -c import json\nfrom paper_search_carsi\.browser/),
      "python -c import tkinter",
    ]);
    const note = `以前下载的 Camoufox 浏览器不再使用，可以手动删除：${m.camoufoxDir}（本机其他用 Camoufox 的程序可能也在用）`;
    expect(outcome.record).toMatchObject({ browser: "chrome", chrome: { path: m.chrome, version: "156.0.8078.81" },
      warnings: [note], school: "红木兰大学" });
    expect(outcome.record.camoufoxBrowser).toBeUndefined();
    expect(existsSync(m.camoufoxDir)).toBe(true);
    const after = renderStatusText(await carsiStatus(m.host, m.context));
    expect(after).toContain("  浏览器：Google Chrome");
    expect(after).toContain(`  注意：${note}`);
  });

  it("installs again from Python on when an old Camoufox install is installed over", async () => {
    const m = fakeMachine({ answers: [""] });
    legacyInstall(m);
    m.calls.length = 0;
    expect((await installCarsi(m.host, YES, m.context)).status).toBe("installed");
    expect(m.calls.slice(0, 3)).toEqual(["uv python install 3.12", "uv venv <root>/venv --python 3.12", "python --version"]);
    expect(m.calls).toContain("paper-search-carsi config set browser_backend chrome");
    expect(m.calls).not.toContain("uv --version");
    const record = JSON.parse(readFileSync(join(m.root, "install.json"), "utf8"));
    expect(record).toMatchObject({ browser: "chrome", school: "红木兰大学" });
    expect(record.camoufoxBrowser).toBeUndefined();
    // The old build is named when the extension goes, never deleted.
    const outcome = await uninstallCarsi(m.host, { yes: true, removeData: false }, m.context);
    expect(outcome.kept).not.toContain(m.camoufoxDir);
    expect(existsSync(m.camoufoxDir)).toBe(true);
  });

  it("names an old Camoufox build on uninstall without deleting it", async () => {
    const m = fakeMachine();
    legacyInstall(m);
    const outcome = await uninstallCarsi(m.host, { yes: true, removeData: false }, m.context);
    expect(outcome.status).toBe("uninstalled");
    expect(outcome.kept).toContain(m.camoufoxDir);
    expect(existsSync(m.camoufoxDir)).toBe(true);
    expect(m.logs).toContain(`  以前下载的 Camoufox 浏览器（${m.camoufoxDir}）：不再使用，这里不删，可以手动删除`);
  });

  it("leaves another configured backend alone when uninstalling", async () => {
    const m = fakeMachine();
    await installCarsi(m.host, YES, m.context);
    m.config.PAPER_SEARCH_CARSI_EXECUTABLE = "/repo/carsi/bin/paper-search-carsi";
    const outcome = await uninstallCarsi(m.host, { yes: true, removeData: false }, m.context);
    expect(m.config).toEqual({
      PAPER_SEARCH_CARSI_EXECUTABLE: "/repo/carsi/bin/paper-search-carsi",
      PAPER_SEARCH_CARSI_ENABLED: "true",
    });
    expect(outcome.kept[0]).toBe("PaperSearch 配置（后端：/repo/carsi/bin/paper-search-carsi）");
  });
});
