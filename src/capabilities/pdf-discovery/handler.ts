import { resolveDownloadPath, runDownloadFolder } from "../../config/ConfigService.js";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, parse, resolve, sep } from "node:path";
import type { Searchers } from "../../core/searchers.js";
import { resolvePlatformId } from "../../registry/platformMetadata.js";
import {
  createDefaultDownloadTiers,
  downloadWithFallback,
} from "./OpenAccessFallbackService.js";
import type { SchoolBackend } from "./school/index.js";

import { RunLedger, resolveRunLogRoot } from "../../infrastructure/runlog/RunLedger.js";
import type {
  DownloadWithFallbackOptions,
  DownloadWithFallbackResult,
} from "./types.js";
import {
  downloadBatch,
  downloadBatchItem,
  downloadSupplementsOnly,
  type DownloadBatchOptions,
} from "./batch.js";
import { asWindowBatch } from "./batchSummary.js";

function jsonTextResponse(text: string) {
  return {
    content: [
      {
        type: "text" as const,
        text,
      },
    ],
  };
}

/**
 * The folder of this download (runDownloadFolder). A caller's own serial batch, several calls with one batch id,
 * keeps the folder its first call got: remembered for two days in the run ledger's batch-folders.json. With the
 * ledger turned off every call gets its own folder.
 */
export function downloadRunFolder(savePath?: string, batchId?: string, now: Date = new Date()): string {
  const root = batchId ? resolveRunLogRoot() : null;
  if (!batchId || !root) return runDownloadFolder(savePath, now);
  const file = join(root, "batch-folders.json");
  let known: Record<string, { folder: string; at: number }> = {};
  if (existsSync(file)) {
    try {
      known = JSON.parse(readFileSync(file, "utf8"));
    } catch {
      // Only this function writes the file; an unreadable one starts afresh.
      known = {};
    }
  }
  const key = `${resolveDownloadPath(savePath)}\n${batchId}`;
  if (known[key]) return known[key].folder;
  const folder = runDownloadFolder(savePath, now);
  for (const [k, v] of Object.entries(known)) if (now.getTime() - v.at > 2 * 86_400_000) delete known[k];
  known[key] = { folder, at: now.getTime() };
  mkdirSync(root, { recursive: true });
  writeFileSync(file, `${JSON.stringify(known, null, 2)}\n`);
  return folder;
}

/**
 * Where a batch's own files go (its run records, the window's folder): this run's folder, or, when every paper
 * has a folder of its own (the user's grouping by topic, 2026-11-11), the folder they all sit in. Such papers
 * are saved where they were told; no run folder holds only the run records.
 */
export function batchSaveFolder(options: DownloadBatchOptions, now: Date = new Date()): string {
  const own = options.items.map((item) => item.savePath?.trim() ?? "");
  if (own.length && own.every(Boolean)) {
    const common = commonFolder(own.map((path) => resolve(resolveDownloadPath(path))));
    if (common) return common;
  }
  return downloadRunFolder(options.savePath, undefined, now);
}

/** The deepest folder holding every (absolute) path, below the drive or file-system root (none on another drive). */
function commonFolder(paths: string[]): string | undefined {
  const fold = (path: string) => (sep === "\\" ? path.toLowerCase() : path);
  const within = (path: string, folder: string) =>
    fold(path) === fold(folder) || fold(path).startsWith(fold(folder.endsWith(sep) ? folder : folder + sep));
  for (let folder = paths[0]; ; folder = dirname(folder)) {
    if (parse(folder).root === folder) return undefined;
    if (paths.every((path) => within(path, folder))) return folder;
  }
}

