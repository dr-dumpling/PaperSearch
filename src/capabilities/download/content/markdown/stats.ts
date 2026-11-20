/**
 * The Markdown saved on this computer, for the settings window's PaperSearch Pro page (user,
 * 2026-11-19): how many, and how many with nothing noted as possibly missing, in ``pro/stats.json``
 * of PaperSearch's data, beside Pro's own records (an install keeps them). Counts only, never sent
 * anywhere; writing them never changes a download.
 */
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { paperSearchDataHome } from "../../../../infrastructure/school/index.js";

export interface MarkdownStats {
  converted: number;
  complete: number;
}

export function markdownStatsFile(env: Record<string, string | undefined> = process.env): string {
  return join(paperSearchDataHome(env), "pro", "stats.json");
}

export function readMarkdownStats(env: Record<string, string | undefined> = process.env): MarkdownStats {
  try {
    const read = JSON.parse(readFileSync(markdownStatsFile(env), "utf8")) as Partial<MarkdownStats>;
    const count = (value: unknown) => (Number.isInteger(value) && (value as number) >= 0 ? value as number : 0);
    const converted = count(read.converted);
    return { converted, complete: Math.min(converted, count(read.complete)) };
  } catch {
    return { converted: 0, complete: 0 };
  }
}

/** One Markdown saved; ``complete``: nothing noted as possibly missing. */
export function recordMarkdownSaved(complete: boolean, env: Record<string, string | undefined> = process.env): void {
  const file = markdownStatsFile(env);
  try {
    const stats = readMarkdownStats(env);
    mkdirSync(dirname(file), { recursive: true });
    const temp = `${file}.${process.pid}.tmp`;
    writeFileSync(temp, `${JSON.stringify({ schemaVersion: 1, converted: stats.converted + 1,
      complete: stats.complete + (complete ? 1 : 0) })}\n`);
    renameSync(temp, file);
  } catch {
    // Not counted: the page shows what was counted before.
  }
}
