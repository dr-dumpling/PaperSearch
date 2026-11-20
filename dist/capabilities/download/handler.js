import { resolveDownloadPath, runDownloadFolder } from "../../config/ConfigService.js";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, parse, resolve, sep } from "node:path";
import { resolvePlatformId } from "../../registry/platformMetadata.js";
import { createDefaultDownloadTiers, downloadWithFallback, } from "./content/pdf/OpenAccessFallbackService.js";
import { RunLedger, resolveRunLogRoot } from "../../infrastructure/runlog/RunLedger.js";
import { contentKinds, } from "./types.js";
import { batchStopped, downloadBatch, downloadBatchItem, } from "./batch/batch.js";
import { asWindowBatch } from "./batch/batchSummary.js";
import { batchFolderName, INDEX_FILE, RUN_FOLDER } from "./batch/batchFolder.js";
import { supplementShortfall } from "./content/supplements/shortfall.js";
import { fulltextAlone, fulltextForItem } from "./content/markdown/step.js";
import { planResume } from "./batch/resume.js";
import { fulltextPageVisit } from "./content/markdown/pageVisit.js";
import { loadMarkdownPro } from "./content/markdown/pro.js";
import { proFeatures } from "../../config/edition.js";
import { downloadSupplementsOnly } from "./content/supplements/fetch.js";
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
/**
 * Where a batch's own files go (its run records, the window's folder): this run's folder, or, when every paper
 * has a folder of its own (the user's grouping by topic, 2026-11-11), the folder they all sit in. Such papers
 * are saved where they were told; no run folder holds only the run records.
 */
