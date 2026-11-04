import { dirname } from "node:path";
import type { Searchers } from "../../core/searchers.js";
import { resolvePlatformId } from "../../registry/platformMetadata.js";
import {
  createDefaultDownloadTiers,
  downloadWithFallback,
} from "./OpenAccessFallbackService.js";
import type { CarsiBackend } from "./carsi/index.js";

import { RunLedger } from "../../infrastructure/runlog/RunLedger.js";
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

/** One download recorded as its own run in the local run ledger. */
async function recordedDownload(
  options: DownloadWithFallbackOptions,
  download: (options: DownloadWithFallbackOptions) => Promise<DownloadWithFallbackResult>,
): Promise<DownloadWithFallbackResult> {
  const ledger = RunLedger.open({
    kind: "download",
    total: 1,
    ...(options.batch ? { batchId: options.batch.id } : {}),
    ...(options.savePath ? { savePath: options.savePath } : {}),
  });
  if (!ledger) return download(options);
  const item = {
    index: options.batch?.index ?? 1,
    paperId: options.paperId,
    ...(options.doi ? { doi: options.doi } : {}),
    ...(options.title ? { title: options.title } : {}),
  };
  const result = await download({ ...options, onStage: (record) => ledger.stage(item, record) });
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
  carsiBackend?: CarsiBackend,
) {
  const { paperId, platform, savePath, useEntitledAccess } = args;
  const resolvedSavePath = savePath || "./downloads";
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
    (options) => downloadWithFallback(searchers, options, createDefaultDownloadTiers(carsiBackend)),
  );
  return jsonTextResponse(
    `Download paper ${result.status}.\n\n${JSON.stringify(result, null, 2)}`,
  );
}

export async function handleDownloadWithFallback(
  args: Parameters<typeof downloadWithFallback>[1],
  searchers: Searchers,
  carsiBackend?: CarsiBackend,
) {
  const tiers = createDefaultDownloadTiers(carsiBackend);
  const result = await recordedDownload(args, async (options) => {
    if (options.content === "supplements") return downloadSupplementsOnly(options, carsiBackend, searchers);
    const outcome = options.batch
      ? await downloadBatchItem(searchers, { ...options, batch: options.batch }, tiers, carsiBackend)
      : await downloadWithFallback(searchers, options, tiers);
    if (options.content === "both" && outcome.status === "ok" && !outcome.supplements) {
      // The main text came from an open stage: supplementary files only.
      const extra = await downloadSupplementsOnly({ ...options, ...(outcome.publishedDoi ? { doi: outcome.publishedDoi } : {}) }, carsiBackend, searchers, outcome.path && !outcome.version ? dirname(outcome.path) : undefined);
      if (extra.supplements) return { ...outcome, supplements: extra.supplements };
    }
    return outcome;
  });
  return jsonTextResponse(
    `Download with fallback ${result.status}.\n\n${JSON.stringify(result, null, 2)}`,
  );
}

export async function handleDownloadBatch(
  args: DownloadBatchOptions,
  searchers: Searchers,
  carsiBackend?: CarsiBackend,
) {
  const result = await downloadBatch(searchers, args, carsiBackend);
  return jsonTextResponse(
    `Download batch ${result.status}: ${result.succeeded}/${result.total} succeeded.\n\n${JSON.stringify(result, null, 2)}`,
  );
}
