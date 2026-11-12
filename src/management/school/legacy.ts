import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import {
  browserProfileInUse,
  DOWNLOAD_LOCK_FILE,
  isStaleDownloadLock,
  LEGACY_SCHOOL_DATA_DIR,
  paperSearchDataHome,
} from "../../capabilities/pdf-discovery/school/index.js";

/**
 * Before 0.6.1 school subscription downloads were named for CARSI, the first
 * federation they supported: the config keys (ConfigService), the backend's data
 * directory and its runtime. What 0.6.0 left is taken over here once:
 * - the data directory ``paper-search-cli/carsi`` (school, logins, progress, runs)
 *   is renamed ``school`` when nothing uses it;
 * - the runtime ``paper-search-cli/carsi-runtime`` cannot be moved (its Python
 *   environment holds its own paths): ``school update`` installs a new one beside
 *   it and removes the old (installer.ts).
 */
export const LEGACY_RUNTIME_DIR = "carsi-runtime";

export function legacyRuntimeRoot(
  env: Record<string, string | undefined> = process.env,
  home: string = homedir(),
): string {
  return join(paperSearchDataHome(env, home), LEGACY_RUNTIME_DIR);
}

export interface DataMove {
  outcome: "none" | "moved" | "busy" | "failed";
  from?: string;
  to?: string;
  error?: string;
}

/**
 * Renames 0.6.0's data directory once nothing uses it: no download holds its
 * lock and no download browser has a profile open in it. 0.6.0's progress window,
 * which would keep showing the old place, is closed first. Paths the backend saved
 * in its config follow the directory. Until the rename succeeds the old directory
 * stays in use (resolveDefaultSchoolProfileDir), and the next command tries again.
 */
export function moveLegacyDataDir(
  env: Record<string, string | undefined> = process.env,
  home: string = homedir(),
  platform: NodeJS.Platform = process.platform,
): DataMove {
  const base = paperSearchDataHome(env, home);
  const from = join(base, LEGACY_SCHOOL_DATA_DIR);
  const to = join(base, "school");
  if (existsSync(to) || !existsSync(from)) return { outcome: "none" };
  const lock = join(from, DOWNLOAD_LOCK_FILE);
  if ((existsSync(lock) && !isStaleDownloadLock(lock, from)) || browserProfileInUse(from)) {
    return { outcome: "busy", from, to };
  }
  closeLegacyProgressWindow(from, platform);
  try {
    renameSync(from, to);
  } catch (error) {
    return { outcome: "failed", from, to, error: (error as Error).message };
  }
  followSavedPaths(join(to, "config.json"), from, to);
  return { outcome: "moved", from, to };
}

/**
 * 0.6.0's progress window, recorded in ``progress/bar.pid``: closed when that
 * process is still the window (its command line names the module), never another
 * process that took over the number.
 */
export function closeLegacyProgressWindow(dataDir: string, platform: NodeJS.Platform = process.platform): void {
  let pid: number;
  try {
    pid = Number(readFileSync(join(dataDir, "progress", "bar.pid"), "utf8").trim());
  } catch {
    return;
  }
  if (!Number.isSafeInteger(pid) || pid <= 0 || !alive(pid)) return;
  if (!/paper_search_carsi[.\\/]progress_capsule/.test(commandLine(pid, platform))) return;
  try {
    process.kill(pid);
  } catch {
    return;
  }
  // Windows releases the window's files only once the process is gone.
  const until = Date.now() + 3000;
  while (alive(pid) && Date.now() < until) Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
}

function commandLine(pid: number, platform: NodeJS.Platform): string {
  try {
    return platform === "win32"
      ? execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command",
        `(Get-CimInstance Win32_Process -Filter "ProcessId=${pid}").CommandLine`],
      { encoding: "utf8", timeout: 15000, windowsHide: true })
      : execFileSync("ps", ["-o", "command=", "-p", String(pid)], { encoding: "utf8", timeout: 5000 });
  } catch {
    return "";
  }
}

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

/** The backend saves its whole config, defaults included: paths under the old directory move with it. */
function followSavedPaths(configFile: string, from: string, to: string): void {
  let config: Record<string, unknown>;
  try {
    config = JSON.parse(readFileSync(configFile, "utf8")) as Record<string, unknown>;
  } catch {
    return; // no backend config yet
  }
  let changed = false;
  for (const [key, value] of Object.entries(config)) {
    if (typeof value === "string" && (value === from || value.startsWith(`${from}/`) || value.startsWith(`${from}\\`))) {
      config[key] = to + value.slice(from.length);
      changed = true;
    }
  }
  if (changed) writeFileSync(configFile, `${JSON.stringify(config, null, 2)}\n`);
}