export function batchSaveFolder(options, now = new Date()) {
    // A folder named for the batch (Osteoarthritis Cartilage_2024-2026) in the download folder: its papers straight
    // inside it, beside its records (batchFolder.ts, user 2026-11-17).
    const named = batchFolderName(options.folderName);
    if (named)
        return join(resolve(resolveDownloadPath(options.savePath)), named);
    const own = options.items.map((item) => item.savePath?.trim() ?? "");
    if (own.length && own.every(Boolean)) {
        const common = commonFolder(own.map((path) => resolve(resolveDownloadPath(path))));
        if (common)
            return common;
    }
    return downloadRunFolder(options.savePath, undefined, now);
}
/** The deepest folder holding every (absolute) path, below the drive or file-system root (none on another drive). */
function commonFolder(paths) {
    const fold = (path) => (sep === "\\" ? path.toLowerCase() : path);
    const within = (path, folder) => fold(path) === fold(folder) || fold(path).startsWith(fold(folder.endsWith(sep) ? folder : folder + sep));
    for (let folder = paths[0];; folder = dirname(folder)) {
        if (parse(folder).root === folder)
            return undefined;
        if (paths.every((path) => within(path, folder)))
            return folder;
    }
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
        recordsDir: ledger.records, diagnosticsDir: ledger.diagnostics });
    ledger.item(item, result);
    ledger.close();
    return { ...result, runLog: ledger.dir };
}
export async function handleDownloadPaper(args, searchers, schoolBackend) {
    const { paperId, platform, savePath, useEntitledAccess, fulltext } = args;
    const content = args.content === "markdown" ? "markdown" : undefined;
    // The Markdown is PaperSearch Pro's: known before the download whether it can be made.
    if (fulltext || content)
        await loadMarkdownPro();
    const resolvedSavePath = downloadRunFolder(savePath);
    const resolvedPlatform = resolvePlatformId(platform);
    const result = await recordedDownload({
        source: resolvedPlatform,
        paperId,
        doi: paperId,
        savePath: resolvedSavePath,
        useEntitledAccess,
        useSciHub: true,
        ...(content ? { content } : {}),
        ...(fulltext || content ? { fulltext: true } : {}),
    }, (options) => asWindowBatch(options, schoolBackend, async (windowed) => {
        const tiers = createDefaultDownloadTiers(schoolBackend);
        if (windowed.content === "markdown") {
            return fulltextAlone({ status: "error", attempts: [] }, windowed, searchers, fulltextPageVisit(schoolBackend, windowed));
        }
        const outcome = await downloadWithFallback(searchers, windowed, tiers);
        await fulltextForItem(outcome, windowed, searchers, fulltextPageVisit(schoolBackend, windowed));
        return outcome;
    }));
    return jsonTextResponse(`Download paper ${result.status}.\n\n${JSON.stringify(result, null, 2)}`);
}
export async function handleDownloadWithFallback(args, searchers, schoolBackend) {
    args = { ...args, savePath: downloadRunFolder(args.savePath, args.batch?.id) };
    if (args.fulltext || args.content === "markdown")
        await loadMarkdownPro();
    const tiers = createDefaultDownloadTiers(schoolBackend);
    // A caller's own serial batch reports each item; a lone download is a batch of one.
    const download = async (options, callerBatch) => {
        const mainText = (mainOptions) => callerBatch && mainOptions.batch
            ? downloadBatchItem(searchers, { ...mainOptions, batch: mainOptions.batch }, tiers, schoolBackend)
            : downloadWithFallback(searchers, mainOptions, tiers);
        // Each kind on its own (user, 2026-11-14): the Markdown without the PDF is the full-text
        // package, no PDF in its place (user, 2026-11-16); beside supplementary files it reads
        // the page their visit opened.
        if (options.content === "markdown") {
            return fulltextAlone({ status: "error", attempts: [] }, options, searchers, fulltextPageVisit(schoolBackend, options));
        }
        if (options.content === "supplements") {
            const files = await downloadSupplementsOnly(options, schoolBackend, searchers);
            return options.fulltext ? fulltextAlone(files, options, searchers, fulltextPageVisit(schoolBackend, options)) : files;
        }
        const outcome = await mainText(options);
        if (options.content === "both" && outcome.status === "ok" && !outcome.supplements) {
            // The main text came from an open stage: supplementary files only.
            const extra = await downloadSupplementsOnly({ ...options, ...(outcome.publishedDoi ? { doi: outcome.publishedDoi } : {}) }, schoolBackend, searchers, outcome.path && !outcome.version ? outcome.path : undefined);
            if (extra.supplements) {
                const withFiles = { ...outcome, supplements: extra.supplements, ...(extra.path ? { path: extra.path } : {}),
                    ...(extra.fulltextPage ? { fulltextPage: extra.fulltextPage } : {}) };
                await fulltextForItem(withFiles, options, searchers, fulltextPageVisit(schoolBackend, options));
                return withFiles;
            }
        }
        await fulltextForItem(outcome, options, searchers, fulltextPageVisit(schoolBackend, options));
        return outcome;
    };
    const result = await recordedDownload(args, (options) => options.batch
        ? download(options, true)
        : asWindowBatch(options, schoolBackend, (windowed) => download(windowed, false)));
    return jsonTextResponse(`Download with fallback ${result.status}.\n\n${JSON.stringify(result, null, 2)}`);
}
/**
 * A batch as the caller is told it (user, 2026-11-17): its totals, how many papers lack their
 * Markdown or supplementary files, and where each paper's result is (_run/article_index.csv),
 * not every paper. A batch of hundreds came back as a megabyte (466 papers, 1 MB) that AI tools
 * cut short; each paper's result stands in the list and the run's records.
 */
function batchOutcome(result, folder, content) {
    const { items, ...totals } = result;
    const index = join(folder, RUN_FOLDER, INDEX_FILE);
    const markdownMissing = items.filter((item) => item.markdown && item.markdown.status !== "ok").length;
    const supplementsMissing = items.filter((item) => supplementShortfall(item)).length;
    // Saved, its checks against a registered site's page finding something short: to look over (user, 2026-11-17).
    const markdownPossiblyShort = items.filter((item) => item.status === "ok" && item.markdown?.possiblyMissing).length;
    return {
        ...totals,
        content,
        folder,
        ...(existsSync(index) ? { index } : {}),
        ...(markdownMissing ? { markdownMissing } : {}),
        ...(markdownPossiblyShort ? { markdownPossiblyShort } : {}),
        ...(supplementsMissing ? { supplementsMissing } : {}),
    };
}
export async function handleDownloadBatch(args, searchers, schoolBackend) {
    if (args.resume?.trim())
        return resumeBatch(args, args.resume.trim(), searchers, schoolBackend);
    const { folderName: _name, markdownAgain: _again, ...batch } = args;
    const folder = batchSaveFolder(args);
    const result = await downloadBatch(searchers, { ...batch, savePath: folder }, schoolBackend);
    // The kinds as the caller named them (pdf, supplements, markdown).
    const shown = batchOutcome(result, folder, contentKinds(result.content, args.fulltext));
    return jsonTextResponse(`Download batch ${result.status}: ${result.succeeded}/${result.total} succeeded.` +
        `${shown.index ? ` Each paper: ${shown.index}` : ""}\n\n${JSON.stringify(shown, null, 2)}`);
}
/**
 * Without PaperSearch Pro's features (config/edition.ts) a batch's Markdown is left out (a batch from a
 * version with it): the papers missing only their Markdown are complete, and a batch that asked for
 * the Markdown alone gets the PDF of the papers it did not save.
 */
