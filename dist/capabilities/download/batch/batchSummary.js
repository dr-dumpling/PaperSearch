import { randomUUID } from "node:crypto";
import { dirname, isAbsolute } from "node:path";
import { sanitizeDoi } from "../../../infrastructure/security/SecurityUtils.js";
import { classifyFailureCode } from "../../../infrastructure/runlog/failureClass.js";
import { schoolShortReason } from "../../../infrastructure/school/index.js";
import { supplementsMissing } from "../content/supplements/shortfall.js";
import { markdownDoubt, markdownMissing, unverifiedNote } from "../content/markdown/shortfall.js";
import { markdownPro } from "../content/markdown/pro.js";
/**
 * Where a saved main text came from, as the finished window names it: the two
 * ways of downloading (the guide's 开放下载 and 机构下载, the batch's two lanes),
 * the open one's sources other than open access in brackets (user, 2026-11-10).
 */
const OPEN_DOWNLOAD = "开放下载";
const ENTITLED_DOWNLOAD = "机构下载";
const OPEN_DETAILS = {
    publisher_api: "出版社 API",
    scihub: "Sci-Hub",
    preprint: "预印本",
    elsevier_api: "出版社 API",
};
/** Not saved because the user stopped the batch: not a failure of the paper (2026-11-16). */
export function stoppedItem(item) {
    return item.status !== "ok" && item.attempts.some((attempt) => attempt.code === "batch_stopped");
}
/**
 * Tell the progress window how the whole batch ended: what was saved, and
 * each failure's class and reason in a few words. Sent once, after every
 * stage (open, institutional, supplementary files); the window is optional,
 * so this never changes the batch result.
 */
export async function reportBatchResults(result, backend, startedAt, folder) {
    if (!backend?.reportBatchProgress || result.total < 1)
        return;
    try {
        await backend.reportBatchProgress({
            id: result.batchId,
            total: result.total,
            done: result.total,
            succeeded: result.succeeded,
            failed: result.failed,
            finished: true,
            results: batchResults(result, startedAt, folder),
        });
    }
    catch {
        // The progress window is optional; it never changes a download outcome.
    }
}
/**
 * One download outside a batch, run as a batch of one so the progress window
 * ends with the same finished card (its reason when it failed). Reported only
 * when the download reached the backend; an open-access copy opens no window.
 */
