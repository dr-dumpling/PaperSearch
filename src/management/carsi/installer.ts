import {
  appendFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import {
  camoufoxBuildDir,
  CHROME_DOWNLOAD_URL,
  chromeCandidates,
  egoAppCandidates,
  hasScreen,
  NO_SCREEN,
  PYTHON_VERSION,
  runtimePaths,
  runtimeRoot,
  UV_ARCHIVES,
  uvArchiveUrl,
  UV_VERSION,
  type RuntimePaths,
} from "./runtime.js";

/**
 * `paper-search carsi install / status` (ADR 0013, plan in
 * docs/history/institutional-installer-2026-11-03.zh.md). Every step is recorded in
 * install.json as it completes; running install again continues from the
 * step that failed. Everything outside the process goes through the host, so
 * tests run the steps without network, downloads or windows.
 */
export type InstallBrowser = "chrome" | "ego";

export const INSTALL_STEPS = ["preflight", "uv", "python", "backend", "browser", "config", "school", "notifications", "check"] as const;
export type InstallStep = (typeof INSTALL_STEPS)[number];

export interface InstallOptions {
  browser: InstallBrowser;
  /** Do not ask before installing or before replacing another configured backend. */
  yes: boolean;
  /** The start was confirmed already (setup's question, or --install-carsi): only
   * the start is not asked again; replacing another configured backend still is. */
  confirmed?: boolean;
  /** Start again from the first step. */
  force: boolean;
  skipSchool: boolean;
}

export interface CommandResult {
  code: number;
  stdout: string;
  stderr: string;
}

export interface InstallerHost {
  platform: NodeJS.Platform;
  arch: string;
  home: string;
  env: Record<string, string | undefined>;
  run(command: string, args: string[], options?: { env?: Record<string, string>; echo?: boolean }): Promise<CommandResult>;
  download(url: string, file: string): Promise<void>;
  sha256(file: string): Promise<string>;
  /** Free bytes on the volume holding ``path`` (or its nearest existing parent). */
  freeBytes(path: string): number;
  confirm(question: string): Promise<boolean>;
  ask(question: string): Promise<string>;
  log(line: string): void;
}

/** What install needs from PaperSearch itself. */
export interface InstallContext {
  /** The npm package's root: holds carsi/ with the backend's source. */
  packageRoot: string;
  paperSearchVersion: string;
  /** The backend's data directory (school, logins), as PaperSearch passes it. */
  dataDir: string;
  getConfig(key: "PAPER_SEARCH_CARSI_ENABLED" | "PAPER_SEARCH_CARSI_EXECUTABLE" | "PAPER_SEARCH_CARSI_AUTO_UPDATE"): string;
  setConfig(key: "PAPER_SEARCH_CARSI_ENABLED" | "PAPER_SEARCH_CARSI_EXECUTABLE", value: string): void;
  unsetConfig(key: "PAPER_SEARCH_CARSI_ENABLED" | "PAPER_SEARCH_CARSI_EXECUTABLE"): void;
  /** The MCP handshake with the backend at ``executable``: its readiness state. */
  readiness(executable: string): Promise<{ state: string; message?: string }>;
  now(): Date;
}

export interface InstallRecord {
  schema: 1;
  paperSearchVersion: string;
  /** "camoufox" in installs from before Chrome (ADR 0016); install and update move them to "chrome". */
  browser: InstallBrowser | "camoufox";
  startedAt: string;
  finishedAt?: string;
  steps: Partial<Record<InstallStep, string>>;
  uv?: string;
  python?: string;
  backend?: string;
  executable?: string;
  /** The user's Google Chrome as the browser step found it. */
  chrome?: { path: string; version: string };
  /** Installs from before Chrome: the Camoufox build they downloaded (left for the user to delete). */
  camoufoxBrowser?: string;
  ego?: string;
  school?: string;
  notifications?: boolean;
  /** Set by update: when the extension was last brought to this PaperSearch version. */
  updatedAt?: string;
  warnings?: string[];
}

export class InstallError extends Error {
  constructor(readonly step: InstallStep | "update", message: string, readonly logFile: string) {
    super(message);
    this.name = "InstallError";
  }
}

const GB = 1024 ** 3;

export function readInstallRecord(paths: RuntimePaths): InstallRecord | undefined {
  try {
    return JSON.parse(readFileSync(paths.installFile, "utf8")) as InstallRecord;
  } catch {
    return undefined;
  }
}

export async function installCarsi(
  host: InstallerHost,
  options: InstallOptions,
  context: InstallContext,
): Promise<{ status: "installed" | "already_installed" | "cancelled"; record?: InstallRecord; paths: RuntimePaths }> {
  const paths = runtimePaths(runtimeRoot(host.env, host.home), host.platform);
  let record = readInstallRecord(paths);
  if (record?.browser === "camoufox" && !options.force) {
    // Installed with Camoufox: its environment has no Patchright. Everything
    // from Python on is done again (ADR 0016).
    record.browser = options.browser;
    for (const step of ["python", "backend", "browser", "config", "check"] as const) delete record.steps[step];
    delete record.finishedAt;
  }
  if (record?.finishedAt && record.browser === options.browser && !options.force) {
    host.log(`学校订阅下载已安装（${record.finishedAt}）。查看：paper-search carsi status；重装：加 --force。`);
    return { status: "already_installed", record, paths };
  }
  if (!record || options.force) {
    record = { schema: 1, paperSearchVersion: context.paperSearchVersion, browser: options.browser,
      startedAt: context.now().toISOString(), steps: {} };
  } else if (record.browser !== options.browser) {
    // Another browser: the environment stays, the browser and what follows are redone.
    record.browser = options.browser;
    for (const step of ["browser", "config", "check"] as const) delete record.steps[step];
    delete record.finishedAt;
  }
  describePlan(host, paths, options);
  if (!options.yes && !options.confirmed && !(await host.confirm("开始安装？[y/N] "))) {
    host.log("已取消，没有写入任何文件。");
    return { status: "cancelled", paths };
  }
  mkdirSync(paths.root, { recursive: true });
  host = withLog(host, paths);
  const steps: Record<InstallStep, () => Promise<void>> = {
    preflight: () => preflight(host, paths, options, context),
    uv: async () => { record!.uv = await prepareUv(host, paths); },
    python: () => preparePython(host, paths, record!),
    backend: () => installBackend(host, paths, options, context, record!),
    browser: () => installBrowser(host, paths, options, context, record!),
    config: () => writeConfig(host, paths, options, context, record!),
    school: () => askSchool(host, paths, options, context, record!),
    notifications: () => askNotifications(host, paths, context, record!),
    check: () => selfCheck(host, paths, context, record!),
  };
  for (const step of INSTALL_STEPS) {
    if (record.steps[step]) continue;
    host.log(`== ${step === "browser" && options.browser === "ego" ? "检测 ego lite" : STEP_LABELS[step]}`);
    appendLog(paths, `== ${step} ${context.now().toISOString()}`);
    try {
      await steps[step]();
    } catch (error) {
      writeRecord(paths, record);
      const message = error instanceof InstallError ? error.message : describe(error);
      appendLog(paths, `!! ${step}: ${message}`);
      throw new InstallError(step, message, paths.logFile);
    }
    record.steps[step] = context.now().toISOString();
    writeRecord(paths, record);
  }
  clearUvCache(paths, record);
  record.paperSearchVersion = context.paperSearchVersion;
  record.finishedAt = context.now().toISOString();
  writeRecord(paths, record);
  return { status: "installed", record, paths };
}

/** The same machine, with every command and its output in install.log. */
function withLog(host: InstallerHost, paths: RuntimePaths): InstallerHost {
  return {
    ...host,
    run: async (command, args, runOptions) => {
      appendLog(paths, `$ ${command} ${args.join(" ")}`);
      const result = await host.run(command, args, runOptions);
      appendLog(paths, `${result.stdout}${result.stderr}`.trimEnd() + `\n(exit ${result.code})`);
      return result;
    },
  };
}

const STEP_LABELS: Record<InstallStep, string> = {
  preflight: "检查系统和磁盘空间",
  uv: "准备 uv",
  python: `准备 Python ${PYTHON_VERSION} 和虚拟环境`,
  backend: "安装机构下载后端和依赖",
  browser: "检查 Google Chrome",
  config: "写入配置",
  school: "学校",
  notifications: "系统通知偏好",
  check: "自检",
};

function describePlan(host: InstallerHost, paths: RuntimePaths, options: InstallOptions): void {
  host.log("将要安装 PaperSearch 学校订阅下载（CARSI）：");
  host.log(`  安装目录：${paths.root}（uv、Python ${PYTHON_VERSION}、虚拟环境、安装记录）`);
  host.log(options.browser === "chrome"
    ? "  浏览器：使用你电脑上的 Google Chrome（下载时用单独的浏览器资料，不动你日常用的 Chrome），不另下载浏览器"
    : "  浏览器：使用你的 ego lite，不另下载浏览器");
  host.log("  学校配置和登录会话：保留在原数据目录，不受安装影响");
  host.log("  需要下载约 0.5 GB；会把 PaperSearch 配置改为启用这个后端");
}

const CHROME_MISSING = `没有找到 Google Chrome：请先从 ${CHROME_DOWNLOAD_URL} 安装 Chrome，再运行 paper-search carsi install`;
const CHROME_GONE = `没有找到 Google Chrome：机构下载要用它，请从 ${CHROME_DOWNLOAD_URL} 安装`;

/** Chrome at its usual place, or at ``chrome_executable`` in the backend's config. */
function chromeFound(host: InstallerHost, context: InstallContext): boolean {
  if (host.platform === "linux") return true; // the backend searches PATH; the browser step checks
  let configured = "";
  try {
    configured = String(JSON.parse(readFileSync(join(context.dataDir, "config.json"), "utf8")).chrome_executable ?? "");
  } catch {
    // no backend config yet
  }
  return [configured.trim(), ...chromeCandidates(host.platform, host.home, host.env)].some((path) => path && existsSync(path));
}

async function preflight(
  host: InstallerHost, paths: RuntimePaths, options: InstallOptions, context: InstallContext,
): Promise<void> {
  if (!UV_ARCHIVES[`${host.platform}-${host.arch}`]) {
    throw new Error(`此系统暂不支持（${host.platform}-${host.arch}）`);
  }
  if (!hasScreen(host.platform, host.env)) throw new Error(NO_SCREEN);
  if (options.browser === "ego") {
    if (host.platform !== "darwin") throw new Error("ego lite 目前只支持 macOS；请用 --browser chrome");
    if (!egoAppCandidates(host.home).some((app) => existsSync(app))) {
      throw new Error("没有找到 ego lite（~/Applications 或 /Applications 下的 “ego lite.app”）");
    }
  } else if (!chromeFound(host, context)) {
    throw new Error(CHROME_MISSING);
  }
  const need = 1 * GB;
  const free = host.freeBytes(paths.root);
  if (free < need) {
    throw new Error(`磁盘剩余 ${(free / GB).toFixed(1)} GB，至少需要 ${need / GB} GB`);
  }
}

/** `uv pip install --exact`, which an update uses, works from uv 0.4.22 on (added in 0.4.21, fixed in 0.4.22). */
const UV_EXACT_FROM = [0, 4, 22];

function uvDoesExact(versionLine: string): boolean {
  const version = /(\d+)\.(\d+)\.(\d+)/.exec(versionLine)?.slice(1).map(Number);
  if (!version) return false;
  const differs = version.findIndex((part, i) => part !== UV_EXACT_FROM[i]);
  return differs === -1 || version[differs] > UV_EXACT_FROM[differs];
}

/** The computer's own uv when it is new enough, else the pinned one, downloaded and checked. */
async function prepareUv(host: InstallerHost, paths: RuntimePaths): Promise<string> {
  const onPath = await host.run("uv", ["--version"]).catch(() => undefined);
  if (onPath?.code === 0 && uvDoesExact(onPath.stdout)) return "uv";
  const archive = UV_ARCHIVES[`${host.platform}-${host.arch}`];
  mkdirSync(paths.bin, { recursive: true });
  const file = join(paths.bin, archive.file);
  host.log(`下载 uv ${UV_VERSION}`);
  await host.download(uvArchiveUrl(archive.file), file);
  const actual = await host.sha256(file);
  if (actual !== archive.sha256) {
    rmSync(file, { force: true });
    throw new Error(`uv 安装包校验不符（期望 ${archive.sha256}，实际 ${actual}），已删除`);
  }
  const extract = await host.run("tar", [archive.file.endsWith(".zip") ? "-xf" : "-xzf", file, "-C", paths.bin]);
  if (extract.code !== 0) throw new Error(`解压 uv 失败：${extract.stderr.trim()}`);
  rmSync(file, { force: true });
  const uv = findFile(paths.bin, host.platform === "win32" ? "uv.exe" : "uv");
  if (!uv) throw new Error("解压后没有找到 uv");
  await check(host.run(uv, ["--version"]), "uv 无法运行");
  return uv;
}

function uvEnv(paths: RuntimePaths): Record<string, string> {
  // Python and uv's download cache go into the runtime, not uv's global directories,
  // so uninstalling leaves nothing behind; only uv's own Pythons.
  return { UV_PYTHON_INSTALL_DIR: paths.python, UV_CACHE_DIR: paths.uvCache, UV_PYTHON_PREFERENCE: "only-managed" };
}

async function preparePython(host: InstallerHost, paths: RuntimePaths, record: InstallRecord): Promise<void> {
  const uv = record.uv || "uv";
  await check(host.run(uv, ["python", "install", PYTHON_VERSION], { env: uvEnv(paths), echo: true }),
    `下载 Python ${PYTHON_VERSION} 失败`);
  rmSync(paths.venv, { recursive: true, force: true });
  await check(host.run(uv, ["venv", paths.venv, "--python", PYTHON_VERSION], { env: uvEnv(paths), echo: true }),
    "创建虚拟环境失败");
  record.python = (await check(host.run(paths.venvPython, ["--version"]), "虚拟环境里的 Python 无法运行")).stdout.trim();
}

async function installBackend(
  host: InstallerHost, paths: RuntimePaths, options: InstallOptions, context: InstallContext, record: InstallRecord,
  reinstall = false,
): Promise<void> {
  // Built from a copy: the build writes into its source, and a global npm
  // directory may not be writable.
  const source = join(context.packageRoot, "carsi");
  if (!existsSync(join(source, "pyproject.toml"))) throw new Error(`安装包里没有后端源码：${source}`);
  rmSync(paths.src, { recursive: true, force: true });
  cpSync(source, paths.src, {
    recursive: true,
    filter: (path) => !/(?:^|[\\/])(?:__pycache__|\.venv|tests|build|[^\\/]+\.egg-info)(?:$|[\\/])/.test(path.slice(source.length)),
  });
  // Patchright, which drives either browser, is a base dependency; ego adds its relay.
  const extras = "ego";
  // The backend keeps its version number across PaperSearch releases, so an
  // update reinstalls it explicitly; its dependencies follow pyproject's pins and
  // ranges, and --exact removes those it no longer needs (PyMuPDF after pypdfium2).
  const reinstallArgs = reinstall ? ["--reinstall-package", "paper-search-carsi", "--exact"] : [];
  await check(host.run(record.uv || "uv", ["pip", "install", "--python", paths.venvPython, ...reinstallArgs,
    `${paths.src}[${extras}]`], { env: uvEnv(paths), echo: true }), "安装后端和依赖失败");
  record.backend = (await check(host.run(paths.venvPython, ["-c",
    "import importlib.metadata as m; print(m.version('paper-search-carsi'))"]), "后端没有装好")).stdout.trim();
  record.executable = paths.executable;
}

// The backend's own look at the browsers (backend.browser_check), with its config.
const BROWSER_PROBE = [
  "import json",
  "from paper_search_carsi.browser import backend as b",
  "from paper_search_carsi.config import load_config",
  "c = load_config()",
  "print(json.dumps({'chrome': b.browser_check(c), 'ego': b.ego_app_version(c)}))",
].join("\n");

interface BrowserProbe {
  /** The Chrome the backend would run ("" browser when none) and its version against the tested one. */
  chrome: { browser: string; path: string; version: string; tested: string; outdated: boolean; driver: string };
  ego: string;
}

async function browserProbe(host: InstallerHost, paths: RuntimePaths, context: InstallContext): Promise<BrowserProbe> {
  const result = await check(host.run(paths.venvPython, ["-c", BROWSER_PROBE], { env: { CARSI_DATA_DIR: context.dataDir } }),
    "读取浏览器版本失败");
  return JSON.parse(result.stdout.trim().split("\n").pop() || "{}");
}

function outdatedChrome(chrome: BrowserProbe["chrome"]): string {
  return `Google Chrome ${chrome.version} 低于测试过的 ${chrome.tested}：请先更新 Chrome（菜单 → 帮助 → 关于 Google Chrome）`;
}

async function installBrowser(
  host: InstallerHost, paths: RuntimePaths, options: InstallOptions, context: InstallContext, record: InstallRecord,
): Promise<void> {
  const probe = await browserProbe(host, paths, context);
  if (options.browser === "chrome") {
    if (!probe.chrome?.browser) throw new Error(CHROME_MISSING);
    record.chrome = { path: probe.chrome.path, version: probe.chrome.version };
    host.log(`  Google Chrome ${probe.chrome.version || "（版本未知）"}：${probe.chrome.path}；${probe.chrome.driver}`);
    if (probe.chrome.outdated) host.log(`  注意：${outdatedChrome(probe.chrome)}`);
  }
  if (probe.ego) record.ego = probe.ego;
  if (record.camoufoxBrowser) {
    // Not deleted here: other programs on this computer may use Camoufox's cache.
    const old = camoufoxBuildDir(host.platform, record.camoufoxBrowser, host.home, host.env);
    if (existsSync(old)) {
      const note = `以前下载的 Camoufox 浏览器不再使用，可以手动删除：${old}（本机其他用 Camoufox 的程序可能也在用）`;
      host.log(`  ${note}`);
      warn(record, note);
    }
    delete record.camoufoxBrowser;
  }
}

async function writeConfig(
  host: InstallerHost, paths: RuntimePaths, options: InstallOptions, context: InstallContext, record: InstallRecord,
): Promise<void> {
  const current = context.getConfig("PAPER_SEARCH_CARSI_EXECUTABLE");
  if (current && current !== paths.executable && !options.yes) {
    host.log(`现在配置的后端是：${current}`);
    if (!(await host.confirm("改用这次安装的后端？[y/N] "))) {
      warn(record, `保留原来的后端配置：${current}`);
      return;
    }
  }
  context.setConfig("PAPER_SEARCH_CARSI_EXECUTABLE", paths.executable);
  context.setConfig("PAPER_SEARCH_CARSI_ENABLED", "true");
  await check(host.run(paths.executable, ["config", "set", "browser_backend", options.browser],
    { env: { CARSI_DATA_DIR: context.dataDir } }), "写入浏览器设置失败");
}

// The backend's own rule for "some institutional access is configured" (CARSI);
// without it the backend skips the browser download altogether.
const ACCESS_PROBE = [
  "import json",
  "from paper_search_carsi.config import load_config",
  "from paper_search_carsi.engine.bridge import _any_institutional_configured",
  "c = load_config()",
  "print(json.dumps({'configured': _any_institutional_configured(c), 'school': c.get('carsi_idp_name') or ''}))",
].join("\n");

async function askSchool(
  host: InstallerHost, paths: RuntimePaths, options: InstallOptions, context: InstallContext, record: InstallRecord,
): Promise<void> {
  const env = { CARSI_DATA_DIR: context.dataDir };
  const probe = await check(host.run(paths.venvPython, ["-c", ACCESS_PROBE], { env }), "读取机构访问设置失败");
  const access = JSON.parse(probe.stdout.trim().split("\n").pop() || "{}") as { configured?: boolean; school?: string };
  let school = access.school || "";
  const answer = options.skipSchool ? "" : (await host.ask(school
    ? `学校（CARSI；现在是“${school}”，回车保留）：`
    : "请输入你的学校（中文名、英文名或域名都可以；回车跳过，登录时在选校页自己选）：")).trim();
  if (answer) school = (await saveSchool(host, paths, env, answer)) || school;
  if (!school && !access.configured) {
    // CARSI on, the school chosen by the user on the chooser.
    await check(host.run(paths.executable, ["setup", "--carsi"], { env }), "开启 CARSI 失败");
  }
  if (school) record.school = school;
  else warn(record, "还没有配置学校：机构登录时需要你在选校页自己选");
}

interface SchoolCandidate { name: string; name_en: string; domain: string; entity_id: string }

async function askNotifications(
  host: InstallerHost, paths: RuntimePaths, context: InstallContext, record: InstallRecord,
): Promise<void> {
  const env = { CARSI_DATA_DIR: context.dataDir };
  const result = await check(host.run(paths.executable, ["config", "get", "progress_notify"], { env }),
    "读取系统通知设置失败");
  const current: unknown = JSON.parse(result.stdout).progress_notify;
  if (typeof current !== "boolean") throw new Error("系统通知设置必须为 true 或 false");
  for (let attempt = 0; attempt < 3; attempt++) {
    const answer = (await host.ask(
      `需要登录或手动处理时，是否发送系统通知？[y/n，回车保留${current ? "开启" : "关闭"}]（以后可在胶囊齿轮中修改）：`,
    )).trim();
    if (answer && !/^(?:y(?:es)?|n(?:o)?)$/i.test(answer)) {
      host.log("请输入 y（开启）或 n（关闭），也可以回车保留当前设置。");
      continue;
    }
    const enabled = answer ? /^y(?:es)?$/i.test(answer) : current;
    if (answer) await check(host.run(paths.executable,
      ["config", "set", "progress_notify", String(enabled)], { env }), "保存系统通知设置失败");
    record.notifications = enabled;
    host.log(`系统通知已${enabled ? "开启" : "关闭"}；胶囊的琥珀色提醒始终保留。`);
    return;
  }
  throw new Error("尚未选择系统通知偏好，请重新运行安装命令继续配置");
}

interface SetupReply {
  error?: string;
  detail?: string;
  count?: number;
  candidates?: SchoolCandidate[];
  settings?: { carsi_institution_hint?: string };
}

function setupReply(stdout: string): SetupReply {
  try {
    return JSON.parse(stdout.trim()) as SetupReply;
  } catch {
    return {}; // not a setup reply: the exit code decides
  }
}

/**
 * The backend looks the school up in the CARSI member list and saves its
 * names and entityID. Several matches are numbered for the user to pick one
 * (saved by its entityID); a name that is not a member is asked again. An
 * empty answer leaves the school as it was ("" is returned).
 */
async function saveSchool(
  host: InstallerHost, paths: RuntimePaths, env: Record<string, string>, first: string,
): Promise<string> {
  const setup = (school: string) => host.run(paths.executable, ["setup", "--carsi", "--institution", school], { env });
  let answer = first;
  for (let attempt = 1; answer; attempt++) {
    let result = await setup(answer);
    const reply = setupReply(result.stdout);
    if (result.code !== 0 && reply.error === "carsi_school_list_unavailable") {
      throw new Error(`取不到 CARSI 学校列表（${reply.detail ?? ""}）：稍后再运行本命令，或加 --skip-school 先跳过`);
    }
    if (result.code !== 0 && reply.error === "carsi_school_not_found") {
      if (attempt >= 3) throw new Error(`CARSI 成员学校里没有“${answer}”`);
      answer = (await host.ask(`CARSI 成员学校里没有“${answer}”，请重新输入（中文名、英文名或域名；回车跳过）：`)).trim();
      continue;
    }
    if (result.code !== 0 && reply.error === "carsi_school_ambiguous" && reply.candidates?.length) {
      const candidates = reply.candidates;
      const more = (reply.count ?? 0) > candidates.length ? `（共 ${reply.count} 所，列出前 ${candidates.length} 所）` : "";
      host.log(`“${answer}”对应多所学校${more}：`);
      candidates.forEach((c, i) => host.log(`  ${i + 1}. ${c.name}（${c.name_en}，${c.domain}）`));
      const pick = candidates[Number((await host.ask("输入序号（回车跳过）：")).trim()) - 1];
      if (!pick) return "";
      result = await setup(pick.entity_id);
    }
    await check(Promise.resolve(result), "保存学校失败");
    return setupReply(result.stdout).settings?.carsi_institution_hint || answer;
  }
  return "";
}

async function selfCheck(host: InstallerHost, paths: RuntimePaths, context: InstallContext, record: InstallRecord): Promise<void> {
  const tk = await host.run(paths.venvPython, ["-c", "import tkinter"]);
  if (tk.code !== 0) warn(record, "这个 Python 没有 tkinter：下载照常，只是没有进度窗口");
  const readiness = await context.readiness(paths.executable);
  if (readiness.state !== "available") {
    throw new Error(`后端握手没有通过（${readiness.state}${readiness.message ? `：${readiness.message}` : ""}）`);
  }
}

/**
 * After a PaperSearch upgrade: the backend and its dependencies from the new
 * package, the browser check, and the handshake. The school, logins, Chrome and
 * ego lite are left alone. An install from before Chrome gets a new Python
 * environment first (its Camoufox build stays where it is, named for the user).
 */
export async function updateCarsi(
  host: InstallerHost,
  options: { force: boolean },
  context: InstallContext,
): Promise<{ status: "updated" | "up_to_date"; record: InstallRecord; paths: RuntimePaths }> {
  const paths = runtimePaths(runtimeRoot(host.env, host.home), host.platform);
  const record = readInstallRecord(paths);
  if (!record?.finishedAt || !existsSync(paths.venvPython)) {
    throw new InstallError("update", "还没有装好：先运行 paper-search carsi install", paths.logFile);
  }
  if (record.paperSearchVersion === context.paperSearchVersion && !options.force) {
    host.log(`已是最新（PaperSearch ${context.paperSearchVersion}）。要强制重装后端，加 --force。`);
    return { status: "up_to_date", record, paths };
  }
  host = withLog(host, paths);
  appendLog(paths, `== update ${record.paperSearchVersion} -> ${context.paperSearchVersion} ${context.now().toISOString()}`);
  const legacy = record.browser === "camoufox";
  const settings: InstallOptions = { browser: legacy ? "chrome" : record.browser as InstallBrowser,
    yes: true, force: false, skipSchool: true };
  try {
    // The computer's uv may since have gone or be too old for --exact; a downloaded one may be gone.
    if (record.uv === "uv" || (record.uv && !existsSync(record.uv))) record.uv = await prepareUv(host, paths);
    if (legacy) {
      host.log("== 改用 Google Chrome：重建 Python 环境（不再下载 Camoufox）");
      await preparePython(host, paths, record);
      record.browser = "chrome";
    }
    host.log("== 更新机构下载后端和依赖");
    await installBackend(host, paths, settings, context, record, true);
    host.log(`== ${settings.browser === "ego" ? "检测 ego lite" : STEP_LABELS.browser}`);
    await installBrowser(host, paths, settings, context, record);
    host.log("== 自检");
    await selfCheck(host, paths, context, record);
  } catch (error) {
    writeRecord(paths, record);
    const message = describe(error);
    appendLog(paths, `!! update: ${message}`);
    throw new InstallError("update", message, paths.logFile);
  }
  clearUvCache(paths, record);
  record.paperSearchVersion = context.paperSearchVersion;
  record.updatedAt = context.now().toISOString();
  writeRecord(paths, record);
  return { status: "updated", record, paths };
}

export interface UninstallOptions {
  /** Do not ask; keep the user's data unless told to remove it. */
  yes: boolean;
  removeData: boolean;
}

/**
 * Remove the runtime and turn the integration off. The user's data (school,
 * logins) is kept unless the user chooses to remove it; Chrome and ego lite are
 * the user's own and never touched. A Camoufox build left by an install from
 * before Chrome is named for the user, never deleted here.
 */
export async function uninstallCarsi(
  host: InstallerHost,
  options: UninstallOptions,
  context: InstallContext,
): Promise<{ status: "uninstalled" | "cancelled" | "not_installed"; removed: string[]; kept: string[] }> {
  const paths = runtimePaths(runtimeRoot(host.env, host.home), host.platform);
  if (!existsSync(paths.root)) {
    host.log("没有安装学校订阅下载。");
    return { status: "not_installed", removed: [], kept: [] };
  }
  const record = readInstallRecord(paths);
  const oldBrowser = record?.camoufoxBrowser
    ? camoufoxBuildDir(host.platform, record.camoufoxBrowser, host.home, host.env) : "";
  const hasOldBrowser = Boolean(oldBrowser) && existsSync(oldBrowser);
  const hasData = existsSync(context.dataDir);
  const configured = context.getConfig("PAPER_SEARCH_CARSI_EXECUTABLE");
  const ours = configured === paths.executable;
  host.log("将要卸载 PaperSearch 学校订阅下载（CARSI）：");
  host.log(`  删除安装目录：${paths.root}（${(directoryBytes(paths.root) / GB).toFixed(2)} GB）`);
  host.log(ours
    ? "  PaperSearch 配置：关闭机构下载，清除后端路径"
    : `  PaperSearch 配置：不改（用的是另一个后端：${configured || "未配置"}）`);
  if (hasData) host.log(`  学校配置和登录会话（${context.dataDir}）：默认保留`);
  host.log(record?.browser === "ego" ? "  ego lite 是你自己的浏览器，不受影响" : "  Google Chrome 是你自己的浏览器，不受影响");
  if (hasOldBrowser) host.log(`  以前下载的 Camoufox 浏览器（${oldBrowser}）：不再使用，这里不删，可以手动删除`);
  if (!options.yes && !(await host.confirm("确认卸载？[y/N] "))) {
    host.log("已取消，没有删除任何东西。");
    return { status: "cancelled", removed: [], kept: [] };
  }
  const removeData = hasData && (options.removeData || (!options.yes && await host.confirm(
    "也删除学校配置和登录会话？删除后要重新配置学校、重新登录。[y/N] ")));
  const removed: string[] = [];
  const kept: string[] = [];
  rmSync(paths.root, { recursive: true, force: true });
  removed.push(paths.root);
  if (ours) {
    context.unsetConfig("PAPER_SEARCH_CARSI_EXECUTABLE");
    context.unsetConfig("PAPER_SEARCH_CARSI_ENABLED");
    removed.push("PaperSearch 配置 PAPER_SEARCH_CARSI_ENABLED、PAPER_SEARCH_CARSI_EXECUTABLE");
  } else {
    kept.push(`PaperSearch 配置（后端：${configured || "未配置"}）`);
  }
  if (hasOldBrowser) kept.push(oldBrowser);
  if (hasData) (removeData ? removed : kept).push(context.dataDir);
  if (removeData) rmSync(context.dataDir, { recursive: true, force: true });
  return { status: "uninstalled", removed, kept };
}

export interface CarsiStatus {
  installed: boolean;
  complete: boolean;
  root: string;
  record?: InstallRecord;
  executable: string;
  executableExists: boolean;
  enabled: boolean;
  configuredExecutable: string;
  usesThisInstall: boolean;
  paperSearchVersion: string;
  upToDate: boolean;
  versions?: BrowserProbe;
  runtimeBytes: number;
  notes: string[];
}

export async function carsiStatus(host: InstallerHost, context: InstallContext): Promise<CarsiStatus> {
  const paths = runtimePaths(runtimeRoot(host.env, host.home), host.platform);
  const record = readInstallRecord(paths);
  const executableExists = existsSync(paths.executable);
  const configuredExecutable = context.getConfig("PAPER_SEARCH_CARSI_EXECUTABLE");
  const enabled = context.getConfig("PAPER_SEARCH_CARSI_ENABLED") === "true";
  const notes: string[] = [];
  let versions: CarsiStatus["versions"];
  if (existsSync(paths.venvPython)) {
    versions = await browserProbe(host, paths, context).catch(() => undefined);
  }
  const complete = Boolean(record?.finishedAt) && executableExists;
  const upToDate = record?.paperSearchVersion === context.paperSearchVersion;
  if (!record) notes.push("还没有安装：paper-search carsi install");
  else if (!record.finishedAt) {
    const done = INSTALL_STEPS.filter((step) => record.steps[step]).length;
    notes.push(`安装没有完成（${done}/${INSTALL_STEPS.length} 步）：再运行 paper-search carsi install 接着装`);
  }
  if (complete && record?.browser === "camoufox") {
    notes.push("机构下载已改用 Google Chrome，不再用 Camoufox：运行 paper-search carsi update");
  } else if (complete && !upToDate) {
    notes.push(`PaperSearch 已是 ${context.paperSearchVersion}，扩展是 ${record?.paperSearchVersion} 时装的：运行 paper-search carsi update`);
  }
  if (complete && record?.browser !== "ego" && versions?.chrome) {
    if (!versions.chrome.browser) notes.push(CHROME_GONE);
    else if (versions.chrome.outdated) notes.push(outdatedChrome(versions.chrome));
  }
  if (complete && configuredExecutable !== paths.executable) notes.push(`PaperSearch 用的是另一个后端：${configuredExecutable || "（未配置）"}`);
  if (complete && !enabled) notes.push("机构下载没有启用：paper-search config set PAPER_SEARCH_CARSI_ENABLED true");
  return {
    installed: Boolean(record), complete, root: paths.root, ...(record ? { record } : {}),
    executable: paths.executable, executableExists, enabled, configuredExecutable,
    usesThisInstall: configuredExecutable === paths.executable,
    paperSearchVersion: context.paperSearchVersion, upToDate,
    ...(versions ? { versions } : {}),
    runtimeBytes: directoryBytes(paths.root), notes,
  };
}

export function renderStatusText(status: CarsiStatus): string {
  const r = status.record;
  const lines = [
    `学校订阅下载：${status.complete ? "已安装" : status.installed ? "安装未完成" : "未安装"}`,
    `  安装目录：${status.root}（${(status.runtimeBytes / GB).toFixed(2)} GB）`,
  ];
  if (r) {
    const chrome = status.versions?.chrome;
    lines.push(`  浏览器：${r.browser === "ego"
      ? `ego lite${status.versions?.ego || r.ego ? `（${status.versions?.ego || r.ego}）` : ""}`
      : r.browser === "camoufox" ? "camoufox（已停用，运行 paper-search carsi update 改用 Google Chrome）" : "Google Chrome"}`);
    if (chrome) {
      lines.push(chrome.browser
        ? `  Google Chrome：${chrome.version || "版本未知"}（${chrome.path}；测试过的版本 ${chrome.tested}）`
        : "  Google Chrome：没有找到");
      if (chrome.driver) lines.push(`  驱动：${chrome.driver}`);
    }
    lines.push(`  ego lite：${status.versions?.ego || r.ego || "未检测到"}`);
    lines.push(`  Python：${r.python || "-"}；后端：${r.backend || "-"}；uv：${r.uv || "-"}`);
    lines.push(`  学校：${r.school || "未配置"}`);
    lines.push(`  安装时的 PaperSearch：${r.paperSearchVersion}（现在 ${status.paperSearchVersion}）`);
  }
  lines.push(`  PaperSearch 配置：${status.enabled ? "已启用" : "未启用"}，后端 ${status.configuredExecutable || "（未配置）"}`);
  for (const warning of r?.warnings ?? []) lines.push(`  注意：${warning}`);
  for (const note of status.notes) lines.push(`  → ${note}`);
  return lines.join("\n");
}

async function check(pending: Promise<CommandResult>, failure: string): Promise<CommandResult> {
  const result = await pending;
  if (result.code !== 0) {
    const detail = (result.stderr || result.stdout).trim().split("\n").slice(-3).join(" | ");
    throw new Error(`${failure}${detail ? `：${detail}` : ""}`);
  }
  return result;
}

/**
 * uv's download cache, once the environment is built: an update reinstalls only
 * the backend from the package and fetches only dependencies that changed, so
 * only a forced reinstall would use it again. An install that stopped keeps it,
 * for the next run to go on from.
 */
function clearUvCache(paths: RuntimePaths, record: InstallRecord): void {
  try {
    rmSync(paths.uvCache, { recursive: true, force: true });
  } catch (error) {
    warn(record, `下载缓存没能清掉，可以手动删除：${paths.uvCache}（${describe(error)}）`);
  }
}

function warn(record: InstallRecord, text: string): void {
  record.warnings = [...(record.warnings ?? []).filter((w) => w !== text), text];
}

function writeRecord(paths: RuntimePaths, record: InstallRecord): void {
  mkdirSync(paths.root, { recursive: true });
  writeFileSync(paths.installFile, `${JSON.stringify(record, null, 2)}\n`);
}

function appendLog(paths: RuntimePaths, text: string): void {
  mkdirSync(dirname(paths.logFile), { recursive: true });
  appendFileSync(paths.logFile, `${text}\n`);
}

function findFile(dir: string, name: string): string | undefined {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isFile() && entry.name === name) return path;
    if (entry.isDirectory()) {
      const found = findFile(path, name);
      if (found) return found;
    }
  }
  return undefined;
}

function directoryBytes(dir: string): number {
  if (!existsSync(dir)) return 0;
  let total = 0;
  const pending = [dir];
  while (pending.length) {
    const current = pending.pop()!;
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const path = join(current, entry.name);
      if (entry.isDirectory()) pending.push(path);
      else if (entry.isFile()) total += statSync(path).size;
    }
  }
  return total;
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