function withoutMarkdown(plan) {
    const key = (item) => (item.doi || item.paperId || "").toLowerCase();
    const files = new Set(plan.files.map(key));
    return { ...plan, markdown: [], fulltext: false, content: plan.content === "markdown" ? "main" : plan.content,
        complete: plan.complete + plan.markdown.filter((item) => !files.has(key(item))).length };
}
/**
 * 接着下 (resume.ts): an earlier batch's papers not saved, again, then what those saved are
 * still missing, their supplementary files, their Markdown or both in one visit, into its
 * download folder (user, 2026-11-15).
 */
async function resumeBatch(args, which, searchers, schoolBackend) {
    // Which sites PaperSearch Pro has rules for decides the Markdown to fill (resume.ts).
    await loadMarkdownPro();
    const planned = planResume(which, process.env, args.markdownAgain ? { markdownAgain: args.markdownAgain } : {});
    if (typeof planned === "string")
        return jsonTextResponse(`Nothing to go on with: ${planned}`);
    const plan = proFeatures() ? planned : withoutMarkdown(planned);
    // The school the batch used, unless the user names another for this run.
    const school = args.school?.trim() || plan.school;
    // So too how it went (entitled_only: through the school alone), unless this run says (user, 2026-11-17).
    const mode = args.mode ?? plan.mode;
    const common = { savePath: plan.folder, resumeOf: plan.runId, useEntitledAccess: args.useEntitledAccess,
        useSciHub: args.useSciHub, ...(mode ? { mode } : {}), ...(school ? { school } : {}) };
    const papers = plan.retry.length
        ? await downloadBatch(searchers, { ...common, items: plan.retry, content: plan.content, fulltext: plan.fulltext }, schoolBackend)
        : undefined;
    // Stopped in the window: nothing more after it.
    let stopped = !!papers && batchStopped(papers);
    const key = (item) => (item.doi || item.paperId || "").toLowerCase();
    const withMarkdown = new Set(plan.markdown.map(key));
    const withFiles = new Set(plan.files.map(key));
    const fills = [
        { got: "their files and Markdown", items: plan.files.filter((item) => withMarkdown.has(key(item))), content: "supplements", fulltext: true },
        { got: "their files", items: plan.files.filter((item) => !withMarkdown.has(key(item))), content: "supplements", fulltext: false },
        { got: "their Markdown", items: plan.markdown.filter((item) => !withFiles.has(key(item))), content: "markdown", fulltext: true },
    ];
    const filled = [];
    for (const fill of fills) {
        if (!fill.items.length || stopped)
            continue;
        const result = await downloadBatch(searchers, { ...common, items: [...fill.items], content: fill.content, fulltext: fill.fulltext }, schoolBackend);
        filled.push({ got: fill.got, fulltext: fill.fulltext, result });
        stopped = batchStopped(result);
    }
    const summary = { from: plan.runId, folder: plan.folder, content: contentKinds(plan.content, plan.fulltext),
        complete: plan.complete, retried: plan.retry.length, ...(plan.unreached ? { notReached: plan.unreached } : {}),
        filesOnly: plan.files.length, markdownOnly: plan.markdown.length };
    const said = !papers && !filled.length ? "every paper of it is complete"
        : [papers && `${papers.succeeded}/${papers.total} papers saved`,
            ...filled.map(({ got, result }) => `${result.succeeded}/${result.total} papers got ${got}`)].filter(Boolean).join("; ");
    const outcome = (result, fulltext) => batchOutcome(result, plan.folder, contentKinds(result.content, fulltext));
    return jsonTextResponse(`Went on with ${plan.runId}: ${said}.\n\n${JSON.stringify({ resume: summary,
        ...(papers ? { papers: outcome(papers, plan.fulltext) } : {}),
        ...(filled.length ? { filled: filled.map(({ result, fulltext }) => outcome(result, fulltext)) } : {}) }, null, 2)}`);
}
//# sourceMappingURL=handler.js.map