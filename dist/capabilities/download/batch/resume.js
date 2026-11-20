/**
 * 接着下: what an earlier batch left undone, from its run ledger, for one more batch into
 * the same download folder (user, 2026-11-15). A paper not saved is downloaded again with
 * the batch's content; a paper saved without all its supplementary files (missing, failed,
 * not reached when the batch stopped) or without its Markdown (not reached, failed, its
 * login lapsed) gets only those, beside its PDF. The runs that went on with a batch name it
 * (``resumeOf``): the batch and those runs are read together, the latest record of each
 * paper counting, so going on again asks only for what is still missing.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { resolveRunLogRoot } from "../../../infrastructure/runlog/RunLedger.js";
import { SCHOOL_UPDATE_NEEDED } from "../../../infrastructure/school/index.js";
import { markdownPro } from "../content/markdown/pro.js";
import { RUN_FOLDER } from "./batchFolder.js";
/** The stop's own entries: nothing was tried for these files. */
const NOT_TRIED = new Set(["batch_stopped", "user_skipped"]);
const notTried = (files) => files.length > 0 && files.every((file) => file.status !== "saved" && NOT_TRIED.has(String(file.reason ?? "")));
/**
 * A file not to ask for again: the site has no rule for its files, or listed none. A file once
 * past the size limit is asked for again: files written to disk have none since 2026-11-17.
 */
const FINAL_FILE_REASONS = new Set(["supplements_not_supported", "no_supplements"]);
/**
 * A Markdown not got for want of the login, an older extension or time (stopped), or not
 * kept for missing figures (user, 2026-11-16), not for want of a source: asked for again.
 * One with no source, or only an abstract, is not.
 */
const MARKDOWN_AGAIN_CODES = new Set([
    "login_timeout", "login_required", "sso_required", "login_not_reached", "institution_federation_unavailable",
    "idp_login_error", "idp_no_return_to_publisher", "captcha_required", "cloudflare_blocked", "download_timeout",
    "access_blocked", "rate_limited", "login_paused", SCHOOL_UPDATE_NEEDED, "batch_stopped", "user_skipped", "figures_missing",
    "institutional_not_run", "pmc_failed", "tables_missing", "page_not_saved",
    // PaperSearch Pro was not installed, or could not be used then: once it is, 接着下 makes them.
    "markdown_pro_required", "markdown_pro_key_required", "markdown_pro_offline", "markdown_pro_unavailable",
]);
/**
 * A page from a site without rules, asked for again: one never tried (before 2026-11-16 such a
 * page was not converted at all, "has no converter": 432 papers of an ARD batch), as every site
 * is tried now; one tried and not complete, once its site has rules.
 */
