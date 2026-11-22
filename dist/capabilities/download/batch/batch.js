import { resolveDownloadPath } from "../../../config/ConfigService.js";
import { randomUUID } from "node:crypto";
import { RunLedger } from "../../../infrastructure/runlog/RunLedger.js";
import { classifyFailureCode, FAILURE_CLASS_NAMES, } from "../../../infrastructure/runlog/failureClass.js";
import { createDefaultDownloadTiers, downloadWithFallback, } from "../content/pdf/OpenAccessFallbackService.js";
import { schoolAttemptDetails, schoolShortReason } from "../../../infrastructure/school/index.js";
import { journalOfDoi, takeNext } from "./journalKey.js";
import { downloadSupplementsOnly, filesPastNetworkLoss } from "../content/supplements/fetch.js";
import { supplementShortfall } from "../content/supplements/shortfall.js";
import { fulltextPageVisit } from "../content/markdown/pageVisit.js";
import { fulltextAlone, fulltextForItem, markdownBeside, markdownPastNetworkLoss } from "../content/markdown/step.js";
import { markdownDoubt, markdownMissing } from "../content/markdown/shortfall.js";
import { batchPaper, failure, reportBatchResults, stoppedItem } from "./batchSummary.js";
import { loadMarkdownPro, markdownBlocked } from "../content/markdown/pro.js";
import { PaperList } from "./batchPapers.js";
import { networkReachable, pastNetworkLoss } from "./networkLoss.js";
import { openBatchFolder } from "./batchFolder.js";
/** From this many items the progress window opens at the start, in the open-access stretch. */
export const OPEN_PROGRESS_MIN_ITEMS = 5;
/** Every source that needs no browser: open access, publisher APIs, Sci-Hub when on (the guide's 开放下载). */
const OPEN_CHANNEL = "开放下载";
/**
 * One item of a serial batch. When the item reaches the entitled-access
 * backend, the backend records it in its progress window itself; items that
 * finish earlier (open access, Sci-Hub) and the last item are reported with
 * the batch totals so the window always shows "k / N" for the whole batch.
 */
export async function downloadBatchItem(searchers, options, tiers, backend) {
    const result = await downloadWithFallback(searchers, options, tiers);
    await reportBatchItem(options, result, backend);
    return result;
}
async function reportBatchItem(options, result, backend) {
    const { batch } = options;
    if (!backend?.reportBatchProgress || rateLimitWait(result))
        return; // a waiting item runs again
    const reachedBackend = result.attempts.some((attempt) => attempt.stage === "entitled_access" && attempt.status !== "skipped");
    const finished = batch.index >= batch.total;
    if (reachedBackend && !finished)
        return;
    const ok = result.status === "ok";
    try {
        await backend.reportBatchProgress({
            id: batch.id,
            total: batch.total,
            done: batch.done + 1,
            succeeded: batch.succeeded + (ok ? 1 : 0),
            failed: batch.failed + (ok ? 0 : 1),
            current: options.doi || options.paperId,
            finished,
        });
    }
    catch {
        // The progress window is optional; it never changes a download outcome.
    }
}
function itemOptions(item, options) {
    const doi = item.doi?.trim() || "";
    return {
        preprintIds: [],
        source: item.source?.trim() || "crossref",
        paperId: item.paperId?.trim() || doi,
        doi,
        title: item.title?.trim() || "",
        savePath: item.savePath?.trim() || options.savePath,
        useEntitledAccess: options.useEntitledAccess,
        useSciHub: options.useSciHub,
        ...(options.content && options.content !== "main" ? { content: options.content } : {}),
        ...(options.fulltext ? { fulltext: true } : {}),
        ...(options.fulltext && options.mode === "entitled_only" ? { fulltextPageOnly: true } : {}),
        ...(options.school?.trim() ? { school: options.school.trim() } : {}),
    };
}
/**
 * A school login that lapsed, and nothing else: the paper's wait ran out (login_timeout) on
 * the school's own sign-in page, a password box or the school's sign-in step, as the backend
 * says where the wait ended (trace.loginWaitPage). After the publisher's earlier articles came
 * through the school, one such paper holds its papers (user, 2026-11-15). A wait that ended
 * on the publisher's pages or a redirect, the network, a verification or a timeout elsewhere
 * is no lapsed login: Science once stalled on its sign-in redirect and 152 papers waited for
 * nothing (Windows, 2026-11-15). A backend that does not say where its wait ended holds none.
 */
const LOGIN_LAPSED_CODE = "login_timeout";
const SCHOOL_SIGN_IN_PAGE = "school_login";
/** How often a batch waiting for the user to go on with held publishers asks its window. */
const HOLD_POLL_MS = 3_000;
const HOLD_WAIT_PHASE = "其他篇目已完成，等你回来点“登录并继续”";
const AWAY_NOTICE = "[批量] 这一篇等你登录或验证已到时限；后面的篇目遇到登录或验证只等 60 秒，你在登录页开始输入就照常等";
/**
 * Entitled access waited on the user (school login, verification) until its
 * time was up: the user seems away, so later articles of the batch wait briefly.
 */
function waitedOutOnUser(result) {
    return (result.status !== "ok" &&
        result.attempts.some((attempt) => attempt.stage === "entitled_access" &&
            (attempt.code === "login_timeout" || attempt.code === "download_timeout")));
}
/**
 * The seconds the backend asked this article to wait, and whose limit it is: the publisher's
 * hourly limit was reached before it opened (dependencies section 6, state L).
 */
function rateLimitWait(result) {
    if (result.status === "ok")
        return undefined;
    const attempt = result.attempts.find((a) => a.stage === "entitled_access" && a.code === "rate_limited");
    return attempt ? { wait: Math.max(1, Math.min(3600, attempt.retryAfterSec ?? 60)),
        ...(attempt.hourlyPublisher ? { publisher: attempt.hourlyPublisher } : {}) } : undefined;
}
/**
 * How often a batch waiting for the hourly limit keeps the publisher's session alive:
 * Wiley's institutional session lapsed after about half an hour without a request,
 * and the school's login had expired by then too (Windows, 2026-11-12).
 */
export const KEEP_SESSION_EVERY_MS = 10 * 60_000;
/**
 * How often a batch waiting for the hourly limit asks the backend how long it still waits: with
 * the settings window's 马上生效 on, a limit raised there, or none, goes on at once (the user,
 * 2026-11-19). Each ask reads the backend's settings and count only.
 */
export const HOURLY_RECHECK_EVERY_MS = 10_000;
/**
 * Runs the item again after each wait the publisher's hourly limit asks for. During a
 * wait, the backend's keepSession runs every KEEP_SESSION_EVERY_MS.
 */
async function pastHourlyLimit(run, log, pause, backend) {
    let result = await run();
    for (let held = rateLimitWait(result); held; held = rateLimitWait(result)) {
        await waitOutHour(held.wait, log, pause, backend, held.publisher);
        result = await run();
    }
    return result;
}
/**
 * The wait the publisher's hourly limit asks for, said once, the session kept alive meanwhile.
 * A backend that can say how long ``publisher`` still waits is asked every
 * HOURLY_RECHECK_EVERY_MS: the wait ends as soon as the limit the user set allows the article.
 */
