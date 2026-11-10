import { resolveDownloadPath, runDownloadFolder } from "../../config/ConfigService.js";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { resolvePlatformId } from "../../registry/platformMetadata.js";
import { createDefaultDownloadTiers, downloadWithFallback, } from "./OpenAccessFallbackService.js";
import { RunLedger, resolveRunLogRoot } from "../../infrastructure/runlog/RunLedger.js";
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
/**
 * The folder of this download (runDownloadFolder). A caller's own serial batch, several calls with one batch id,
 * keeps the folder its first call got: remembered for two days in the run ledger's batch-folders.json. With the
 * ledger turned off every call gets its own folder.
 */
export function downloadRunFolder(savePath, batchId, now = new Date()) {
    const root = batchId ? resolveRunLogRoot() : null;
    if (!batchId || !root)
        return runDownloadFolder(savePath, now);
    const file = join(root, "batch-folders.json");
    let known = {};
    if (existsSync(file)) {
        try {
            known = JSON.parse(readFileSync(file, "utf8"));
        }
        catch {
            // Only this function writes the file; an unreadable one starts afresh.
            known = {};
        }
    }
    const key = `${resolveDownloadPath(savePath)}\n${batchId}`;
    if (known[key])
        return known[key].folder;
    const folder = runDownloadFolder(savePath, now);
    for (const [k, v] of Object.entries(known))
        if (now.getTime() - v.at > 2 * 86_400_000)
            delete known[k];
    known[key] = { folder, at: now.getTime() };
    mkdirSync(root, { recursive: true });
    writeFileSync(file, `${JSON.stringify(known, null, 2)}\n`);
    return folder;
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
    const result = await download({ ...options, savePath: options.savePath, onStage: (record) => ledger.stage(item, record),
        recordsDir: ledger.records });
    ledger.item(item, result);
    ledger.close();
    return { ...result, runLog: ledger.dir };
}
export async function handleDownloadPaper(args, searchers, carsiBackend) {
    const { paperId, platform, savePath, useEntitledAccess } = args;
    const resolvedSavePath = downloadRunFolder(savePath);
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
    args = { ...args, savePath: downloadRunFolder(args.savePath, args.batch?.id) };
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
    const result = await downloadBatch(searchers, { ...args, savePath: downloadRunFolder(args.savePath) }, carsiBackend);
    return jsonTextResponse(`Download batch ${result.status}: ${result.succeeded}/${result.total} succeeded.\n\n${JSON.stringify(result, null, 2)}`);
}
//# sourceMappingURL=handler.js.map