const NOW_SUPPORTED_CODES = new Set(["page_not_supported", "unverified_incomplete"]);
/** The site a Markdown stage's message names ("The page the browser saved (ard.eular.org) …", "ard.eular.org is not yet supported…"). */
function siteNamed(message) {
    return /\(([a-z0-9.-]+\.[a-z]{2,})\) has no converter/i.exec(message)?.[1]
        ?? /^([a-z0-9.-]+\.[a-z]{2,}) is not yet supported/i.exec(message)?.[1];
}
function markdownMissing(markdown) {
    if (markdown && NOW_SUPPORTED_CODES.has(markdown.code ?? "") && (markdown.untried || (markdown.host && markdownPro()?.hasRulesForUrl(`https://${markdown.host}/`))))
        return true;
    return !markdown || markdown.status === "error" || MARKDOWN_AGAIN_CODES.has(markdown.code ?? "");
}
function readJson(file) {
    try {
        const value = JSON.parse(readFileSync(file, "utf8"));
        return value && typeof value === "object" ? value : undefined;
    }
    catch {
        return undefined;
    }
}
function readPapers(dir) {
    const file = join(dir, "items.jsonl");
    if (!existsSync(file))
        return [];
    const papers = [];
    for (const line of readFileSync(file, "utf8").split("\n")) {
        if (!line.trim())
            continue;
        try {
            const item = JSON.parse(line);
            const markdown = (Array.isArray(item.stages) ? item.stages : [])
                .filter((stage) => stage.stage === "markdown").at(-1);
            const stages = (Array.isArray(item.stages) ? item.stages : []);
            const saved = stages.find((stage) => stage.status === "ok" && !["supplements", "markdown"].includes(String(stage.stage)));
            const failed = stages.filter((stage) => stage.status === "error" && stage.code && stage.stage !== "markdown").at(-1);
            papers.push({
                index: Number(item.index) || 0,
                doi: String(item.doi ?? ""),
                paperId: String(item.paperId ?? item.doi ?? ""),
                title: String(item.title ?? ""),
                status: String(item.status ?? ""),
                path: String(item.path ?? ""),
                ...(Array.isArray(item.supplements) ? { supplements: item.supplements } : {}),
                ...(markdown ? { markdown: { status: String(markdown.status ?? ""), ...(markdown.code ? { code: String(markdown.code) } : {}),
                        ...(siteNamed(String(markdown.message ?? "")) ? { host: siteNamed(String(markdown.message ?? "")) } : {}),
                        ...(/has no converter/i.test(String(markdown.message ?? "")) ? { untried: true } : {}),
                        ...(markdown.possiblyMissing && typeof markdown.possiblyMissing === "object" ? { possiblyMissing: markdown.possiblyMissing } : {}) } } : {}),
                ...(Array.isArray(item.stages) && item.stages.some((stage) => stage?.stage === "entitled_access"
                    && stage?.status === "ok") ? { byVisit: true } : {}),
                ...(item.status === "ok" && saved ? { source: String(saved.stage) } : {}),
                ...(item.status !== "ok" && failed ? { reason: String(failed.code) } : {}),
                ...(markdown?.status === "ok" && typeof markdown.path === "string" ? { markdownFile: markdown.path } : {}),
            });
        }
        catch {
            // A line cut short (a run ended mid-write): that paper is not counted as saved.
        }
    }
    return papers;
}
/**
 * The latest record of each paper over the runs in ``dirs`` (oldest first). A saved paper is
 * gone on with only for its files or Markdown: those runs change what they got, the saved PDF
 * stands.
 */
export function latestPapers(dirs) {
    const papers = new Map();
    for (const dir of dirs) {
        for (const paper of readPapers(dir)) {
            const key = (paper.doi || paper.paperId).toLowerCase();
            if (!key)
                continue;
            const before = papers.get(key);
            // A run the user stopped before it tried this paper's files leaves what was known (2026-11-16).
            const tried = paper.supplements !== undefined && !notTried(paper.supplements);
            papers.set(key, before?.status === "ok"
                ? { ...before, path: paper.path || before.path,
                    // Its PDF saved again (another batch into the same folder): where this one came from
                    // (a preprint went on listed after the published PDF replaced it, 2026-11-19).
                    ...(paper.status === "ok" && paper.source ? { source: paper.source, byVisit: paper.byVisit } : {}),
                    ...(tried ? { supplements: paper.supplements } : {}),
                    ...(paper.markdown ? { markdown: paper.markdown } : {}),
                    ...(paper.markdownFile ? { markdownFile: paper.markdownFile } : {}) }
                : { ...paper, index: before?.index ?? paper.index, path: paper.path || before?.path || "", title: paper.title || before?.title || "" });
        }
    }
    return papers;
}
/**
 * The papers the batch was asked for: its first run's own copy of its arguments in the batch's
 * folder (batchFolder.ts); none for a batch from before the folder kept them.
 */
function askedItems(folder, runId) {
    const args = readJson(join(folder, RUN_FOLDER, runId, "batch-args.json"));
    if (!Array.isArray(args?.items))
        return [];
    const text = (value) => (typeof value === "string" && value.trim() ? value.trim() : undefined);
    return args.items.flatMap((given) => {
        if (!given || typeof given !== "object")
            return [];
        const item = given;
        const fields = { source: text(item.source), paperId: text(item.paperId), doi: text(item.doi), title: text(item.title),
            savePath: text(item.savePath) };
        return [Object.fromEntries(Object.entries(fields).filter(([, value]) => value))];
    });
}
/** Download batches in the ledger root, oldest first (their folders sort by start time). */
function batchRuns(root) {
    if (!existsSync(root))
        return [];
    return readdirSync(root, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && /^\d{8}-\d{6}-/.test(entry.name))
        .map((entry) => entry.name)
        .sort()
        .map((name) => ({ name, run: readJson(join(root, name, "run.json")) ?? {} }))
        .filter(({ run }) => run.kind === "download_batch");
}
/**
 * What ``which`` ("latest", or a run id as ``paper-search failures`` names it) left undone;
 * a string saying why there is nothing to go on with otherwise.
 */