async function waitOutHour(wait, log, pause, backend, publisher) {
    const resume = new Date(Date.now() + wait * 1000).toTimeString().slice(0, 5);
    log(`[批量] 这家出版社一小时内的下载已到上限（防止学校被暂停访问），${resume} 继续这一篇`);
    const recheck = publisher && backend?.hourlyWait ? () => backend.hourlyWait(publisher) : undefined;
    let sinceKeep = 0;
    for (let left = wait * 1000; left > 0;) {
        const step = Math.min(left, KEEP_SESSION_EVERY_MS - sinceKeep, recheck ? HOURLY_RECHECK_EVERY_MS : Infinity);
        await pause(step);
        left -= step;
        sinceKeep += step;
        if (left <= 0)
            break;
        const now = recheck ? await recheck().catch(() => undefined) : undefined;
        if (now?.waitSec === 0) {
            log(`[批量] 按现在的每小时上限（${now.limit > 0 ? `${now.limit} 篇` : "不限"}）可以接着下这一篇`);
            return;
        }
        if (now)
            left = now.waitSec * 1000;
        if (sinceKeep >= KEEP_SESSION_EVERY_MS) {
            sinceKeep = 0;
            await backend?.keepSession?.().catch(() => false);
        }
    }
}
/**
 * A batch's visit for an article page alone (its Markdown), waiting out the publisher's
 * hourly limit as a download does: the page reads count toward it, and with no PDF in the
 * Markdown's place there is no download to wait in (user, 2026-11-16).
 */
function pageVisit(backend, request, log, pause, seen) {
    const visit = fulltextPageVisit(backend, request);
    if (!visit)
        return undefined;
    return async (doi, outputDir, diagnosticsDir) => {
        let outcome = await visit(doi, outputDir, diagnosticsDir);
        while (outcome?.code === "rate_limited") {
            await waitOutHour(Math.max(1, Math.min(3600, outcome.retryAfterSec ?? 60)), log, pause, backend, outcome.hourlyPublisher);
            outcome = await visit(doi, outputDir, diagnosticsDir);
        }
        seen?.(outcome?.trace);
        return outcome;
    };
}
/** The journal's site blocked the current network (state L): a protection page,
 * or the school paused for downloading too much. The backend answers the
 * journal's later items at once; every other item goes on (the user, 2026-11-02). */
/** The user pressed "终止任务" in the progress window: the batch ends after this item. */
function stoppedByUser(result) {
    return result.attempts.some((attempt) => attempt.code === "batch_stopped") ||
        !!result.supplements?.some((file) => file.reason === "batch_stopped");
}
const STOP_NOTICE = "[批量] 已在进度窗口终止任务，剩下的篇目不再下载";
/** The user pressed 终止 in the batch's window (papers not reached, or still paused, show it). */
export function batchStopped(result) {
    return !!result.stopped || result.items.some((item) => stoppedByUser(item) || item.attempts.some((attempt) => attempt.code === "login_paused"));
}
/**
 * 没权限 (FailureClass no_access) at the school's stage: the publisher refused the signed-in school, the school's
 * sign-in is not enabled for the publisher, the publisher has no route for it, or the user marked the journal as
 * without access. Another saved school may have it (没权限时换下一所学校, user 2026-11-22: every paper under 没权限).
 */
function withoutAccess(result) {
    if (!result || result.status === "ok")
        return false;
    const school = [...result.attempts].reverse().find((attempt) => attempt.stage === "entitled_access");
    return school?.status === "error" && classifyFailureCode(school.code) === "no_access";
}
/**
 * 原因不明 (FailureClass unexplained) at the school's stage: tried once more at the batch's end, with the school it had,
 * before any other school (user, 2026-11-22: "原因不明的也最后再试一次"); not a paper the user stopped.
 */
function unexplainedFailure(result) {
    if (!result || result.status === "ok" || stoppedByUser(result))
        return false;
    const school = [...result.attempts].reverse().find((attempt) => attempt.stage === "entitled_access");
    return school?.status === "error" && classifyFailureCode(school.code) === "unexplained";
}
/** The other saved schools a batch's papers without access go to at its end: none for a batch given its school. */
async function schoolsAfterDefault(backend, options) {
    if (options.school?.trim() || !backend?.schoolSwitch)
        return [];
    return (await backend.schoolSwitch().catch(() => undefined))?.schools.slice(1) ?? [];
}
/**
 * 没权限时换下一所学校 at a batch's end (PaperSearch Pro; user, 2026-11-22): the papers still without access go to each
 * other saved school in turn, all of them with one before the next, so that the school's login is switched once, not at
 * every paper (switching to and fro had a school's login ask for a picture code, Windows 2026-11-22). ``visit`` tries
 * one paper with a school.
 */
async function laterSchools(schools, waiting, announce, visit, stopped) {
    for (const school of schools) {
        const offsets = waiting();
        if (!offsets.length || stopped())
            return;
        await announce(school, offsets.length);
        for (const offset of offsets) {
            if (stopped())
                return;
            await visit(offset, school);
        }
    }
}
/** A paper without access with each of ``count`` schools: its last school stage says so (N 所学校都没有权限). */
function triedSchools(result, count) {
    const school = [...result.attempts].reverse().find((attempt) => attempt.stage === "entitled_access");
    if (school && count > 1)
        school.schools = count;
}
/** The attempt recorded for an item the batch did not reach because the user stopped it. */
function notReached() {
    return { stage: "entitled_access", status: "skipped", message: "已终止任务，未下载", code: "batch_stopped" };
}
function publisherBlocked(result) {
    return (result.status !== "ok" &&
        result.attempts.some((a) => a.stage === "entitled_access" && a.code === "access_blocked"));
}
function blockedNotice(doi) {
    return (`[批量] 出版社网站拦截了当前网络（${doi}）：可能是当前网络被网站防护拦截，也可能是下载过多被暂停；` +
        "同一期刊的后续文章暂时直接跳过，每 5 分钟拿一篇再试一次网站（换了网络就会接着下），其他照常继续");
}
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function runItem(index, request) {
    return {
        index,
        paperId: request.paperId,
        ...(request.doi ? { doi: request.doi } : {}),
        ...(request.title ? { title: request.title } : {}),
    };
}
/**
 * A failed paper's class and reason, as the failed list names them (batchSummary.failure);
 * undefined for a saved paper or one the stop left undone. Every failed paper is in a class: a
 * batch of the Markdown alone counted only those whose step ended in an error, "失败 6" beside
 * classes of 1 (AHA, 2026-11-17).
 */
