import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describeFailure, FAILURE_CLASSES, FAILURE_CLASS_LABELS, hostOf, } from "../../infrastructure/runlog/failureClass.js";
export function summarizeFailures(root, query = {}) {
    const runs = selectRuns(root, query);
    const classes = Object.fromEntries(FAILURE_CLASSES.map((c) => [c, 0]));
    const groups = new Map();
    let failed = 0;
    let notAttempted = 0;
    for (const runId of runs) {
        for (const item of readItems(join(root, runId, "items.jsonl"))) {
            if (item.status === "ok")
                continue;
            const stages = Array.isArray(item.stages) ? item.stages : [];
            const stage = [...stages].reverse().find((s) => s.stage === "entitled_access");
            if (!stage || stage.status !== "error") {
                notAttempted += 1;
                continue;
            }
            failed += 1;
            const code = typeof stage.code === "string" && stage.code ? stage.code : "download_failed";
            const backend = stage.backend;
            const description = typeof stage.failureClass === "string"
                ? {
                    failureClass: stage.failureClass,
                    ...(typeof stage.evidence === "string" ? { evidence: stage.evidence } : {}),
                    ...(typeof stage.stoppedAt === "string" ? { stoppedAt: stage.stoppedAt } : {}),
                }
                : describeFailure(code, backend, stage.trace);
            const detail = (backend?.diagnostic ?? backend?.record);
            const trace = (stage.trace ?? {});
            const publisher = typeof trace.publisher === "string" && trace.publisher ? trace.publisher : "-";
            const site = hostOf(detail?.final_url) || hostOf(detail?.article_url) || "-";
            classes[description.failureClass] += 1;
            const key = [description.failureClass, publisher, site, code].join("\u0000");
            const group = groups.get(key) ?? {
                failureClass: description.failureClass, publisher, site, code, count: 0, items: [],
            };
            group.count += 1;
            if (!group.evidence && description.evidence)
                group.evidence = description.evidence;
            const diagnostic = backend?.diagnostic?.file;
            group.items.push({
                doi: String(item.doi ?? item.paperId ?? ""),
                runId,
                ...(description.evidence ? { evidence: description.evidence } : {}),
                ...(description.stoppedAt ? { stoppedAt: description.stoppedAt } : {}),
                ...(typeof diagnostic === "string" ? { diagnostic } : {}),
            });
            groups.set(key, group);
        }
    }
    const order = (c) => FAILURE_CLASSES.indexOf(c);
    return {
        root,
        runs,
        failed,
        notAttempted,
        classes,
        groups: [...groups.values()].sort((a, b) => order(a.failureClass) - order(b.failureClass) || b.count - a.count),
    };
}
/** Run directories are named <yyyymmdd>-<hhmmss>-<id>, so names sort by start time. */
function selectRuns(root, query) {
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
function readItems(file) {
    if (!existsSync(file))
        return [];
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
            lines.push(`  ${group.publisher} · ${group.site} · ${group.code}  ${group.count}`);
            if (failureClass === "no_access" && group.evidence)
                lines.push(`    依据：${group.evidence}`);
            if (failureClass !== "unexplained")
                continue;
            for (const item of group.items.slice(0, shown)) {
                lines.push(`    ${item.doi}` +
                    (item.stoppedAt ? `  停在 ${item.stoppedAt}` : "") +
                    (item.diagnostic ? `\n      ${item.diagnostic}` : ""));
            }
            if (group.items.length > shown)
                lines.push(`    …另 ${group.items.length - shown} 篇（--all 全部列出）`);
        }
    }
    return lines.join("\n");
}
function day(runId) {
    return `${runId.slice(0, 4)}-${runId.slice(4, 6)}-${runId.slice(6, 8)}`;
}
//# sourceMappingURL=index.js.map