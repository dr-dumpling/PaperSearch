import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { classifyFailureCode, describeFailure, FAILURE_CLASSES, FAILURE_CLASS_LABELS, hostOf, } from "../../infrastructure/runlog/failureClass.js";
import { CHALLENGE_TYPE_LABELS, schoolShortReason } from "../../infrastructure/school/index.js";
/**
 * The codes of a paper the batch left untried while its publisher was paused (被网站拦截, 学校登录中途失效): its run
 * record has the school stage the batch gave it, no visit (batch.ts ``untried``).
 */
const UNTRIED = new Set(["blocked_paused", "login_paused"]);
/** One entry per failed paper, including a saved main text with incomplete attachments. */
export function selectFailures(root, query = {}, options = {}) {
    const runs = selectRuns(root, query);
    const papers = [];
    let notAttempted = 0;
    let exportBytes = 0;
    for (const runId of runs) {
        for (const item of readItems(join(root, runId, "items.jsonl"))) {
            const doi = String(item.doi ?? item.paperId ?? "");
            if (query.doi && doi.toLowerCase() !== query.doi.toLowerCase())
                continue;
            const supplements = Array.isArray(item.supplements) ? item.supplements : [];
            const incomplete = supplements.find((f) => f.status === "failed" ||
                (f.status === "skipped" && !["no_supplements", "not_requested"].includes(String(f.reason))));
            if (item.status === "ok" && !incomplete)
                continue;
            const stages = Array.isArray(item.stages) ? item.stages : [];
            // The batch's mark on a paper its publisher's pause left untried is no visit: the export keeps to the paper's
            // visits (an earlier one, or none: not attempted), the summary counts the mark as the batch's last line does.
            const visits = options.forExport
                ? stages.filter((s) => !(s.stage === "entitled_access" && UNTRIED.has(String(s.code)))) : stages;
            const main = [...visits].reverse().find((s) => s.stage === "entitled_access");
            const attachment = [...stages].reverse().find((s) => s.stage === "supplements");
            const part = incomplete && (item.status === "ok" || !main || main.status !== "error") ? "supplements" : undefined;
            const stage = part ? attachment ?? main : main;
            if (!stage || (!part && stage.status !== "error")) {
                notAttempted += 1;
                continue;
            }
            const trace = (stage.trace ?? {});
            const recorded = String((part ? incomplete?.reason : stage.code) || "download_failed");
            // Before 2026-11-22 a publisher's article page without the login entry its rules look for was
            // reported as download_failed; the backend's state kept what it was.
            const code = !part && recorded === "download_failed" && trace.state === "publisher_institution_entry_missing"
                ? trace.state : recorded;
            const backend = stage.backend;
            // A saved paper's missing file: its reason's class alone. The visit's last step was the
            // paper's own ("停在 pdf_saved"), not where the file failed (AHA, 2026-11-22).
            const paperSaved = part === "supplements" && item.status === "ok";
            const current = paperSaved ? { failureClass: classifyFailureCode(code) }
                : describeFailure(code, backend, stage.trace);
            // An unregistered entry's evidence as said now: records before 2026-11-19 may carry an old
            // inference of no subscription for it.
            const description = !part && FAILURE_CLASSES.includes(stage.failureClass)
                && code !== "institution_not_registered"
                && (current.failureClass === "unexplained" || current.failureClass === stage.failureClass)
                ? { failureClass: stage.failureClass,
                    ...(typeof stage.evidence === "string" ? { evidence: stage.evidence } : {}),
                    ...(typeof stage.stoppedAt === "string" ? { stoppedAt: stage.stoppedAt } : {}) }
                : current;
            const detail = (backend?.diagnostic ?? backend?.record ?? {});
            const diagnostic = backend?.diagnostic?.file ?? trace.diagnostic;
            const record = backend?.record?.file ?? trace.record;
            const paper = { doi, runId, ...description,
                publisher: typeof trace.publisher === "string" && trace.publisher ? trace.publisher : "-",
                site: hostOf(detail.final_url) || hostOf(detail.article_url) || "-", code,
                ...(!part && typeof trace.challengeType === "string" && Object.hasOwn(CHALLENGE_TYPE_LABELS, trace.challengeType)
                    ? { challengeType: trace.challengeType } : {}),
                ...(part ? { part } : {}),
                ...(paperSaved ? { paperSaved: true } : {}),
                ...(typeof diagnostic === "string" && diagnostic ? { diagnostic } : {}),
                // Local paths for the text summary; an export takes the pictures from the diagnostic itself.
                ...(!options.forExport && screenshotsOf(backend).length ? { screenshots: screenshotsOf(backend) } : {}),
                ...(typeof record === "string" && record ? { record } : {}),
                detail: options.forExport ? detail : {},
                outcome: options.forExport ? { status: item.status, supplements,
                    stages: stages.map(({ stage, status, code, message, startedAt, durationMs }) => ({ stage, status, code, message, startedAt, durationMs })) } : {}, };
            if (options.forExport) {
                exportBytes += Buffer.byteLength(JSON.stringify(paper));
                if (papers.length >= 100 || exportBytes > 8 * 1024 * 1024 - 1024) {
                    throw new Error("导出选择超过 100 篇或 8 MiB，请用 --run 或 --doi 缩小范围。");
                }
            }
            papers.push(paper);
        }
    }
    return { runs, papers, notAttempted };
}
export function summarizeFailures(root, query = {}) {
    const { runs, papers, notAttempted } = selectFailures(root, query);
    const classes = Object.fromEntries(FAILURE_CLASSES.map((c) => [c, 0]));
    const groups = new Map();
    const shortfalls = new Map();
    let failed = 0;
    for (const paper of papers) {
        const { failureClass, publisher, site, code, challengeType } = paper;
        const key = [failureClass, publisher, site, code, challengeType ?? ""].join("\u0000");
        const entry = { doi: paper.doi, runId: paper.runId,
            ...(paper.evidence ? { evidence: paper.evidence } : {}),
            ...(paper.stoppedAt ? { stoppedAt: paper.stoppedAt } : {}),
            ...(paper.diagnostic ? { diagnostic: paper.diagnostic } : {}),
            ...(paper.screenshots ? { screenshots: paper.screenshots } : {}),
            ...(paper.part ? { part: paper.part } : {}),
        };
        if (paper.paperSaved) {
            // Saved, a file short: not a failure of the paper (the batch counts it succeeded).
            const group = shortfalls.get(key) ?? { failureClass, publisher, site, code,
                reason: schoolShortReason(code, "附录没下载成功"), count: 0, items: [] };
            group.count += 1;
            group.items.push(entry);
            shortfalls.set(key, group);
            continue;
        }
        failed += 1;
        classes[failureClass] += 1;
        const group = groups.get(key) ?? { failureClass, publisher, site, code,
            ...(challengeType ? { challengeType } : {}), count: 0, items: [] };
        group.count += 1;
        if (!group.evidence && paper.evidence)
            group.evidence = paper.evidence;
        group.items.push(entry);
        groups.set(key, group);
    }
    const order = (c) => FAILURE_CLASSES.indexOf(c);
    const byClass = (list) => [...list].sort((a, b) => order(a.failureClass) - order(b.failureClass) || b.count - a.count);
    return { root, runs, failed, notAttempted, classes, groups: byClass(groups.values()),
        supplementsMissing: papers.length - failed, supplementGroups: byClass(shortfalls.values()) };
}
/** The diagnostic's screenshots: the page when it failed, then the pages kept on the way. */
function screenshotsOf(backend) {
    const diagnostic = backend?.diagnostic;
    const listed = Array.isArray(diagnostic?.screenshots) ? diagnostic.screenshots : [];
    return [...new Set(listed.filter((file) => typeof file === "string" && file !== ""))];
}
/** Run directories are named <yyyymmdd>-<hhmmss>-<id>, so names sort by start time. */
export function selectRuns(root, query) {
    if (!existsSync(root))
        return [];
    const all = readdirSync(root, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && /^\d{8}-\d{6}-/.test(entry.name))
        .map((entry) => entry.name)
        .sort();
    if (query.run && query.run !== "latest")
        return all.filter((name) => name === query.run);
    if (query.since) {
        const day = query.since.replace(/-/g, "");
        return all.filter((name) => name.slice(0, 8) >= day);
    }
    if (query.runs && query.runs > 0)
        return all.slice(-query.runs);
    return all.slice(-1);
}
export function readItems(file) {
    if (!existsSync(file))
        return [];
    if (statSync(file).size > 64 * 1024 * 1024)
        throw new Error("运行记录超过 64 MiB，无法安全汇总此批次。");
    const items = [];
    for (const line of readFileSync(file, "utf8").split("\n")) {
        if (!line.trim())
            continue;
        try {
            const item = JSON.parse(line);
            if (item && typeof item === "object" && !Array.isArray(item))
                items.push(item);
        }
        catch {
            // A line cut off by an interrupted run.
        }
    }
    return items;
}
export function renderFailuresText(summary, options = {}) {
    const shown = options.all ? Infinity : 5;
    const span = summary.runs.length
        ? `${day(summary.runs[0])} 至 ${day(summary.runs[summary.runs.length - 1])}，${summary.runs.length} 个批次`
        : "没有运行记录";
    const lines = [
        `失败汇总：${span}；机构下载失败 ${summary.failed} 篇` +
            (summary.notAttempted ? `（另有 ${summary.notAttempted} 篇没有走到机构下载）` : ""),
        `运行记录：${summary.root}`,
    ];
    for (const failureClass of FAILURE_CLASSES) {
        const groups = summary.groups.filter((g) => g.failureClass === failureClass);
        if (!groups.length)
            continue;
        lines.push("", `${FAILURE_CLASS_LABELS[failureClass]}  ${summary.classes[failureClass]}`);
        for (const group of groups) {
            const kind = group.challengeType ? ` · ${CHALLENGE_TYPE_LABELS[group.challengeType]}` : "";
            lines.push(`  ${group.publisher} · ${group.site} · ${group.code}${kind}  ${group.count}`);
            if (failureClass === "no_access" && group.evidence)
                lines.push(`    依据：${group.evidence}`);
            if (failureClass !== "unexplained" && failureClass !== "unsupported")
                continue;
            for (const item of group.items.slice(0, shown)) {
                lines.push(`    ${item.doi}` +
                    (item.stoppedAt ? `  停在 ${item.stoppedAt}` : "") +
                    (item.diagnostic ? `\n      ${item.diagnostic}` : "") +
                    (item.screenshots ?? []).map((file) => `\n      截图：${file}`).join(""));
            }
            if (group.items.length > shown)
                lines.push(`    …另 ${group.items.length - shown} 篇（--all 全部列出）`);
        }
    }
    // Saved papers short of some files, apart from the failures (the batch's last line: 附录未下全).
    if (summary.supplementsMissing) {
        lines.push("", `附录未下全  ${summary.supplementsMissing}（正文已保存，不算失败）`);
        for (const group of summary.supplementGroups) {
            lines.push(`  ${group.publisher} · ${group.site} · ${group.reason} · ${group.code}  ${group.count}`);
            for (const item of group.items.slice(0, shown))
                lines.push(`    ${item.doi}`);
            if (group.items.length > shown)
                lines.push(`    …另 ${group.items.length - shown} 篇（--all 全部列出）`);
        }
    }
    const toLookInto = (c) => c === "unsupported" || c === "unexplained";
    if (summary.classes.unsupported || summary.classes.unexplained
        || summary.supplementGroups.some((group) => toLookInto(group.failureClass))) {
        lines.push("", "要我们排查：paper-search failures --export <文件.zip> 导出记录（发出前先看一遍），发给我们。");
    }
    return lines.join("\n");
}
function day(runId) {
    return `${runId.slice(0, 4)}-${runId.slice(4, 6)}-${runId.slice(6, 8)}`;
}
//# sourceMappingURL=index.js.map