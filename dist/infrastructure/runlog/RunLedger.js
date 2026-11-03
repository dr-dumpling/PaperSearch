import { randomBytes } from "node:crypto";
import { appendFileSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync, } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { describeFailure } from "./failureClass.js";
/**
 * Local record of every download run, so a failure can be traced afterwards:
 * which stages ran, how long each took, what the backend's browser reached and
 * where it stopped. One directory per run:
 *
 *   run.json      what was run, when, and the final counts
 *   items.jsonl   one line per finished item with all its stages and the
 *                 backend's collapsed page events
 *   timeline.log  human-readable, appended as each stage finishes
 *
 * Root: PAPER_SEARCH_RUNLOG_DIR, else $XDG_DATA_HOME/paper-search-cli/runs
 * (default ~/.local/share/paper-search-cli/runs). PAPER_SEARCH_RUNLOG=0
 * turns it off. Write failures are reported once on stderr and never change a
 * download outcome.
 */
export function resolveRunLogRoot(env = process.env, home = homedir()) {
    if (env.PAPER_SEARCH_RUNLOG === "0")
        return null;
    if (env.PAPER_SEARCH_RUNLOG_DIR)
        return resolve(env.PAPER_SEARCH_RUNLOG_DIR);
    const base = env.XDG_DATA_HOME
        ? resolve(env.XDG_DATA_HOME)
        : join(home, ".local", "share");
    return join(base, "paper-search-cli", "runs");
}
const MAX_BACKEND_FILE_BYTES = 8 * 1024 * 1024;
const MAX_EVENTS = 400;
const BACKEND_FIELDS = [
    "status",
    "state",
    "reason",
    "article_url",
    "final_url",
    "pdf_url",
    "title",
    "access_state",
    "access_evidence",
    "adapter",
    "browser",
    "size_bytes",
    "verified_match",
    "events_truncated",
    "browser_start",
    "phases",
    "pdf_attempts",
    "snapshots",
];
export class RunLedger {
    dir;
    run;
    stages = new Map();
    started = new Map();
    succeeded = 0;
    failed = 0;
    warned = false;
    constructor(dir, run) {
        this.dir = dir;
        this.run = run;
    }
    static open(start, env = process.env, now = new Date()) {
        const root = resolveRunLogRoot(env);
        if (!root)
            return null;
        const runId = `${stamp(now)}-${randomBytes(3).toString("hex")}`;
        const dir = join(root, runId);
        try {
            mkdirSync(dir, { recursive: true });
        }
        catch (error) {
            process.stderr.write(`[运行记录] 无法创建目录 ${dir}：${describe(error)}\n`);
            return null;
        }
        const ledger = new RunLedger(dir, {
            schema: 1,
            runId,
            ...start,
            startedAt: now.toISOString(),
            pid: process.pid,
            cwd: process.cwd(),
        });
        ledger.writeRun();
        ledger.line(`run ${runId} ${start.kind}${start.mode ? ` ${start.mode}` : ""} total=${start.total}`);
        return ledger;
    }
    phase(text) {
        this.line(`== ${text}`);
    }
    stage(item, record) {
        if (!this.started.has(item.index)) {
            this.started.set(item.index, Date.parse(record.startedAt) || Date.now());
        }
        const backend = record.trace ? readBackendRecords(record.trace) : undefined;
        // A failed institutional download is classified (ADR 0012).
        const failure = record.stage === "entitled_access" && record.status === "error"
            ? describeFailure(record.code, backend, record.trace)
            : undefined;
        const entry = {
            ...record,
            ...(backend ? { backend } : {}),
            ...(failure ?? {}),
        };
        const list = this.stages.get(item.index) ?? [];
        list.push(entry);
        this.stages.set(item.index, list);
        this.line(`#${item.index} ${label(item)} ${record.stage} ${record.status}` +
            `${record.code ? ` ${record.code}` : ""}${failure ? ` class=${failure.failureClass}` : ""}` +
            ` ${(record.durationMs / 1000).toFixed(1)}s` +
            backendSummary(record.trace, backend));
    }
    item(item, result) {
        if (result.status === "ok")
            this.succeeded += 1;
        else
            this.failed += 1;
        const endedAt = Date.now();
        const startedAt = this.started.get(item.index) ?? endedAt;
        const line = {
            index: item.index,
            paperId: item.paperId,
            ...(item.doi ? { doi: item.doi } : {}),
            ...(item.title ? { title: item.title } : {}),
            status: result.status,
            ...(result.path ? { path: result.path } : {}),
            ...(result.format ? { format: result.format } : {}),
            ...(result.review ? { review: result.review } : {}),
            ...(result.supplements ? { supplements: result.supplements } : {}),
            startedAt: new Date(startedAt).toISOString(),
            endedAt: new Date(endedAt).toISOString(),
            durationMs: endedAt - startedAt,
            stages: this.stages.get(item.index) ?? [],
        };
        this.append("items.jsonl", `${JSON.stringify(line)}\n`);
        this.line(`#${item.index} ${label(item)} => ${result.status}` +
            (result.path ? ` ${result.path}` : "") +
            (result.review ? ` review=${result.review.reason} ${result.review.path}` : "") +
            (result.supplements
                ? ` supplements=${result.supplements.filter((f) => f.status === "saved").length}/${result.supplements.length}`
                : ""));
        this.stages.delete(item.index);
        this.started.delete(item.index);
    }
    close(extra = {}) {
        Object.assign(this.run, extra, {
            endedAt: new Date().toISOString(),
            succeeded: this.succeeded,
            failed: this.failed,
        });
        this.writeRun();
        this.line(`end succeeded=${this.succeeded} failed=${this.failed}`);
    }
    writeRun() {
        try {
            writeFileSync(join(this.dir, "run.json"), `${JSON.stringify(this.run, null, 2)}\n`);
        }
        catch (error) {
            this.warn(error);
        }
    }
    line(text) {
        this.append("timeline.log", `${localTime(new Date())} ${text}\n`);
    }
    append(file, text) {
        try {
            appendFileSync(join(this.dir, file), text);
        }
        catch (error) {
            this.warn(error);
        }
    }
    warn(error) {
        if (this.warned)
            return;
        this.warned = true;
        process.stderr.write(`[运行记录] 写入 ${this.dir} 失败：${describe(error)}\n`);
    }
}
/** The backend's record/diagnostic JSON, reduced to what explains the outcome. */
function readBackendRecords(trace) {
    const out = {};
    for (const key of ["record", "diagnostic"]) {
        const file = trace[key];
        if (typeof file !== "string" || !file)
            continue;
        out[key] = readBackendFile(file);
    }
    return Object.keys(out).length ? out : undefined;
}
function readBackendFile(file) {
    try {
        const size = statSync(file).size;
        if (size > MAX_BACKEND_FILE_BYTES)
            return { file, error: `too large (${size} bytes)` };
        const data = JSON.parse(readFileSync(file, "utf8"));
        const picked = { file };
        for (const field of BACKEND_FIELDS) {
            if (data[field] !== undefined && data[field] !== null && data[field] !== "") {
                picked[field] = data[field];
            }
        }
        if (Array.isArray(data.events))
            picked.events = collapseEvents(data.events);
        const screenshots = readdirSync(dirname(file))
            .filter((name) => /\.(?:png|jpe?g)$/i.test(name))
            .map((name) => join(dirname(file), name));
        if (screenshots.length)
            picked.screenshots = screenshots;
        return picked;
    }
    catch (error) {
        return { file, error: describe(error) };
    }
}
export function collapseEvents(events) {
    const out = [];
    for (const raw of events) {
        if (!raw || typeof raw !== "object")
            continue;
        const event = raw;
        const state = String(event.state ?? "");
        const at = typeof event.at === "string" ? event.at : undefined;
        const previous = out[out.length - 1];
        if (previous && previous.state === state) {
            previous.count = (previous.count ?? 1) + 1;
            if (at)
                previous.lastAt = at;
            continue;
        }
        const detail = event.detail === undefined || event.detail === "" ? undefined : String(event.detail);
        out.push({
            state,
            ...(at ? { at } : {}),
            ...(detail ? { detail: detail.length > 500 ? `${detail.slice(0, 500)}…` : detail } : {}),
        });
    }
    return out.length > MAX_EVENTS
        ? [...out.slice(0, MAX_EVENTS / 2), { state: "…", count: out.length - MAX_EVENTS }, ...out.slice(-MAX_EVENTS / 2)]
        : out;
}
function backendSummary(trace, backend) {
    if (!trace)
        return "";
    const parts = [];
    const who = [trace.publisher, trace.driver].filter((v) => typeof v === "string" && v).join("/");
    if (who)
        parts.push(who);
    if (typeof trace.state === "string" && trace.state)
        parts.push(`state=${trace.state}`);
    if (typeof trace.identity === "string")
        parts.push(`identity=${trace.identity}`);
    if (typeof trace.exception === "string")
        parts.push(`exception=${trace.exception}`);
    const detail = (backend?.diagnostic ?? backend?.record);
    if (detail) {
        const events = detail.events;
        const last = events?.length ? events[events.length - 1].state : "";
        if (last)
            parts.push(`last=${last}`);
        if (typeof detail.final_url === "string")
            parts.push(`url=${detail.final_url.slice(0, 160)}`);
    }
    return parts.length ? ` [${parts.join(" ")}]` : "";
}
function label(item) {
    return item.doi || item.paperId;
}
function stamp(now) {
    const pad = (n) => String(n).padStart(2, "0");
    return (`${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-` +
        `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`);
}
function localTime(now) {
    const pad = (n) => String(n).padStart(2, "0");
    return (`${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ` +
        `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`);
}
function describe(error) {
    return error instanceof Error ? `${error.name}: ${error.message}` : String(error);
}
//# sourceMappingURL=RunLedger.js.map