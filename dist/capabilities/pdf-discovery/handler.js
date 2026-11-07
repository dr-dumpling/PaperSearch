import { resolveDownloadPath } from "../../config/ConfigService.js";
import { dirname } from "node:path";
import { resolvePlatformId } from "../../registry/platformMetadata.js";
import { createDefaultDownloadTiers, downloadWithFallback, } from "./OpenAccessFallbackService.js";
import { RunLedger } from "../../infrastructure/runlog/RunLedger.js";
import { downloadBatch, downloadBatchItem, downloadSupplementsOnly, } from "./batch.js";
import { asWindowBatch } from "./batchSummary.js";
function jsonTextResponse(text) {
    return {
        content: [
            {
                type: "text",
                text,
            },
        ],
    };
}
/** One download recorded as its own run in the local run ledger. */
async function recordedDownload(options, download) {
    options = { ...options, savePath: resolveDownloadPath(options.savePath) };
    const ledger = RunLedger.open({
        kind: "download",
        total: 1,
        ...(options.batch ? { batchId: options.batch.id } : {}),
        ...(options.savePath ? { savePath: options.savePath } : {}),
    });
    if (!ledger)
        return download({ ...options, savePath: options.savePath });
    const item = {
        index: options.batch?.index ?? 1,
        paperId: options.paperId,
        ...(options.doi ? { doi: options.doi } : {}),
        ...(options.title ? { title: options.title } : {}),
    };
    const result = await download({ ...options, savePath: options.savePath, onStage: (record) => ledger.stage(item, record) });
    ledger.item(item, result);
    ledger.close();
    return { ...result, runLog: ledger.dir };
}
export async function handleDownloadPaper(args, searchers, carsiBackend) {
    const { paperId, platform, savePath, useEntitledAccess } = args;
    const resolvedSavePath = resolveDownloadPath(savePath);
    const resolvedPlatform = resolvePlatformId(platform);
    const result = await recordedDownload({
        source: resolvedPlatform,
        paperId,
        doi: paperId,
        savePath: resolvedSavePath,
        useEntitledAccess,
        useSciHub: true,
    }, (options) => asWindowBatch(options, carsiBackend, (windowed) => downloadWithFallback(searchers, windowed, createDefaultDownloadTiers(carsiBackend))));
    return jsonTextResponse(`Download paper ${result.status}.\n\n${JSON.stringify(result, null, 2)}`);
}
export async function handleDownloadWithFallback(args, searchers, carsiBackend) {
    const tiers = createDefaultDownloadTiers(carsiBackend);
    // A caller's own serial batch reports each item; a lone download is a batch of one.
    const download = async (options, callerBatch) => {
        if (options.content === "supplements")
            return downloadSupplementsOnly(options, carsiBackend, searchers);
        const outcome = callerBatch && options.batch
            ? await downloadBatchItem(searchers, { ...options, batch: options.batch }, tiers, carsiBackend)
            : await downloadWithFallback(searchers, options, tiers);
        if (options.content === "both" && outcome.status === "ok" && !outcome.supplements) {
            // The main text came from an open stage: supplementary files only.
            const extra = await downloadSupplementsOnly({ ...options, ...(outcome.publishedDoi ? { doi: outcome.publishedDoi } : {}) }, carsiBackend, searchers, outcome.path && !outcome.version ? dirname(outcome.path) : undefined);
            if (extra.supplements)
                return { ...outcome, supplements: extra.supplements };
        }
        return outcome;
    };
    const result = await recordedDownload(args, (options) => options.batch
        ? download(options, true)
        : asWindowBatch(options, carsiBackend, (windowed) => download(windowed, false)));
    return jsonTextResponse(`Download with fallback ${result.status}.\n\n${JSON.stringify(result, null, 2)}`);
}
export async function handleDownloadBatch(args, searchers, carsiBackend) {
    const result = await downloadBatch(searchers, args, carsiBackend);
    return jsonTextResponse(`Download batch ${result.status}: ${result.succeeded}/${result.total} succeeded.\n\n${JSON.stringify(result, null, 2)}`);
}
//# sourceMappingURL=handler.js.map