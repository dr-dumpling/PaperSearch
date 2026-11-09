import { homedir } from "node:os";
import { join, resolve } from "node:path";

/**
 * Where the institutional extension is installed (ADR 0013): uv when the
 * machine has none, a managed Python, the virtual environment with the backend,
 * the install record and log. The user's data (school, logins) stays in the
 * backend's data directory. The browser is the user's own Google Chrome (ADR 0016).
 */
export const UV_VERSION = "0.13.6";

/** uv's release archives and their SHA-256 (the release's .sha256 files, 2026-11-01). */
export const UV_ARCHIVES: Readonly<Record<string, { file: string; sha256: string }>> = {
  "darwin-arm64": {
    file: "uv-aarch64-apple-darwin.tar.gz",
    sha256: "60fbd5c8a1ed681845eea28d9d622fcde03c51e91a43465b64a1e17db1ed3472",
  },
  "darwin-x64": {
    file: "uv-x86_64-apple-darwin.tar.gz",
    sha256: "63ba17fdda55ad1a230d4b37fc6017ffa10c23688c83818bd3bfdf914c652a02",
  },
  "win32-x64": {
    file: "uv-x86_64-pc-windows-msvc.zip",
    sha256: "a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f",
  },
  "win32-arm64": {
    file: "uv-aarch64-pc-windows-msvc.zip",
    sha256: "c2426c0c8e28b53d8c440e47a18d96ad4db51e159866c0e81435b196d7f0081c",
  },
  "linux-x64": {
    file: "uv-x86_64-unknown-linux-gnu.tar.gz",
    sha256: "f29c3e94ffabd7e6f3ba521dba169a9b7ec12100bf3257087f0f24f6123f3645",
  },
  "linux-arm64": {
    file: "uv-aarch64-unknown-linux-gnu.tar.gz",
    sha256: "229e194255c7958d86d56e8790d969a6f74736592133f0dfd0076f754c642c1d",
  },
};

export const PYTHON_VERSION = "3.12";

export function uvArchiveUrl(file: string): string {
  return `https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${file}`;
}

/** `${XDG_DATA_HOME:-~/.local/share}/paper-search-cli/carsi-runtime`, beside the backend's data directory. */
export function runtimeRoot(env: Record<string, string | undefined> = process.env, home: string = homedir()): string {
  const base = env.XDG_DATA_HOME ? resolve(env.XDG_DATA_HOME) : join(home, ".local", "share");
  return join(base, "paper-search-cli", "carsi-runtime");
}

export interface RuntimePaths {
  root: string;
  bin: string;
  python: string;
  /** uv's download cache, kept here so uninstalling removes it too. */
  uvCache: string;
  venv: string;
  src: string;
  venvPython: string;
  executable: string;
  installFile: string;
  logFile: string;
}

export function runtimePaths(root: string, platform: NodeJS.Platform): RuntimePaths {
  const windows = platform === "win32";
  const venv = join(root, "venv");
  const scripts = join(venv, windows ? "Scripts" : "bin");
  return {
    root,
    bin: join(root, "bin"),
    python: join(root, "python"),
    uvCache: join(root, "uv-cache"),
    venv,
    src: join(root, "src"),
    venvPython: join(scripts, windows ? "python.exe" : "python"),
    // pip writes this launcher from pyproject's [project.scripts]; on Windows an .exe.
    executable: join(scripts, windows ? "paper-search-carsi.exe" : "paper-search-carsi"),
    installFile: join(root, "install.json"),
    logFile: join(root, "install.log"),
  };
}

/**
 * Whether this computer can show windows. School subscription downloads need a
 * visible browser for the school login: on Linux an X or Wayland display (a
 * server has neither); macOS and Windows always have one.
 */
export function hasScreen(platform: NodeJS.Platform, env: Record<string, string | undefined>): boolean {
  return platform === "darwin" || platform === "win32" || Boolean(env.DISPLAY || env.WAYLAND_DISPLAY);
}

export const NO_SCREEN =
  "学校订阅下载要在浏览器里登录学校，需要图形界面；这台电脑没有（没有 DISPLAY 或 WAYLAND_DISPLAY），不能安装。" +
  "检索、查影响因子、开放获取下载都不需要它；API key 用 paper-search setup <KEY> 填。";

/** ego lite, the user's own browser; only looked for on macOS (ADR 0013). */
export function egoAppCandidates(home: string = homedir()): string[] {
  return [join(home, "Applications", "ego lite.app"), "/Applications/ego lite.app"];
}

export const CHROME_DOWNLOAD_URL = "https://www.google.com/chrome/";

/**
 * Where Google Chrome installs itself, as the backend looks for it
 * (browser/backend.py find_chrome); on Linux the backend searches PATH itself.
 */
export function chromeCandidates(
  platform: NodeJS.Platform,
  home: string = homedir(),
  env: Record<string, string | undefined> = process.env,
): string[] {
  if (platform === "darwin") {
    return ["/Applications", join(home, "Applications")]
      .map((base) => join(base, "Google Chrome.app", "Contents", "MacOS", "Google Chrome"));
  }
  if (platform === "win32") {
    return [env.PROGRAMFILES, env["PROGRAMFILES(X86)"], env.LOCALAPPDATA]
      .filter((root): root is string => Boolean(root))
      .map((root) => join(root, "Google", "Chrome", "Application", "chrome.exe"));
  }
  return [];
}

/**
 * Where an install from before Chrome had its Camoufox browser build:
 * Camoufox's own cache (platformdirs' user cache directory for "camoufox").
 */
export function camoufoxBuildDir(
  platform: NodeJS.Platform,
  build: string,
  home: string = homedir(),
  env: Record<string, string | undefined> = process.env,
): string {
  const cache = platform === "darwin"
    ? join(home, "Library", "Caches", "camoufox")
    : platform === "win32"
      ? join(env.LOCALAPPDATA || join(home, "AppData", "Local"), "camoufox", "camoufox", "Cache")
      : join(env.XDG_CACHE_HOME || join(home, ".cache"), "camoufox");
  return join(cache, "browsers", "official", build);
}