/**
 * ``markdownAgain: "possibly_short"``: the Markdown saved with a note of what it may lack
 * (possiblyMissing) is made again too, e.g. after the rules were fixed (user, 2026-11-18: 94
 * Cell papers saved before the tables' fix); a whole new package replaces it in the paper's folder.
 */
export function planResume(which, env = process.env, options = {}) {
    const root = resolveRunLogRoot(env);
    if (!root)
        return "运行记录已关闭（PAPER_SEARCH_RUNLOG=0），无法接着下。";
    const runs = batchRuns(root);
    const picked = which === "latest" ? runs.at(-1) : runs.find(({ name }) => name === which);
    if (!picked)
        return which === "latest" ? "没有找到批量下载的运行记录。" : `没有找到运行记录 ${which}。`;
    const first = String(picked.run.resumeOf || picked.name);
    const chain = runs.filter(({ name, run }) => name === first || run.resumeOf === first);
    const original = chain.find(({ name }) => name === first)?.run ?? picked.run;
    const folder = String(original.savePath ?? "");
    if (!folder)
        return `运行记录 ${first} 没有记下载文件夹，无法接着下。`;
    const papers = latestPapers(chain.map(({ name }) => join(root, name)));
    const content = ["main", "supplements", "both", "markdown"].find((kind) => kind === original.content)
        ?? ([...papers.values()].some((paper) => paper.supplements !== undefined) ? "both" : "main");
    const fulltext = content === "markdown" || original.fulltext === true
        || original.fulltext === undefined && [...papers.values()].some((paper) => paper.markdown);
    const retry = [];
    const files = [];
    const markdown = [];
    let complete = 0;
    const item = (paper) => ({
        ...(paper.doi ? { doi: paper.doi } : {}), paperId: paper.paperId, ...(paper.title ? { title: paper.title } : {}),
    });
    for (const paper of [...papers.values()].sort((a, b) => a.index - b.index)) {
        if (paper.status !== "ok") {
            retry.push(item(paper));
            continue;
        }
        // No record of its files after the institutional visit for its PDF: that visit checked the
        // page and it listed none; versions before 0.6.11 did not record an empty list (2026-11-16).
        const unchecked = paper.supplements === undefined && !paper.byVisit;
        const filesMissing = content === "both" && (unchecked
            || (paper.supplements ?? []).some((file) => file.status !== "saved" && !FINAL_FILE_REASONS.has(String(file.reason ?? ""))));
        const besides = { ...item(paper), ...(paper.path ? { mainPath: paper.path } : {}) };
        if (filesMissing)
            files.push(besides);
        const again = options.markdownAgain === "possibly_short" && paper.markdown?.status === "ok" && !!paper.markdown.possiblyMissing;
        if (fulltext && (markdownMissing(paper.markdown) || again))
            markdown.push(besides);
        else if (!filesMissing)
            complete += 1;
    }
    // A batch killed outright (Windows restarted for an update, 2026-11-19) recorded nothing of the
    // papers it had not reached: those of its list with no record are downloaded again too.
    let unreached = 0;
    const seen = new Set(papers.keys());
    for (const asked of askedItems(folder, first)) {
        const key = (asked.doi || asked.paperId || "").toLowerCase();
        if (!key || seen.has(key))
            continue;
        seen.add(key);
        retry.push(asked);
        unreached += 1;
    }
    const school = [...chain].reverse().map(({ run }) => run.school).find((name) => typeof name === "string" && !!name.trim());
    // The serial runs (supplements or Markdown alone) record their content as their mode, not a batch mode.
    const mode = [...chain].reverse().map(({ run }) => run.mode).find((value) => value === "two_phase" || value === "per_item" || value === "entitled_only");
    return { runId: first, folder, content, fulltext, ...(school ? { school } : {}), ...(mode ? { mode } : {}),
        retry, ...(unreached ? { unreached } : {}), files, markdown, complete };
}
//# sourceMappingURL=resume.js.map