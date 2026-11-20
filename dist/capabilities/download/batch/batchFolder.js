/**
 * A batch's own folder (user, 2026-11-17, after the ARD batch laid out so on Windows): named
 * for what it holds (Osteoarthritis Cartilage_2024-2026, the journal's abbreviation as its
 * papers' folders begin), the papers' folders straight inside it, beside one folder of its
 * records (user: the list too, not out among the papers):
 *
 *   _run/batch-args.json        what the batch was asked for (its first run)
 *   _run/batch.log              each run's progress lines, one after another
 *   _run/<run id>/              each run's records as the run ledger writes them (run.json,
 *                               items.jsonl, timeline.log, records/), 接着下 runs too
 *   _run/article_index.csv      every paper of the batch and how it went, as of its latest run
 *                               (its paths from the batch folder)
 *
 * Kept up as the batch goes: the run's files as they are written, the list every 25 papers
 * and at the end. Writing them never changes a download.
 */
import { proFeatures } from "../../../config/edition.js";
import { appendFileSync, cpSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, isAbsolute, join, relative, resolve } from "node:path";
import { resolveRunLogRoot } from "../../../infrastructure/runlog/RunLedger.js";
import { markdownDoubt, markdownMissing } from "../content/markdown/shortfall.js";
import { latestPapers } from "./resume.js";
import { schoolShortReason } from "../../../infrastructure/school/index.js";
export const RUN_FOLDER = "_run";
export const INDEX_FILE = "article_index.csv";
/** The list is written again after this many papers. */
const INDEX_EVERY = 25;
/** A batch folder's name as given ("Osteoarthritis Cartilage_2024-2026"), safe on every system; undefined when none is left. */
export function batchFolderName(name) {
    const safe = (name ?? "").replace(/[<>:"/\\|?*\u0000-\u001f]+/g, "_").replace(/^[\s.]+|[\s.]+$/g, "").slice(0, 120);
    return safe && safe !== RUN_FOLDER ? safe : undefined;
}
function localTime(now) {
    const p = (n) => String(n).padStart(2, "0");
    return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())} ${p(now.getHours())}:${p(now.getMinutes())}:${p(now.getSeconds())}`;
}
/**
 * The batch's records in ``folder`` from now on: what it was asked (``args``), its lines, and
 * its run's files once the run ledger is attached. Undefined when the folder cannot be written.
 */
export function openBatchFolder(folder, args) {
    const runs = join(folder, RUN_FOLDER);
    try {
        mkdirSync(runs, { recursive: true });
        const first = join(runs, "batch-args.json");
        if (!existsSync(first))
            writeFileSync(first, `${JSON.stringify(args, null, 2)}\n`);
    }
    catch {
        return undefined;
    }
    let ledger = null;
    let own;
    const attach = (opened) => {
        if (!opened)
            return;
        ledger = opened;
        own = join(runs, basename(opened.dir));
        opened.mirrorTo(own);
        try {
            writeFileSync(join(own, "batch-args.json"), `${JSON.stringify(args, null, 2)}\n`);
        }
        catch {
            // The run's own copy of its arguments is a convenience; run.json says what ran.
        }
        let recorded = 0;
        opened.onItem = () => {
            if ((recorded += 1) % INDEX_EVERY === 0)
                refresh();
        };
    };
    const refresh = () => {
        if (ledger && own) {
            try {
                if (existsSync(ledger.records))
                    cpSync(ledger.records, join(own, "records"), { recursive: true, force: true });
            }
            catch {
                // The records stay in the run ledger.
            }
        }
        writeIndex(folder);
    };
    return {
        log: (line) => {
            try {
                appendFileSync(join(runs, "batch.log"), `${localTime(new Date())} ${line}\n`);
            }
            catch {
                // The lines still go to the caller.
            }
        },
        attach,
        refresh,
    };
}
/**
 * The runs of ``folder`` not yet in its _run (from before the folder kept them): copied from the
 * run ledger, so the list counts them too.
 */
function adoptEarlierRuns(folder) {
    const root = resolveRunLogRoot();
    if (!root || !existsSync(root))
        return;
    const here = resolve(folder);
    for (const name of readdirSync(root)) {
        if (!/^\d{8}-\d{6}-/.test(name) || existsSync(join(folder, RUN_FOLDER, name)))
            continue;
        try {
            const run = JSON.parse(readFileSync(join(root, name, "run.json"), "utf8"));
            if (run.kind !== "download_batch" || typeof run.savePath !== "string" || resolve(run.savePath) !== here)
                continue;
            mkdirSync(join(folder, RUN_FOLDER, name), { recursive: true });
            for (const file of ["run.json", "items.jsonl", "timeline.log", "records"]) {
                const from = join(root, name, file);
                if (existsSync(from))
                    cpSync(from, join(folder, RUN_FOLDER, name, file), { recursive: true, force: true });
            }
        }
        catch {
            // A run that cannot be read is left out of the list.
        }
    }
}
const SOURCES = {
    entitled_access: "机构下载",
    publisher_api: "开放下载 · 出版社 API",
    scihub: "开放下载 · Sci-Hub",
    preprint: "开放下载 · 预印本",
};
function supplementsCell(paper) {
    const files = paper.supplements;
    if (!files)
        return "";
    if (!files.length)
        return "没有附录";
    const saved = files.filter((file) => file.status === "saved").length;
    if (saved === files.length)
        return `已保存 ${saved}`;
    const reason = files.find((file) => file.status !== "saved")?.reason ?? "";
    if (reason === "supplements_not_supported")
        return saved ? `已保存 ${saved}/${files.length}` : "网站暂不支持自动下载附录";
    return `已保存 ${saved}/${files.length}：${schoolShortReason(reason, "附录没下载成功")}`;
}
function markdownCell(paper) {
    const markdown = paper.markdown;
    if (!markdown)
        return "";
    if (markdown.status === "ok") {
        // Its checks against a registered site's page found something short (user, 2026-11-17).
        const doubt = markdownDoubt({ status: "ok", possiblyMissing: markdown.possiblyMissing, message: "" });
        return doubt ? `已保存（${doubt.note}）` : "已保存";
    }
    return `未生成：${markdownMissing({ status: markdown.status, code: markdown.code, message: "" }).reason}`;
}
function csvCell(value) {
    const text = String(value);
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}
/** _run/article_index.csv of ``folder``: every paper of its runs, as of the latest, its paths from ``folder``. */
export function writeIndex(folder) {
    try {
        adoptEarlierRuns(folder);
        const runs = join(folder, RUN_FOLDER);
        // Oldest first, by when each began (two runs in one second sort by their random ends).
        const began = (dir) => {
            try {
                return String(JSON.parse(readFileSync(join(dir, "run.json"), "utf8")).startedAt ?? "");
            }
            catch {
                return "";
            }
        };
        const dirs = (existsSync(runs) ? readdirSync(runs).filter((name) => /^\d{8}-\d{6}-/.test(name)) : [])
            .map((name) => join(runs, name))
            .map((dir) => ({ dir, at: began(dir) }))
            .sort((a, b) => a.at.localeCompare(b.at) || a.dir.localeCompare(b.dir))
            .map(({ dir }) => dir);
        const papers = [...latestPapers(dirs).values()].sort((a, b) => a.index - b.index);
        if (!papers.length)
            return;
        const within = (path) => (path && isAbsolute(path) ? relative(folder, path) : path).replace(/\\/g, "/");
        const rows = papers.map((paper, offset) => {
            const pdf = paper.status === "ok" && /\.pdf$/i.test(paper.path) ? within(paper.path) : "";
            // The paper's folder: its PDF's, or its Markdown's (markdown/article.md inside it).
            const inside = paper.status === "ok" && paper.path ? join(paper.path, "..")
                : paper.markdownFile ? join(paper.markdownFile, "..", "..") : "";
            const paperFolder = inside ? within(inside) : "";
            return [offset + 1, paper.doi, paper.title, paper.status === "ok" ? "成功" : "失败", pdf,
                paper.source ? SOURCES[paper.source] ?? "开放下载 · 开放获取" : "",
                supplementsCell(paper), markdownCell(paper),
                paper.status !== "ok" ? schoolShortReason(paper.reason, paper.reason ?? "") : "",
                paperFolder === "." ? "" : paperFolder];
        });
        const header = ["index", "doi", "title", "status", "pdf", "source", "supplements", "markdown", "reason", "folder"];
        // The markdown column only with PaperSearch Pro's features (config/edition.ts).
        const pro = proFeatures();
        const shown = (row) => pro ? row : row.filter((_, at) => header[at] !== "markdown");
        // With a byte-order mark, so that Excel reads it as UTF-8.
        writeFileSync(join(runs, INDEX_FILE), `﻿${[header, ...rows].map((row) => shown(row).map(csvCell).join(",")).join("\r\n")}\r\n`);
    }
    catch {
        // The list is a convenience; the run's records stand.
    }
}
//# sourceMappingURL=batchFolder.js.map