function failedAs(item, content) {
    return item.status === "ok" || stoppedItem(item) ? undefined : failure(item, content ?? "main");
}
/** Request options that report each stage of ``item`` to the ledger. */
function recorded(request, ledger, item) {
    return ledger
        ? { ...request, onStage: (record) => ledger.stage(item, record), recordsDir: ledger.records, diagnosticsDir: ledger.diagnostics }
        : request;
}
function openLedger(mode, batchId, options, log) {
    const ledger = RunLedger.open({
        kind: "download_batch",
        mode,
        batchId,
        total: options.items.length,
        ...(options.savePath ? { savePath: options.savePath } : {}),
        content: options.content ?? "main",
        ...(options.fulltext ? { fulltext: true } : {}),
        ...(options.school?.trim() ? { school: options.school.trim() } : {}),
        ...(options.resumeOf ? { resumeOf: options.resumeOf } : {}),
    });
    if (ledger)
        log(`[批量] 运行记录：${ledger.dir}`);
    options.folderRecord?.attach(ledger);
    return ledger;
}
function itemResult(result, index, options) {
    return {
        ...result,
        index,
        paperId: options.paperId,
        ...(options.doi ? { doi: options.doi } : {}),
    };
}
function summary(mode, batchId, items, extra = {}) {
    const succeeded = items.filter((item) => item.status === "ok").length;
    const failed = items.length - succeeded;
    const stopped = items.filter(stoppedItem).length;
    const failureClasses = {};
    for (const item of items) {
        const failed = failedAs(item, extra.content);
        if (failed)
            failureClasses[failed.cls] = (failureClasses[failed.cls] ?? 0) + 1;
    }
    return {
        status: failed === 0 ? "ok" : succeeded === 0 ? "error" : "partial",
        mode,
        content: "main",
        batchId,
        total: items.length,
        succeeded,
        failed,
        ...(stopped ? { stoppedItems: stopped } : {}),
        ...(Object.keys(failureClasses).length ? { failureClasses } : {}),
        ...extra,
        items,
    };
}
/** Download a list serially; one batch id ties it to one progress window. */
export async function downloadBatch(searchers, options, backend, log = (line) => process.stderr.write(`${line}\n`), createTiers = createDefaultDownloadTiers, pause = wait, online = networkReachable) {
    options = { ...options, savePath: resolveDownloadPath(options.savePath) };
    // The batch's own folder keeps its records beside its papers (user, 2026-11-17).
    const { folderRecord: _given, ...asked } = options;
    const folderRecord = openBatchFolder(options.savePath, asked);
    if (folderRecord) {
        const out = log;
        log = (line) => {
            out(line);
            folderRecord.log(line);
        };
        options = { ...options, folderRecord };
    }
    const startedAt = Date.now();
    // The Markdown is PaperSearch Pro's (content/markdown/pro.ts): without it, or while it cannot
    // be used, the batch says so once and its papers' Markdown says why.
    const wantsMarkdown = !!options.fulltext || options.content === "markdown";
    const pro = wantsMarkdown ? await loadMarkdownPro() : undefined;
    const blocked = wantsMarkdown ? markdownBlocked(pro) : undefined;
    if (blocked)
        log(`[批量] ${blocked.code === "markdown_pro_required" ? "Markdown 全文是 PaperSearch Pro 的功能，本机没有安装 Pro（设置窗口的“Markdown 全文”页点“安装”，或运行 paper-search pro install）" : `PaperSearch Pro 暂不可用：${blocked.message}`}；PDF 和补充材料照常下载`);
    // Each batch tries the sites not yet supported afresh (three failures in a row give one up).
    if (pro && !blocked)
        pro.batchStarted();
    // Their first papers go first, so how they convert shows early (landingScan.ts, user 2026-11-16).
    if (pro && !blocked && backend && options.items.length > pro.triedFirstCount) {
        const dois = options.items.flatMap((item) => (item.doi ? [item.doi] : []));
        const { items, sites } = pro.triedFirst(options.items, await pro.landingHosts(dois));
        if (sites.length) {
            options = { ...options, items };
            log(`[批量] 预查：${sites.map((site) => `${site.host} ${site.papers} 篇`).join("、")}，这些网站没有登记 Markdown 规则，`
                + `各先试前 ${pro.triedFirstCount} 篇（先用出版社的规则）；转换完整才保存，前 ${pro.triedFirstCount} 篇都不完整的本批不再尝试`);
        }
    }
    const run = async (backend) => {
        const result = await (options.content === "supplements" || options.content === "markdown"
            ? downloadSerialBatch(options, backend, log, searchers, createTiers, pause, online)
            : options.mode === "per_item"
                ? downloadPerItem(searchers, options, backend, log, createTiers, pause, online)
                : downloadTwoPhase(searchers, options, backend, log, createTiers, options.mode === "entitled_only" ? "entitled_only" : "two_phase", pause, online));
        await reportBatchResults(result, backend, startedAt, options.savePath);
        return result;
    };
    const result = await (backend?.withBatchSession ? backend.withBatchSession(run) : run(backend));
    // Each class with its reasons: "原因不明 1（PDF 身份未确认 1）", not a class alone beside the
    // list's reason (Windows, 2026-11-17).
    const reasons = new Map();
    for (const item of result.items) {
        const failed = failedAs(item, result.content);
        if (!failed)
            continue;
        const byReason = reasons.get(failed.cls) ?? new Map();
        byReason.set(failed.reason, (byReason.get(failed.reason) ?? 0) + 1);
        reasons.set(failed.cls, byReason);
    }
    const byClass = Object.entries(result.failureClasses ?? {})
        .map(([failureClass, count]) => {
        const said = [...(reasons.get(failureClass) ?? [])].sort((a, b) => b[1] - a[1]);
        const listed = said.slice(0, 3).map(([reason, n]) => `${reason} ${n}`).join("、") + (said.length > 3 ? " 等" : "");
        return `${FAILURE_CLASS_NAMES[failureClass]} ${count}` + (listed ? `（${listed}）` : "");
    })
        .join("、");
    // Main text and supplementary files apart: "附录未下全 2 篇：网站人机验证拦截 2".
    const shortfalls = new Map();
    for (const item of result.content === "both" ? result.items : []) {
        const code = supplementShortfall(item);
        if (!code)
            continue;
        const reason = schoolShortReason(code, "附录没下载成功");
        shortfalls.set(reason, (shortfalls.get(reason) ?? 0) + 1);
    }
    const missed = [...shortfalls.values()].reduce((sum, n) => sum + n, 0);
    // The Markdown not saved, by reason: beside the PDF or the files, for a paper saved without
    // it (432 such went unsaid at the end of an ARD batch, user 2026-11-16); in a batch of the
    // Markdown alone, for each paper it failed.
    const noMarkdown = new Map();
    for (const item of result.items) {
        if (!item.markdown || item.markdown.status === "ok" || stoppedItem(item))
            continue;
        if (result.content !== "markdown" && item.status !== "ok")
            continue;
        const { reason } = markdownMissing(item.markdown);
        const site = item.markdown.unverified ? `（${item.markdown.unverified.host}）` : "";
        noMarkdown.set(reason + site, (noMarkdown.get(reason + site) ?? 0) + 1);
    }
    const incomplete = [...noMarkdown.values()].reduce((sum, n) => sum + n, 0);
    // Saved, its checks finding something short (a registered site's page, user 2026-11-17).
    const doubts = new Map();
    for (const item of result.items) {
        const doubt = item.status === "ok" ? markdownDoubt(item.markdown) : undefined;
        if (doubt)
            doubts.set(doubt.reason, (doubts.get(doubt.reason) ?? 0) + 1);
    }
    const doubtful = [...doubts.values()].reduce((sum, n) => sum + n, 0);
    // Papers the stop left undone are told apart, not counted as failed (user, 2026-11-16).
    const stopped = result.stoppedItems ?? 0;
    log(`[批量] 完成：成功 ${result.succeeded}，失败 ${result.failed - stopped}` + (stopped ? `，已终止 ${stopped}` : "")
        + `，共 ${result.total} 篇` +
        (byClass ? `。失败分类：${byClass}；详情：paper-search failures --format text` : "") +
        (missed ? `。附录未下全 ${missed} 篇：${[...shortfalls].map(([reason, n]) => `${reason} ${n}`).join("、")}` : "") +
        (incomplete ? `。Markdown 未生成 ${incomplete} 篇：${[...noMarkdown].map(([reason, n]) => `${reason} ${n}`).join("、")}` : "") +
        (doubtful ? `。Markdown 可能不全 ${doubtful} 篇（已保存，请核对）：${[...doubts].map(([reason, n]) => `${reason} ${n}`).join("、")}` : ""));
    // What is left goes on later with one word (user, 2026-11-15).
    if ((result.failed || missed || incomplete) && result.runLog) {
        log("[批量] 没下全的篇目：回来后对 AI 说“接着下”即可补（download_batch 的 resume: \"latest\"，同一套环境变量）");
    }
    folderRecord?.refresh();
    return result;
}
/**
 * content "supplements" or "markdown": every item, one after another, without the main
 * text's stages: its supplementary files, its Markdown (the full-text package, no PDF in
 * its place: user, 2026-11-16), or both (user, 2026-11-14).
 */