export async function asWindowBatch(options, backend, download) {
    if (!backend?.reportBatchProgress)
        return download(options);
    const startedAt = Date.now();
    const batch = { id: randomUUID(), index: 1, total: 1, done: 0, succeeded: 0, failed: 0 };
    const result = await download({ ...options, batch });
    const reachedBackend = result.supplements !== undefined || result.markdown?.source === "publisher_page" || result.attempts.some((attempt) => attempt.stage === "entitled_access" && attempt.status !== "skipped");
    if (!reachedBackend)
        return result;
    const ok = result.status === "ok";
    await reportBatchResults({
        status: ok ? "ok" : "error",
        mode: "per_item",
        content: options.content ?? "main",
        batchId: batch.id,
        total: 1,
        succeeded: ok ? 1 : 0,
        failed: ok ? 0 : 1,
        items: [{ ...result, index: 1, paperId: options.paperId, ...(options.doi ? { doi: options.doi } : {}) }],
    }, backend, startedAt, result.path && !result.version ? dirname(result.path) : options.savePath);
    return result;
}
export function batchResults(result, startedAt, folder) {
    const sources = new Map();
    const details = new Map();
    const summary = {
        // The Markdown alone is counted as Markdown (a backend before it shows it as the main text).
        content: result.content,
        folder,
        started: Math.floor(startedAt / 1000),
        stopped: false,
        main: 0,
        supplements: 0,
        no_supplements: 0,
        sources: [],
        failures: [],
        supplement_failures: [],
    };
    // The Markdown beside the PDF or the files: how many papers got their article.md (the
    // Markdown alone is the main count, which the card names Markdown).
    if (result.content !== "markdown" && result.items.some((item) => item.markdown)) {
        summary.markdown = result.items.filter((item) => item.markdown?.status === "ok").length;
    }
    // Saved without their Markdown, and why: the count alone told the user nothing (2026-11-15).
    const noMarkdown = result.items.filter((item) => item.status === "ok" && item.markdown && item.markdown.status !== "ok");
    if (noMarkdown.length) {
        summary.markdown_failures = noMarkdown.map((item) => {
            const note = unverifiedNote(item.markdown);
            return {
                ...markdownMissing(item.markdown),
                ...(item.title ? { title: item.title } : {}),
                // A site's note says where it came from, in place of the journal (one line in the card).
                ...(item.journal && !note ? { journal: item.journal } : {}),
                ...(item.doi ? { doi: item.doi } : {}),
                ...(note ? { note, unverified: true } : {}),
            };
        });
    }
    // Saved with a Markdown its checks found short (a registered site's page, user 2026-11-17).
    const doubts = result.items.flatMap((item) => {
        const doubt = item.status === "ok" ? markdownDoubt(item.markdown) : undefined;
        return doubt ? [{ ...doubt, ...(item.title ? { title: item.title } : {}), ...(item.journal ? { journal: item.journal } : {}),
                ...(item.doi ? { doi: item.doi } : {}) }] : [];
    });
    if (doubts.length)
        summary.markdown_doubts = doubts;
    for (const item of result.items) {
        const saved = item.supplements?.filter((file) => file.status === "saved").length ?? 0;
        summary.supplements += saved;
        if (item.attempts.some((attempt) => attempt.code === "batch_stopped"))
            summary.stopped = true;
        // Left undone by the stop: counted apart, listed with the papers left (not as failed).
        if (stoppedItem(item)) {
            summary.stopped_count = (summary.stopped_count ?? 0) + 1;
            continue;
        }
        if (item.status === "ok") {
            // Checked, none listed: in the visit for the PDF (an empty list) or on its own.
            if (item.attempts.some((attempt) => attempt.code === "no_supplements")
                || (Array.isArray(item.supplements) && item.supplements.length === 0))
                summary.no_supplements += 1;
            const missing = supplementsMissing(item, result.content);
            if (missing) {
                summary.supplement_failures.push({
                    ...missing,
                    ...(item.title ? { title: item.title } : {}),
                    ...(item.journal ? { journal: item.journal } : {}),
                    ...(item.doi ? { doi: item.doi } : {}),
                });
            }
            if (result.content === "supplements" || !(item.path || item.markdown?.status === "ok"))
                continue;
            summary.main += 1;
            const [label, detail] = sourceLabel(item);
            sources.set(label, (sources.get(label) ?? 0) + 1);
            if (detail) {
                const said = details.get(label) ?? new Map();
                said.set(detail, (said.get(detail) ?? 0) + 1);
                details.set(label, said);
            }
            continue;
        }
        // The Markdown alone from a site not yet supported: its note in place of the journal.
        const site = result.content === "markdown" && item.markdown ? unverifiedNote(item.markdown) : undefined;
        summary.failures.push({
            ...failure(item, result.content),
            ...(item.title ? { title: item.title } : {}),
            ...(item.journal && !site ? { journal: item.journal } : {}),
            ...(item.doi ? { doi: item.doi } : {}),
            ...(saved ? { note: `附录 ${saved} 个已保存` } : {}),
            ...(site ? { note: site, unverified: true } : {}),
        });
    }
    summary.sources = [...sources].sort((a, b) => b[1] - a[1]);
    // Each label's sources: the open ones (Unpaywall, PubMed Central), the schools a 机构下载 went through.
    if (details.size) {
        summary.source_details = [...details].map(([label, said]) => [label, [...said].map(([name, n]) => `${name} ${n}`).join("、")]);
    }
    return summary;
}
/**
 * A paper for the window's lists (成功, 失败, 剩余): waiting in a lane, or its
 * result as the finished card tells it (the way it came, or why it failed).
 */
export function batchPaper(request, item, waiting, content, mainPath) {
    const paper = { doi: item?.doi ?? request.doi ?? "", title: item?.title ?? request.title ?? "", journal: item?.journal ?? "" };
    if (waiting || !item)
        return { ...paper, state: waiting ?? "open" };
    // Left undone by the stop: listed apart, not with the failed (user, 2026-11-16).
    if (stoppedItem(item))
        return { ...paper, state: "stopped" };
    if (item.status !== "ok")
        return { ...paper, state: "failed", ...failure(item, content), ...markdownSite(item) };
    const [via, detail] = sourceLabel(item);
    // The window's 失败 list also shows a saved paper still missing supplementary files (user, 2026-11-11).
    const missing = supplementsMissing(item, content);
    // A batch of the files alone: its PDF saved before is where the list shows the paper,
    // also when the page listed none (it said “这篇没有保存的文件”, 2026-11-16).
    const path = savedFile(item) ?? (mainPath && isAbsolute(mainPath) ? mainPath : undefined);
    // Its Markdown, when asked for and not saved: why.
    const missingMarkdown = item.markdown && item.markdown.status !== "ok" ? markdownMissing(item.markdown) : undefined;
    const doubt = markdownDoubt(item.markdown);
    const files = content === "supplements" && Array.isArray(item.supplements)
        ? item.supplements.filter((file) => file.status === "saved").length : undefined;
    return {
        ...paper, state: "ok", via, ...(detail ? { detail } : {}), ...(path ? { path } : {}),
        ...(files !== undefined ? { supplements_saved: files } : {}),
        ...(missing ? { supplement_cls: missing.cls, supplement_reason: missing.reason } : {}),
        ...(missingMarkdown ? { markdown_cls: missingMarkdown.cls, markdown_reason: missingMarkdown.reason } : {}),
        ...(doubt ? { markdown_doubt_reason: doubt.reason, markdown_doubt_note: doubt.note } : {}),
        ...markdownSite(item),
    };
}
/**
 * The file a listed paper opens at (its folder shown, the file selected): its PDF, else its
 * article.md, else its first supplementary file saved; a batch of the Markdown or the files
 * alone has no PDF (Windows, 2026-11-16).
 */