/** One download recorded as its own run in the local run ledger. */
async function recordedDownload(
  options: DownloadWithFallbackOptions,
  download: (options: DownloadWithFallbackOptions & { savePath: string }) => Promise<DownloadWithFallbackResult>,
): Promise<DownloadWithFallbackResult> {
  options = { ...options, savePath: resolveDownloadPath(options.savePath) };
  const ledger = RunLedger.open({
    kind: "download",
    total: 1,
    ...(options.batch ? { batchId: options.batch.id } : {}),
    ...(options.savePath ? { savePath: options.savePath } : {}),
  });
  if (!ledger) return download({ ...options, savePath: options.savePath! });
  const item = {
    index: options.batch?.index ?? 1,
    paperId: options.paperId,
    ...(options.doi ? { doi: options.doi } : {}),
    ...(options.title ? { title: options.title } : {}),
  };
  const result = await download({ ...options, savePath: options.savePath!, onStage: (record) => ledger.stage(item, record),
    recordsDir: ledger.records, diagnosticsDir: ledger.diagnostics });
  ledger.item(item, result);
  ledger.close();
  return { ...result, runLog: ledger.dir };
}

export async function handleDownloadPaper(
  args: {
    paperId: string;
    platform: string;
    savePath?: string;
    useEntitledAccess?: boolean;
  },
  searchers: Searchers,
  schoolBackend?: SchoolBackend,
) {
  const { paperId, platform, savePath, useEntitledAccess } = args;
  const resolvedSavePath = downloadRunFolder(savePath);
  const resolvedPlatform = resolvePlatformId(platform);

  const result = await recordedDownload(
    {
      source: resolvedPlatform,
      paperId,
      doi: paperId,
      savePath: resolvedSavePath,
      useEntitledAccess,
      useSciHub: true,
    },
    (options) => asWindowBatch(options, schoolBackend,
      (windowed) => downloadWithFallback(searchers, windowed, createDefaultDownloadTiers(schoolBackend))),
  );
  return jsonTextResponse(
    `Download paper ${result.status}.\n\n${JSON.stringify(result, null, 2)}`,
  );
}

export async function handleDownloadWithFallback(
  args: Parameters<typeof downloadWithFallback>[1],
  searchers: Searchers,
  schoolBackend?: SchoolBackend,
) {
  args = { ...args, savePath: downloadRunFolder(args.savePath, args.batch?.id) };
  const tiers = createDefaultDownloadTiers(schoolBackend);
  // A caller's own serial batch reports each item; a lone download is a batch of one.
  const download = async (options: DownloadWithFallbackOptions, callerBatch: boolean) => {
    if (options.content === "supplements") return downloadSupplementsOnly(options, schoolBackend, searchers);
    const outcome = callerBatch && options.batch
      ? await downloadBatchItem(searchers, { ...options, batch: options.batch }, tiers, schoolBackend)
      : await downloadWithFallback(searchers, options, tiers);
    if (options.content === "both" && outcome.status === "ok" && !outcome.supplements) {
      // The main text came from an open stage: supplementary files only.
      const extra = await downloadSupplementsOnly({ ...options, ...(outcome.publishedDoi ? { doi: outcome.publishedDoi } : {}) }, schoolBackend, searchers, outcome.path && !outcome.version ? outcome.path : undefined);
      if (extra.supplements) return { ...outcome, supplements: extra.supplements, ...(extra.path ? { path: extra.path } : {}) };
    }
    return outcome;
  };
  const result = await recordedDownload(args, (options) => options.batch
    ? download(options, true)
    : asWindowBatch(options, schoolBackend, (windowed) => download(windowed, false)));
  return jsonTextResponse(
    `Download with fallback ${result.status}.\n\n${JSON.stringify(result, null, 2)}`,
  );
}

export async function handleDownloadBatch(
  args: DownloadBatchOptions,
  searchers: Searchers,
  schoolBackend?: SchoolBackend,
) {
  const result = await downloadBatch(searchers, { ...args, savePath: batchSaveFolder(args) }, schoolBackend);
  return jsonTextResponse(
    `Download batch ${result.status}: ${result.succeeded}/${result.total} succeeded.\n\n${JSON.stringify(result, null, 2)}`,
  );
}
