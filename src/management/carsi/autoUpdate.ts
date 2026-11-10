import { existsSync } from "node:fs";
import type { CarsiBackend, CarsiBatchPapers, CarsiBatchUpdate } from "../../capabilities/pdf-discovery/carsi/index.js";
import { InstallError, readInstallRecord, updateCarsi, type InstallContext, type InstallerHost } from "./installer.js";
import { runtimePaths, runtimeRoot } from "./runtime.js";

export type AutoUpdateOutcome = "off" | "not_needed" | "busy" | "updated" | "failed";

const MANUAL = "这次用旧版本继续；可以稍后运行 paper-search carsi update。";

/**
 * After a PaperSearch upgrade, the extension is brought up to it before its
 * first use (`carsi update`), as the Skill is synced after an upgrade;
 * PAPER_SEARCH_CARSI_AUTO_UPDATE=false turns this off. Only the extension this
 * PaperSearch installed and uses: another backend (a developer's) is left alone.
 * ``lock`` takes the download lock and answers how to release it (it throws
 * EEXIST while another PaperSearch holds it), so a download running elsewhere
 * keeps its backend and two upgrades never install at once. Every step is said
 * on stderr; a failed update leaves the old backend for this download.
 */
export async function autoUpdateCarsi(
  host: InstallerHost,
  context: InstallContext,
  lock: () => () => void,
): Promise<AutoUpdateOutcome> {
  if (context.getConfig("PAPER_SEARCH_CARSI_AUTO_UPDATE") === "false") return "off";
  const paths = runtimePaths(runtimeRoot(host.env, host.home), host.platform);
  /** The PaperSearch version the extension was installed with, when it is behind this one. */
  const behind = (): string | undefined => {
    const record = readInstallRecord(paths);
    return record?.finishedAt && existsSync(paths.venvPython) && record.paperSearchVersion !== context.paperSearchVersion
      ? record.paperSearchVersion : undefined;
  };
  if (context.getConfig("PAPER_SEARCH_CARSI_EXECUTABLE") !== paths.executable || !behind()) return "not_needed";
  let release: () => void;
  try {
    release = lock();
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
      host.log(`学校订阅下载扩展没能自动更新：${(error as Error).message}。${MANUAL}`);
      return "failed";
    }
    host.log(`学校订阅下载扩展要更新到 PaperSearch ${context.paperSearchVersion}，但另一个 PaperSearch 正在用它；这次不更新，下次用到时再更新。`);
    return "busy";
  }
  try {
    // Another PaperSearch may have updated it just before the lock was taken.
    const installed = behind();
    if (!installed) return "not_needed";
    host.log(`学校订阅下载扩展是 PaperSearch ${installed} 时装的，先更新到 ${context.paperSearchVersion} 再下载` +
      "（不想自动更新：paper-search config set PAPER_SEARCH_CARSI_AUTO_UPDATE false）。");
    await updateCarsi(host, { force: false }, context);
    host.log("扩展已更新，继续下载。");
    return "updated";
  } catch (error) {
    const log = error instanceof InstallError ? `（日志：${error.logFile}）` : "";
    host.log(`学校订阅下载扩展没能自动更新：${(error as Error).message}${log}。${MANUAL}`);
    return "failed";
  } finally {
    release();
  }
}

/**
 * ``backend`` with ``update`` run once, before the first call that starts the
 * backend process: a probe, a download, or a batch progress or papers report (a
 * batch session itself starts nothing). Calls made meanwhile wait for the same update.
 */
export function withAutoUpdate(backend: CarsiBackend, update: () => Promise<unknown>): CarsiBackend {
  let pending: Promise<unknown> | undefined;
  const ready = () => (pending ??= update());
  const wrap = (inner: CarsiBackend): CarsiBackend => ({
    probe: async (signal) => {
      await ready();
      return inner.probe(signal);
    },
    downloadLegalDoi: async (request) => {
      await ready();
      return inner.downloadLegalDoi(request);
    },
    ...(inner.withBatchSession
      ? { withBatchSession: <T>(run: (scoped: CarsiBackend) => Promise<T>) =>
          inner.withBatchSession!((scoped) => run(wrap(scoped))) }
      : {}),
    ...(inner.reportBatchProgress
      ? { reportBatchProgress: async (progress: CarsiBatchUpdate, signal?: AbortSignal) => {
          await ready();
          return inner.reportBatchProgress!(progress, signal);
        } }
      : {}),
    ...(inner.reportBatchPapers
      ? { reportBatchPapers: async (papers: CarsiBatchPapers, last?: boolean) => {
          await ready();
          return inner.reportBatchPapers!(papers, last);
        } }
      : {}),
  });
  return wrap(backend);
}