function savedFile(item) {
    return item.path || item.markdown?.file || item.supplements?.find((file) => file.status === "saved" && file.file)?.file;
}
/**
 * A page from a site not yet supported: its host, whether kept (or not tried: the batch gave
 * the site up), a note, the kept report.
 */
function markdownSite(item) {
    const markdown = item.markdown;
    if (!markdown?.unverified)
        return {};
    const note = unverifiedNote(markdown);
    const report = markdown.unverified.report;
    const rules = markdownPro()?.rulesName(markdown.unverified.template);
    return {
        markdown_host: markdown.unverified.host,
        markdown_saved: markdown.status === "ok",
        // Whose rules converted it (or came closest): the window says which were borrowed (user, 2026-11-17).
        ...(rules ? { markdown_rules: rules } : {}),
        ...(markdown.unverified.skipped ? { markdown_skipped: true } : {}),
        ...(note ? { markdown_note: note } : {}),
        ...(report && isAbsolute(report) ? { markdown_report: report } : {}),
    };
}
/** The way a main text came (and, for the open one, its source when not open access). */
function sourceLabel(item) {
    if (item.version === "preprint")
        return [OPEN_DOWNLOAD, OPEN_DETAILS.preprint];
    const ok = item.attempts.filter((attempt) => attempt.status === "ok");
    // The PDF's own step: the Markdown's or the files' come after it (a PDF through the school and its
    // Markdown from PubMed Central were listed as 开放下载, JAMA Netw Open, Windows 2026-11-19).
    const saved = [...ok].reverse().find((attempt) => attempt.stage !== "markdown" && attempt.stage !== "supplements");
    // Through a saved school other than the default one (没权限时换下一所学校, user 2026-11-21): its name.
    if (saved?.stage === "entitled_access") {
        return saved.school ? [ENTITLED_DOWNLOAD, saved.school] : [ENTITLED_DOWNLOAD];
    }
    if (saved)
        return [OPEN_DOWNLOAD, OPEN_DETAILS[saved.stage]];
    // The Markdown alone (content "markdown"): the school's page, or an open source or API.
    if (ok.some((attempt) => attempt.stage === "markdown")) {
        return item.markdown?.source === "publisher_page" ? [ENTITLED_DOWNLOAD] : [OPEN_DOWNLOAD, OPEN_DETAILS[item.markdown?.source ?? ""]];
    }
    return [OPEN_DOWNLOAD];
}
/** The failure's class (ADR 0012) and its reason in a few words, as the lists and the end line say it. */
export function failure(item, content) {
    if (content === "supplements") {
        const code = item.supplements?.find((file) => file.status !== "saved" && file.reason)?.reason;
        return { cls: classifyFailureCode(code), reason: schoolShortReason(code, "附录没下载成功") };
    }
    // The Markdown alone: why it was not saved (no PDF stands in for it, user 2026-11-16).
    if (content === "markdown" && item.markdown && !item.attempts.some((attempt) => attempt.code === "batch_stopped")) {
        return markdownMissing(item.markdown);
    }
    const entitled = [...item.attempts].reverse().find((attempt) => attempt.stage === "entitled_access");
    if (entitled && (entitled.status === "error" || entitled.code === "batch_stopped")) {
        // No access with every saved school tried (没权限时换下一所学校, user 2026-11-21).
        const reason = entitled.schools ? `${entitled.schools} 所学校都没有权限` : schoolShortReason(entitled.code);
        return { cls: classifyFailureCode(entitled.code), reason };
    }
    // Institutional access never ran for this item.
    return item.doi && sanitizeDoi(item.doi).valid
        ? { cls: classifyFailureCode("institutional_not_run"), reason: "没有进行机构下载" }
        : { cls: "unsupported", reason: "没有有效 DOI" };
}
//# sourceMappingURL=batchSummary.js.map