async function downloadSerialBatch(options, backend, log, searchers, createTiers, pause, online) {
    const content = options.content === "markdown" ? "markdown" : "supplements";
    const batchId = randomUUID();
    const total = options.items.length;
    const ledger = openLedger(content, batchId, options, log);
    const watch = { log, pause, online };
    // The window's lists (成功, 失败, 剩余 open on a click), as the other batches send them: a
    // batch of the Markdown or the files alone sent none (Windows, 2026-11-15).
    const papers = new PaperList(backend, batchId, options.savePath, options.items.map((item) => batchPaper(itemOptions(item, options), undefined, "open", content, item.mainPath)));
    await papers.send();
    const items = [];
    let succeeded = 0;
    let failed = 0;
    let away = false;
    for (const [offset, item] of options.items.entries()) {
        const batch = { id: batchId, index: offset + 1, total, done: offset, succeeded, failed };
        const request = { ...itemOptions(item, options), batch, ...(away ? { shortUserWait: true } : {}) };
        const entry = runItem(offset + 1, request);
        log(`[批量] ${content === "markdown" ? "Markdown" : options.fulltext ? "补充材料和 Markdown" : "补充材料"} ${offset + 1}/${total}：${request.doi || request.paperId}`);
        // 接着下 (resume.ts): a paper whose PDF a batch saved before gets its Markdown beside it, not the PDF again.
        // Done again after a network loss, from what was there before it (``before`` copied each time).
        const markdown = (before) => pastNetworkLoss(() => {
            const from = { ...before, attempts: [...before.attempts] };
            return item.mainPath
                ? markdownBeside(from, item.mainPath, recorded(request, ledger, entry), searchers, pageVisit(backend, request, log, pause))
                : fulltextAlone(from, recorded(request, ledger, entry), searchers, pageVisit(backend, request, log, pause));
        }, watch);
        let result;
        if (content === "markdown") {
            result = await markdown({ status: "error", attempts: [] });
        }
        else {
            result = await pastNetworkLoss(() => downloadSupplementsOnly(recorded(request, ledger, entry), backend, searchers, item.mainPath), watch);
            if (options.fulltext && !stoppedByUser(result))
                result = await markdown(result);
        }
        if (!away && waitedOutOnUser(result)) {
            away = true;
            log(AWAY_NOTICE);
        }
        await reportBatchItem(request, result, backend);
        if (result.status === "ok")
            succeeded += 1;
        else
            failed += 1;
        ledger?.item(entry, result);
        items.push(itemResult(result, offset + 1, request));
        papers.set(offset, batchPaper(request, items[items.length - 1], undefined, content, item.mainPath));
        if (stoppedByUser(result)) {
            for (const [rest, item] of options.items.entries()) {
                if (rest <= offset)
                    continue;
                const request = itemOptions(item, options);
                const skipped = itemResult({ status: "error", attempts: [notReached()],
                    ...(content === "supplements" ? { supplements: [{ status: "skipped", label: "", reason: "batch_stopped" }] } : {}) }, rest + 1, request);
                items.push(skipped);
                ledger?.item(runItem(rest + 1, request), skipped);
                papers.set(rest, batchPaper(request, skipped, undefined, content, item.mainPath));
            }
            log(STOP_NOTICE);
            break;
        }
        await papers.send();
    }
    await papers.send(true);
    ledger?.close();
    return summary(options.mode ?? "two_phase", batchId, items, {
        content,
        ...(ledger ? { runLog: ledger.dir } : {}),
    });
}
async function downloadPerItem(searchers, options, backend, log, createTiers, pause, online) {
    const batchId = randomUUID();
    const total = options.items.length;
    const ledger = openLedger("per_item", batchId, options, log);
    const watch = { log, pause, online };
    const content = options.content ?? "main";
    const papers = new PaperList(backend, batchId, options.savePath, options.items.map((item) => batchPaper(itemOptions(item, options), undefined, "open", content)));
    await papers.send();
    const items = [];
    let succeeded = 0;
    let failed = 0;
    let away = false;
    // 没权限时换下一所学校 (PaperSearch Pro): papers without access wait for the other saved schools, tried at the end, one
    // school at a time (``laterSchools``, user 2026-11-22).
    let turns;
    const otherSchools = () => (turns ??= schoolsAfterDefault(backend, options));
    const waiting = new Map();
    const schoolsTried = new Map();
    /** Papers failed for a reason not known, waiting for their one more try at the end (user, 2026-11-22). */
    const unexplainedYet = new Map();
    let stopped = false;
    for (const [offset, item] of options.items.entries()) {
        const index = offset + 1;
        const request = itemOptions(item, options);
        const entry = runItem(index, request);
        log(`[批量] 第 ${index}/${total} 篇：${request.doi || request.paperId}`);
        // Papers waiting for the end (without access, 原因不明) are not done yet: the counts are of those finished.
        const batch = { id: batchId, index, total, done: succeeded + failed, succeeded, failed };
        const result = await pastNetworkLoss(() => pastHourlyLimit(() => downloadWithFallback(searchers, recorded({ ...request, batch, ...(away ? { shortUserWait: true } : {}) }, ledger, entry), createTiers(backend)), log, pause, backend), watch);
        if (!away && waitedOutOnUser(result)) {
            away = true;
            log(AWAY_NOTICE);
        }
        const finished = itemResult(result, index, request);
        if (!stoppedByUser(result))
            await filesPastNetworkLoss(finished, recorded({ ...request, batch }, ledger, entry), backend, searchers, watch);
        if (!stoppedByUser(result)) {
            await markdownPastNetworkLoss(finished, recorded({ ...request, batch }, ledger, entry), searchers, pageVisit(backend, { ...request, batch }, log, pause), watch);
        }
        items.push(finished);
        if (withoutAccess(finished) && !stoppedByUser(finished) && (await otherSchools()).length) {
            // Not finished: it waits for the other schools at the end.
            waiting.set(offset, entry);
            papers.set(offset, batchPaper(request, finished, "school", content));
            await papers.send();
            continue;
        }
        if (unexplainedFailure(finished)) {
            // Not finished: once more at the end, with this school.
            unexplainedYet.set(offset, entry);
            papers.set(offset, batchPaper(request, finished, "school", content));
            await papers.send();
            continue;
        }
        if (result.status === "ok")
            succeeded += 1;
        else
            failed += 1;
        // The window's end when the last paper is finished, not the last in the list (some wait for the end).
        await reportBatchItem({ ...request, batch: { ...batch, index: batch.done + 1 } }, finished, backend);
        ledger?.item(entry, finished);
        papers.set(offset, batchPaper(request, finished, undefined, content));
        if (publisherBlocked(result))
            log(blockedNotice(request.doi || request.paperId));
        if (stoppedByUser(finished)) {
            stopped = true;
            for (const [rest, restItem] of options.items.entries()) {
                if (rest <= offset)
                    continue;
                const restRequest = itemOptions(restItem, options);
                const restFinished = itemResult({ status: "error", attempts: [notReached()] }, rest + 1, restRequest);
                ledger?.item(runItem(rest + 1, restRequest), restFinished);
                items.push(restFinished);
                papers.set(rest, batchPaper(restRequest, restFinished, undefined, content));
            }
            log(STOP_NOTICE);
            break;
        }
        await papers.send();
    }
    /** A paper's school stage once more (another saved school when given), its files and Markdown when it comes. */
    const again = async (offset, entry, school) => {
        const request = { ...itemOptions(options.items[offset], options), ...(school ? { school: school.entityId } : {}) };
        const batch = { id: batchId, index: offset + 1, total, done: succeeded + failed, succeeded, failed };
        log(school ? `[批量] 换${school.name}：${request.doi || request.paperId}` : `[批量] 再试一次：${request.doi || request.paperId}`);
        const result = await pastNetworkLoss(() => pastHourlyLimit(() => downloadWithFallback(searchers, recorded({ ...request, batch, ...(away ? { shortUserWait: true } : {}) }, ledger, entry), createTiers(backend).filter((tier) => tier.stage === "entitled_access")), log, pause, backend), watch);
        const before = items[offset];
        const finished = itemResult({ ...result, attempts: [...before.attempts, ...result.attempts],
            ...(before.markdown ? { markdown: before.markdown } : {}) }, offset + 1, request);
        items[offset] = finished;
        if (result.status === "ok") {
            await filesPastNetworkLoss(finished, recorded({ ...request, batch }, ledger, entry), backend, searchers, watch);
            if (finished.markdown?.status !== "ok") {
                await markdownPastNetworkLoss(finished, recorded({ ...request, batch }, ledger, entry), searchers, pageVisit(backend, { ...request, batch }, log, pause), watch);
            }
        }
        if (stoppedByUser(result))
            stopped = true;
        return finished;
    };
    /** A paper finished at the end: counted, recorded, shown. */
    const finish = async (offset, entry) => {
        const request = itemOptions(options.items[offset], options);
        const done = succeeded + failed;
        const batch = { id: batchId, index: done + 1, total, done, succeeded, failed };
        if (items[offset].status === "ok")
            succeeded += 1;
        else
            failed += 1;
        await reportBatchItem({ ...request, batch }, items[offset], backend);
        ledger?.item(entry, items[offset]);
        papers.set(offset, batchPaper(request, items[offset], undefined, content));
        await papers.send();
    };
    // 原因不明 once more, with this school, before any other school (user, 2026-11-22).
    if (unexplainedYet.size && !stopped) {
        log(`[批量] 原因不明的 ${unexplainedYet.size} 篇再试一次`);
        ledger?.phase(`原因不明的 ${unexplainedYet.size} 篇再试一次`);
        for (const [offset, entry] of [...unexplainedYet]) {
            if (stopped)
                break;
            const finished = await again(offset, entry);
            unexplainedYet.delete(offset);
            if (!stopped && withoutAccess(finished) && (await otherSchools()).length)
                waiting.set(offset, entry);
            else
                await finish(offset, entry);
        }
    }
    for (const [offset, entry] of unexplainedYet)
        await finish(offset, entry);
    // The papers without access go to the other saved schools, one school at a time.
    if (waiting.size && !stopped) {
        await laterSchools(await otherSchools(), () => [...waiting.keys()], async (school, count) => {
            log(`[批量] 没权限的 ${count} 篇换${school.name}再试`);
            ledger?.phase(`没权限的 ${count} 篇换${school.name}再试`);
        }, async (offset, school) => {
            const entry = waiting.get(offset);
            const finished = await again(offset, entry, school);
            schoolsTried.set(offset, (schoolsTried.get(offset) ?? 1) + 1);
            if (!stopped && withoutAccess(finished)) {
                triedSchools(finished, schoolsTried.get(offset));
                return;
            }
            waiting.delete(offset);
            await finish(offset, entry);
        }, () => stopped);
    }
    // Without access with every school (or the batch stopped first): failed.
    for (const [offset, entry] of waiting)
        await finish(offset, entry);
    await papers.send(true);
    ledger?.close();
    return summary("per_item", batchId, items, {
        content: options.content ?? "main",
        ...(ledger ? { runLog: ledger.dir } : {}),
    });
}
/** An item a lane could not finish: the error stands as its result; the other lane goes on. */
function laneError(stage, error) {
    return {
        status: "error",
        attempts: [{ stage, status: "error", code: "stage_exception",
                message: error instanceof Error ? `${error.name}: ${error.message}` : String(error) }],
    };
}
async function downloadTwoPhase(searchers, options, backend, log, createTiers, mode = "two_phase", pause = wait, online = networkReachable) {
    const batchId = randomUUID();
    const total = options.items.length;
    const ledger = openLedger(mode, batchId, options, log);
    const requests = options.items.map((item) => itemOptions(item, options));
    const entries = requests.map((request, offset) => runItem(offset + 1, request));
    const results = new Array(total);
    const content = options.content ?? "main";
    const papers = new PaperList(backend, batchId, options.savePath, requests.map((request) => batchPaper(request, undefined, mode === "entitled_only" ? "school" : "open", content)));
    const recordedOffsets = new Set();
    /** An item goes to the run record once, when it has settled. */
    const record = (offset) => {
        if (recordedOffsets.has(offset))
            return;
        recordedOffsets.add(offset);
        ledger?.item(entries[offset], results[offset]);
    };
    const id = (offset) => requests[offset].doi || requests[offset].paperId;
    // Two lanes at once. The open lane checks every item in turn, needing no
    // browser; each item it misses joins the queue of the browser's lane, which
    // starts on the first one at once and takes them one after another (one
    // browser, one school login). Each paper is finished in its turn, its PDF, its
    // supplementary files and its Markdown, never left for a later round (user,
    // 2026-11-15): an open-access paper whose files or page need the browser joins
    // the same queue, to be finished there. A large batch shows the window from the
    // start: one count for the whole batch, where an item counts once it is finished.
    const wantsFiles = options.content === "both";
    const wantsMarkdown = !!options.fulltext;
    /** Open-access papers in the browser's queue for their files or page. */
    const finishing = new Set();
    const openProgress = mode !== "entitled_only" && total >= OPEN_PROGRESS_MIN_ITEMS && !!backend?.reportBatchProgress;
    const missed = [];
    const queue = [];
    let openRunning = mode !== "entitled_only";
    let checked = 0;
    let openFound = 0;
    /** Open-access papers finished (the browser's part done, when they needed one). */
    let openSettled = 0;
    let succeeded = 0;
    let failed = 0;
    /** Of the entitled lane's 成功: arXiv copies, open ones (as the finished card counts them). */
    let preprints = 0;
    let away = false;
    let stopped = false;
    let wake;
    const notify = () => {
        const resume = wake;
        wake = undefined;
        resume?.();
    };
    const settledOk = () => openSettled + succeeded;
    // The window's lines while the lanes run, one report after another so that
    // the counts never go back. Beside a running download only the counts and
    // the lanes lines change (a backend that cannot do that gets none of these).
    // One line in the window: the papers each lane got, which add up to its 成功
    // (失败 and 剩余 are the batch's alone; a lane's "left" read as all going to
    // the school, the user's review 2026-11-10).
    const lanes = () => `${OPEN_CHANNEL} ${openFound + preprints} 篇 · 机构下载 ${succeeded - preprints} 篇`;
    let reports = Promise.resolve();
    const reportProgress = (current) => {
        if (!openProgress)
            return reports;
        const update = {
            id: batchId, total, done: settledOk() + failed, succeeded: settledOk(), failed, current, finished: false,
            ...(openRunning ? { phase: `${OPEN_CHANNEL}：已查 ${checked}/${total} 篇，找到 ${openFound} 篇`, channel: OPEN_CHANNEL } : {}),
            ...(missed.length ? { lanes: lanes() } : {}),
        };
        reports = reports.then(() => backend.reportBatchProgress(update)).catch(() => false);
        return reports;
    };
    // The window's lists, queued behind the progress reports in the order things happened.
    const sendPapers = (last = false) => {
        reports = reports.then(() => papers.send(last));
        return reports;
    };
    const settle = (offset, waiting) => papers.set(offset, batchPaper(requests[offset], results[offset], waiting, content));
    // Without network the window says so, while it is open (a large batch, or the school's lane begun).
    const watch = { log, pause, online, notice: (phase) => {
            if (!backend?.reportBatchProgress || !(openProgress || missed.length))
                return reports;
            const update = { id: batchId, total, done: settledOk() + failed, succeeded: settledOk(), failed, current: "",
                finished: false, phase };
            reports = reports.then(() => backend.reportBatchProgress(update)).catch(() => false);
            return reports;
        } };
    const openLane = async () => {
        try {
            for (const [offset, request] of requests.entries()) {
                if (stopped)
                    break;
                log(`[批量] 开放来源 ${offset + 1}/${total}：${id(offset)}`);
                const tiers = createTiers(backend).filter((tier) => tier.stage !== "entitled_access" && tier.stage !== "preprint");
                let result;
                try {
                    result = await pastNetworkLoss(() => downloadWithFallback(searchers, recorded(request, ledger, entries[offset]), tiers), watch);
                }
                catch (error) {
                    result = laneError("open_access", error);
                    log(`[批量] 开放来源出错（${id(offset)}）：${result.attempts[0].message}；这一篇转机构下载`);
                }
                results[offset] = itemResult(result, offset + 1, request);
                checked = offset + 1;
                if (result.status === "ok") {
                    openFound += 1;
                    // Its Markdown from the open sources now; the browser's part, if any, in its queue.
                    const later = wantsFiles || wantsMarkdown &&
                        await fulltextForItem(results[offset], recorded(request, ledger, entries[offset]), searchers, "later") === "later";
                    // The window lists its PDF as saved now, as it did (its files' shortfall, if any, later).
                    settle(offset);
                    if (later) {
                        finishing.add(offset);
                        queue.push(offset);
                        notify();
                    }
                    else {
                        openSettled += 1;
                        record(offset);
                    }
                }
                else {
                    settle(offset, "school");
                    if (!missed.length) {
                        log(`[批量] 开放来源没有找到 ${id(offset)}，机构下载同时开始`);
                        ledger?.phase("机构下载开始，开放来源同时进行");
                    }
                    missed.push(offset);
                    queue.push(offset);
                    notify();
                }
                await reportProgress(id(offset));
                takeRequests();
                await sendPapers();
            }
        }
        finally {
            openRunning = false;
            notify();
        }
        if (!stopped) {
            log(`[批量] 开放来源查完：获取 ${openFound}/${total} 篇；` +
                (missed.length ? `${missed.length} 篇转机构下载` : "无需机构下载"));
            ledger?.phase(`开放来源查完：${missed.length} 篇转机构下载`);
        }
    };
    /**
     * The browser's part of an open-access paper: its supplementary files (the visit also
     * saves the page when the Markdown is wanted), then its Markdown.
     */
    const finishOpenItem = async (offset) => {
        finishing.delete(offset);
        const done = settledOk() + failed;
        const request = { ...requests[offset], batch: { id: batchId, index: done + 1, total, done, succeeded: settledOk(), failed },
            ...(away ? { shortUserWait: true } : {}) };
        const item = results[offset];
        log(`[批量] ${wantsFiles ? (wantsMarkdown ? "补充材料和 Markdown" : "补充材料") : "Markdown"}（PDF 已从开放来源取得）：${id(offset)}`);
        let extra;
        /** Where the visit for the Markdown's page ended its wait on a school login (trace.loginWaitPage). */
        let pageWait;
        let markdownFrom = item.attempts.length;
        try {
            extra = await filesPastNetworkLoss(item, recorded(request, ledger, entries[offset]), backend, searchers, watch);
            markdownFrom = item.attempts.length;
            if (wantsMarkdown && !stoppedByUser(item)) {
                await markdownPastNetworkLoss(item, recorded(request, ledger, entries[offset]), searchers, pageVisit(backend, request, log, pause, (trace) => { pageWait = trace?.loginWaitPage; learnPublisher(offset, trace?.publisher); }), watch);
            }
        }
        catch (error) {
            log(`[批量] 补充材料或 Markdown 出错（${id(offset)}）：${error instanceof Error ? error.message : String(error)}`);
        }
        // Its full text read on the publisher's page in the browser: the school's login worked for
        // this publisher in this batch, as a PDF through it shows (OAC, 2026-11-17: the login
        // lapsed at 02:39 before any of its PDFs had come through the school, and 44 papers each
        // waited it out until the user signed in again at 08:05).
        if (item.markdown?.status === "ok" && item.markdown.source === "publisher_page")
            cameThrough(offset);
        if (item.markdown?.code === LOGIN_LAPSED_CODE) {
            if (!away) {
                away = true;
                log(AWAY_NOTICE);
            }
            // Its page stopped at the school's own sign-in page: held with its publisher, its Markdown
            // fetched again when the user goes on (the files it got stand).
            if (pageWait === SCHOOL_SIGN_IN_PAGE && wentThrough(offset) && !stoppedByUser(item) && await canHold()) {
                item.attempts.length = markdownFrom;
                delete item.markdown;
                finishing.add(offset);
                if (extra)
                    await reportBatchItem(request, extra, backend);
                hold(offset);
                settle(offset);
                await sendPapers();
                return;
            }
        }
        openSettled += 1;
        if (extra)
            await reportBatchItem(request, extra, backend);
        record(offset);
        // The window's 失败 list shows a missing supplementary file as it happens (user, 2026-11-11).
        settle(offset);
        if (stoppedByUser(item)) {
            stopped = true;
            return;
        }
        if (openRunning || queue.length)
            await reportProgress("");
        await sendPapers();
    };
    // A publisher whose school login stops working mid-batch (its papers came through the
    // school, then one stops at the school's own sign-in page): its papers wait, their PDF, supplementary files
    // and Markdown alike, the others go on, and they go on when the user presses 登录并继续 in
    // the window (the user, 2026-11-15: Science's session lapsed after 84 articles and a
    // misread login page failed the other 540). Publishers by name (user, 2026-11-17: a publisher's
    // journals of other DOI prefixes, Elsevier's 10.1053/ and ARD's 10.1136/ beside 10.1016/, wait
    // with it), each paper's as its school visit named it, else its DOI prefix's as learned so far,
    // else the prefix itself.
    /** Where the school's login worked in this batch: each such paper's publisher and DOI prefix. */
    const viaSchool = new Set();
    /** Each held publisher's papers, open-access ones still to be finished among them. */
    const held = new Map();
    /** Where each paper's wait on a school login ended, as the backend said (trace.loginWaitPage). */
    const waitEnded = new Map();
    const prefixOf = (offset) => (/^10\.\d{4,9}\//.exec(requests[offset].doi.toLowerCase()) ?? [""])[0];
    /** Each paper's publisher as its own school visit named it. */
    const paperPublishers = new Map();
    /** A paper's publisher: its own visit's, else its DOI prefix's as learned so far, else the prefix. */
    const publisherOf = (offset) => paperPublishers.get(offset) ?? publishers.get(prefixOf(offset)) ?? prefixOf(offset);
    const learnPublisher = (offset, name) => {
        if (typeof name !== "string" || !name)
            return;
        paperPublishers.set(offset, name);
        if (prefixOf(offset))
            publishers.set(prefixOf(offset), name);
    };
    const cameThrough = (offset) => {
        if (prefixOf(offset))
            viaSchool.add(prefixOf(offset));
        viaSchool.add(publisherOf(offset));
    };
    const wentThrough = (offset) => viaSchool.has(publisherOf(offset)) || (!!prefixOf(offset) && viaSchool.has(prefixOf(offset)));
    // Held only where the window can show it with its button; else they fail as before.
    let holdOk;
    const canHold = async () => (holdOk ??= await backend?.holdSupported?.().catch(() => false) ?? false);
    /** Each DOI prefix's publisher as the school's stages named it ("Science"); the last one named. */
    const publishers = new Map();
    const heldList = () => [...held.entries()].map(([key, offsets]) => ({
        key, name: publishers.get(key) ?? key, count: offsets.length,
    }));
    /** The window's line and button for the held publishers (none: cleared). */
    const reportHeld = (waiting = false) => {
        if (!backend?.reportBatchProgress || !holdOk)
            return reports;
        const update = { id: batchId, total, done: settledOk() + failed, succeeded: settledOk(), failed, current: "",
            finished: false, held: heldList(), ...(waiting ? { phase: HOLD_WAIT_PHASE, heldWait: true } : { lanes: lanes() }) };
        reports = reports.then(() => backend.reportBatchProgress(update)).catch(() => false);
        return reports;
    };
    /** ``offset`` stopped at the school's sign-in page: its publisher's papers wait for the user. */
    const hold = (offset) => {
        const key = publisherOf(offset);
        if (held.has(key)) {
            held.get(key).push(offset);
            return;
        }
        held.set(key, [offset]);
        log(`[批量] ${key} 的文章前面经学校登录下到了，这一篇停在学校登录页没有完成登录：` +
            "这家出版社的篇目先暂停，其他照常下载；回来后在进度窗口点“登录并继续”");
        ledger?.phase(`暂停 ${key}：学校登录中途失效`);
        void reportHeld();
    };
    /** The user pressed 登录并继续 (or 终止) in the window: held papers go on first. */
    const takeRequests = () => {
        const asked = backend?.takeBatchRequests?.(batchId);
        if (!asked)
            return;
        if (asked.stop)
            stopped = true;
        let resumed = 0;
        for (const key of asked.resume) {
            const offsets = held.get(key) ?? [];
            held.delete(key);
            queue.unshift(...offsets);
            resumed += offsets.length;
        }
        if (resumed) {
            log(`[批量] 已点“登录并继续”：暂停的 ${resumed} 篇接着下载`);
            ledger?.phase(`接着下载暂停的 ${resumed} 篇`);
            void reportHeld();
            notify();
        }
    };
    /** The held papers end as paused (the batch stopped): returns them, no longer held. */
    const markPaused = () => {
        const paused = [...held.values()].flat();
        for (const offset of paused) {
            const item = results[offset];
            if (finishing.has(offset)) {
                // Its PDF stands; its browser's part waited for the login.
                if (wantsFiles)
                    item.supplements = [{ status: "skipped", label: "", reason: "batch_stopped" }];
            }
            else {
                results[offset] = itemResult({ ...item, status: "error", attempts: [...item.attempts,
                        { stage: "entitled_access", status: "error", ...schoolAttemptDetails("login_paused") }] }, offset + 1, requests[offset]);
            }
        }
        held.clear();
        return paused;
    };
    /**
     * The request, its school stage also naming its publisher (``learnPublisher``)
     * and where its wait on a school login ended (``waitEnded``).
     */
    const watchingSchool = (request, offset) => {
        const forward = request.onStage;
        return { ...request, onStage: (record) => {
                if (record.stage === "entitled_access") {
                    learnPublisher(offset, record.trace?.publisher);
                    const page = record.trace?.loginWaitPage;
                    if (typeof page === "string")
                        waitEnded.set(offset, page);
                    else
                        waitEnded.delete(offset);
                }
                forward?.(record);
            } };
    };
    // 没权限时换下一所学校 (PaperSearch Pro): the other saved schools, asked once a paper has gone without access (the
    // backend the batch has by then can say). Such papers wait, not finished, and go to them at the end, all of them with
    // one school before the next (``laterSchools``, user 2026-11-22).
    let turns;
    const otherSchools = () => (turns ??= schoolsAfterDefault(backend, options));
    /** Papers without access with the schools tried so far, waiting for the next one. */
    const withoutAccessYet = new Set();
    /** Papers failed for a reason not known, waiting for their one more try at the end. */
    const unexplainedYet = new Set();
    /** Each waiting paper's schools tried, the default one counted. */
    const schoolsTried = new Map();
    // One journal's papers one after another when the backend says so (more than one school taking part, user
    // 2026-11-21; kept with the switch at the end, user 2026-11-22). Asked until the backend has run a paper and can say.
    let groupJournals;
    let lastJournal = "";
    const entitledLane = async () => {
        for (;;) {
            while (!queue.length && openRunning && !stopped)
                await new Promise((resume) => { wake = resume; });
            if (groupJournals === undefined && backend?.schoolSwitch) {
                groupJournals = (await backend.schoolSwitch().catch(() => undefined))?.group;
            }
            const offset = stopped ? undefined
                : takeNext(queue, (at) => journalOfDoi(requests[at].doi), lastJournal, groupJournals === true);
            if (offset === undefined)
                return;
            lastJournal = journalOfDoi(requests[offset].doi);
            if (held.has(publisherOf(offset))) {
                held.get(publisherOf(offset)).push(offset);
                continue;
            }
            if (finishing.has(offset)) {
                await finishOpenItem(offset);
                if (stopped)
                    return;
                if (held.size)
                    await reportHeld();
                takeRequests();
                continue;
            }
            const request = requests[offset];
            // Papers waiting for the end (without access, 原因不明) counted too: the log goes 1/7, 2/7 … as the window does
            // (Windows 2026-11-22: every line said 1/7 while the papers waited).
            const step = succeeded + failed + withoutAccessYet.size + unexplainedYet.size + 1;
            log(openRunning
                ? `[批量] 机构下载第 ${step} 篇（开放来源还在查）：${id(offset)}`
                : `[批量] 机构下载 ${step}/${missed.length}：${id(offset)}`);
            const done = settledOk() + failed;
            // Its place among the papers gone through, those waiting for the end counted (the window's "k / N" goes on);
            // the counts are of those finished.
            const batch = { id: batchId, index: done + withoutAccessYet.size + unexplainedYet.size + 1, total, done,
                succeeded: settledOk(), failed };
            let result;
            try {
                // Reported to the window once it is known whether the paper waits for the end (``reportBatchItem`` below).
                result = await pastNetworkLoss(() => pastHourlyLimit(() => downloadWithFallback(searchers, watchingSchool(recorded({ ...request, batch, ...(away ? { shortUserWait: true } : {}) }, ledger, entries[offset]), offset), createTiers(backend).filter((tier) => tier.stage === "entitled_access" || mode !== "entitled_only" && tier.stage === "preprint")), log, pause, backend), watch);
            }
            catch (error) {
                result = laneError("entitled_access", error);
                log(`[批量] 机构下载出错（${id(offset)}）：${result.attempts[0].message}`);
            }
            if (result.status === "ok" && result.version === "preprint")
                preprints += 1;
            if (!away && waitedOutOnUser(result)) {
                away = true;
                log(AWAY_NOTICE);
            }
            const open = results[offset];
            results[offset] = itemResult({
                ...result,
                attempts: [...open.attempts, ...result.attempts],
                ...(result.review ?? open.review ? { review: result.review ?? open.review } : {}),
            }, offset + 1, request);
            const school = result.attempts.find((attempt) => attempt.stage === "entitled_access");
            const holding = result.status !== "ok" && wentThrough(offset) && school?.code === LOGIN_LAPSED_CODE
                && waitEnded.get(offset) === SCHOOL_SIGN_IN_PAGE && !stoppedByUser(result) && await canHold();
            // Its Markdown now, from the page this visit saved, or the open sources (only these
            // while its school login is in doubt).
            if (wantsMarkdown && !stoppedByUser(result)) {
                await markdownPastNetworkLoss(results[offset], recorded({ ...request, batch }, ledger, entries[offset]), searchers, holding ? undefined : pageVisit(backend, { ...request, batch, ...(away ? { shortUserWait: true } : {}) }, log, pause), watch);
            }
            if (result.status === "ok") {
                succeeded += 1;
                record(offset);
                settle(offset);
                if (school?.status === "ok")
                    cameThrough(offset);
            }
            else if (holding) {
                hold(offset);
            }
            else if (withoutAccess(result) && !stoppedByUser(result) && (await otherSchools()).length) {
                withoutAccessYet.add(offset);
                settle(offset, "school");
            }
            else if (unexplainedFailure(result)) {
                unexplainedYet.add(offset);
                settle(offset, "school");
            }
            else {
                failed += 1;
                record(offset);
                settle(offset);
            }
            // The window's line, not for a paper that waits for the end (it would close the batch early when last).
            if (!withoutAccessYet.has(offset) && !unexplainedYet.has(offset)) {
                await reportBatchItem({ ...request, batch: { ...batch, index: batch.done + 1 } }, result, backend);
            }
            if (publisherBlocked(result))
                log(blockedNotice(id(offset)));
            if (stoppedByUser(result)) {
                stopped = true;
                return;
            }
            // More to come: the lanes line goes on (after the last item the window has its end).
            if (openRunning || queue.length)
                await reportProgress("");
            if (held.size)
                await reportHeld();
            takeRequests();
            await sendPapers();
        }
    };
    if (mode === "entitled_only") {
        for (const [offset, request] of requests.entries()) {
            results[offset] = itemResult({ status: "error", attempts: [] }, offset + 1, request);
            missed.push(offset);
            queue.push(offset);
        }
        log(`[批量] 跳过开放来源，${total} 篇直接进入机构下载`);
        ledger?.phase(`机构下载 ${total} 篇`);
    }
    else
        ledger?.phase(`开放来源 ${total} 篇`);
    void sendPapers();
    await Promise.all([mode === "entitled_only" ? undefined : openLane(), entitledLane()]);
    // The held publishers wait for the user as long as it takes (user, 2026-11-15): the
    // window shows 登录并继续 and 终止. 登录并继续 downloads them, the school's login asking
    // the user where it lapsed; held again, the wait starts over. 终止 ends them as paused.
    if (held.size && !stopped) {
        const waiting = [...held.values()].reduce((sum, offsets) => sum + offsets.length, 0);
        log(`[批量] 其他篇目已完成，暂停的 ${waiting} 篇等你回来：在进度窗口点“登录并继续”，或点“终止”结束`);
        ledger?.phase(`等你回来：暂停的 ${waiting} 篇`);
    }
    while (held.size && !stopped) {
        await reportHeld(true);
        await pause(HOLD_POLL_MS);
        takeRequests();
        if (queue.length && !stopped) {
            await entitledLane();
        }
    }
    /** A paper's school stage once more, with another saved school when given; merged into its result. */
    const visitAgain = async (offset, school) => {
        const request = { ...requests[offset], ...(school ? { school: school.entityId } : {}) };
        const done = settledOk() + failed;
        const batch = { id: batchId, index: done + 1, total, done, succeeded: settledOk(), failed };
        log(school ? `[批量] 换${school.name}：${id(offset)}` : `[批量] 再试一次：${id(offset)}`);
        let result;
        try {
            result = await pastNetworkLoss(() => pastHourlyLimit(() => downloadWithFallback(searchers, watchingSchool(recorded({ ...request, batch, ...(away ? { shortUserWait: true } : {}) }, ledger, entries[offset]), offset), createTiers(backend).filter((tier) => tier.stage === "entitled_access")), log, pause, backend), watch);
        }
        catch (error) {
            result = laneError("entitled_access", error);
            log(`[批量] 机构下载出错（${id(offset)}）：${result.attempts[0].message}`);
        }
        const before = results[offset];
        const markdown = result.markdown ?? before.markdown;
        results[offset] = itemResult({
            ...result,
            attempts: [...before.attempts, ...result.attempts],
            ...(result.review ?? before.review ? { review: result.review ?? before.review } : {}),
            ...(markdown ? { markdown } : {}),
        }, offset + 1, requests[offset]);
        const item = results[offset];
        // Its Markdown from the page this visit saved, unless the open sources gave it already.
        if (wantsMarkdown && result.status === "ok" && item.markdown?.status !== "ok") {
            await markdownPastNetworkLoss(item, recorded({ ...request, batch }, ledger, entries[offset]), searchers, pageVisit(backend, { ...request, batch, ...(away ? { shortUserWait: true } : {}) }, log, pause), watch);
        }
        if (stoppedByUser(result))
            stopped = true;
        if (publisherBlocked(result))
            log(blockedNotice(id(offset)));
        return item;
    };
    /** The window's line for a paper finished at the end (the counts before it, as ``reportBatchItem`` takes them). */
    const reportSettled = async (offset) => {
        const done = settledOk() + failed;
        await reportBatchItem({ ...requests[offset], batch: { id: batchId, index: done + 1, total, done, succeeded: settledOk(), failed } }, results[offset], backend);
    };
    // 原因不明 once more, the default school still signed in, before any other school (user, 2026-11-22).
    if (unexplainedYet.size && !stopped) {
        log(`[批量] 原因不明的 ${unexplainedYet.size} 篇再试一次`);
        ledger?.phase(`原因不明的 ${unexplainedYet.size} 篇再试一次`);
        for (const offset of [...unexplainedYet]) {
            if (stopped)
                break;
            const item = await visitAgain(offset);
            unexplainedYet.delete(offset);
            if (!stopped && item.status !== "ok" && withoutAccess(item) && (await otherSchools()).length) {
                withoutAccessYet.add(offset);
            }
            else {
                await reportSettled(offset);
                if (item.status === "ok")
                    succeeded += 1;
                else
                    failed += 1;
                record(offset);
                settle(offset);
            }
            await sendPapers();
        }
    }
    for (const offset of unexplainedYet) {
        await reportSettled(offset);
        failed += 1;
        record(offset);
    }
    unexplainedYet.clear();
    // The papers without access go to the other saved schools, one school at a time.
    const withSchool = async (offset, school) => {
        const item = await visitAgain(offset, school);
        schoolsTried.set(offset, (schoolsTried.get(offset) ?? 1) + 1);
        if (!stopped && withoutAccess(item)) {
            triedSchools(item, schoolsTried.get(offset));
        }
        else {
            withoutAccessYet.delete(offset);
            await reportSettled(offset);
            if (item.status === "ok")
                succeeded += 1;
            else
                failed += 1;
            record(offset);
            settle(offset);
        }
        await sendPapers();
    };
    if (withoutAccessYet.size && !stopped) {
        await laterSchools(await otherSchools(), () => [...withoutAccessYet], async (school, count) => {
            log(`[批量] 没权限的 ${count} 篇换${school.name}再试`);
            ledger?.phase(`没权限的 ${count} 篇换${school.name}再试`);
            if (!backend?.reportBatchProgress)
                return;
            const update = { id: batchId, total, done: settledOk() + failed, succeeded: settledOk(), failed, current: "",
                finished: false, phase: `没权限，换${school.name}` };
            reports = reports.then(() => backend.reportBatchProgress(update)).catch(() => false);
            await reports;
        }, withSchool, () => stopped);
    }
    // Without access with every school (or the batch stopped first): failed.
    for (const offset of withoutAccessYet) {
        await reportSettled(offset);
        failed += 1;
        record(offset);
    }
    withoutAccessYet.clear();
    await reports;
    // Stopped in the window: the items neither lane reached end as not downloaded, the held as paused.
    if (stopped) {
        markPaused();
        for (const [offset, request] of requests.entries()) {
            const item = results[offset];
            if (!item)
                results[offset] = itemResult({ status: "error", attempts: [notReached()] }, offset + 1, request);
            else if (finishing.has(offset)) {
                // Its PDF stands; its browser's part was not reached.
                if (wantsFiles)
                    item.supplements = [{ status: "skipped", label: "", reason: "batch_stopped" }];
            }
            else if (queue.includes(offset)) {
                results[offset] = itemResult({ ...item, status: "error", attempts: [...item.attempts, notReached()] }, offset + 1, request);
            }
            else if (!recordedOffsets.has(offset) && item.status === "ok") {
                item.supplements = [{ status: "skipped", label: "", reason: "batch_stopped" }];
            }
            record(offset);
        }
        log(STOP_NOTICE);
    }
    const items = results;
    const remaining = missed.length;
    // Every paper as it ended, before the window's finished card.
    requests.forEach((_, offset) => settle(offset));
    await sendPapers(true);
    ledger?.close({ entitledAccessItems: remaining });
    return summary(mode, batchId, items, {
        content: options.content ?? "main",
        entitledAccessItems: remaining,
        ...(ledger ? { runLog: ledger.dir } : {}),
        ...(stopped ? { stopped: true } : {}),
    });
}
//# sourceMappingURL=batch.js.map