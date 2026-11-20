/**
 * The Markdown saved on this computer, for the settings window's PaperSearch Pro page (user,
 * 2026-11-19): how many, and how many with nothing noted as possibly missing, in ``pro/stats.json``
 * of PaperSearch's data, beside Pro's own records (an install keeps them). Counts only, never sent
 * anywhere; writing them never changes a download.
 */
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { paperSearchDataHome } from "../../../../infrastructure/school/index.js";
export function markdownStatsFile(env = process.env) {
    return join(paperSearchDataHome(env), "pro", "stats.json");
}
export function readMarkdownStats(env = process.env) {
    try {
        const read = JSON.parse(readFileSync(markdownStatsFile(env), "utf8"));
        const count = (value) => (Number.isInteger(value) && value >= 0 ? value : 0);
        const converted = count(read.converted);
        return { converted, complete: Math.min(converted, count(read.complete)) };
    }
    catch {
        return { converted: 0, complete: 0 };
    }
}
/** One Markdown saved; ``complete``: nothing noted as possibly missing. */
export function recordMarkdownSaved(complete, env = process.env) {
    const file = markdownStatsFile(env);
    try {
        const stats = readMarkdownStats(env);
        mkdirSync(dirname(file), { recursive: true });
        const temp = `${file}.${process.pid}.tmp`;
        writeFileSync(temp, `${JSON.stringify({ schemaVersion: 1, converted: stats.converted + 1,
            complete: stats.complete + (complete ? 1 : 0) })}\n`);
        renameSync(temp, file);
    }
    catch {
        // Not counted: the page shows what was counted before.
    }
}
//# sourceMappingURL=stats.js.map