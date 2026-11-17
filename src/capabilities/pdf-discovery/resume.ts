/**
 * 接着下: what an earlier batch left undone, from its run ledger, for one more batch into
 * the same download folder (user, 2026-11-15). A paper not saved is downloaded again with
 * the batch's content; a paper saved without all its supplementary files (missing, failed,
 * not reached when the batch stopped) gets only those, beside its PDF. The runs that went
 * on with a batch name it (``resumeOf``): the batch and those runs are read together, the
 * latest record of each paper counting, so going on again asks only for what is still missing.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { resolveRunLogRoot } from "../../infrastructure/runlog/RunLedger.js";
import type { DownloadBatchItem } from "./batch.js";
import type { SupplementFile } from "./types.js";

/** The content kinds a batch asked for, as the ledger keeps them. */
export type ResumeContent = "main" | "supplements" | "both";

export interface ResumePlan {
  /** The batch gone on with (the first of its chain). */
  runId: string;
  /** Its download folder: the new files go there too. */
  folder: string;
  content: ResumeContent;
  /** Papers not saved: downloaded again with ``content``. */
  retry: DownloadBatchItem[];
  /** Papers saved without all their supplementary files: those only, beside ``mainPath``. */
  files: DownloadBatchItem[];
  /** Papers with nothing missing. */
  complete: number;
}

interface LedgerPaper {
  index: number;
  doi: string;
  paperId: string;
  title: string;
  status: string;
  path: string;
  supplements?: SupplementFile[];
  /** Its PDF came from the institutional visit, which also checks the supplementary files. */
  byVisit?: boolean;
}

/** The stop's own entries: nothing was tried for these files. */
const NOT_TRIED = new Set(["batch_stopped", "user_skipped"]);
const notTried = (files: SupplementFile[]) =>
  files.length > 0 && files.every((file) => file.status !== "saved" && NOT_TRIED.has(String(file.reason ?? "")));

/** A file not to ask for again: the site has no rule for its files, listed none, or it is past the size limit. */
const FINAL_FILE_REASONS = new Set(["supplements_not_supported", "no_supplements", "too_large"]);

function readJson(file: string): Record<string, unknown> | undefined {
  try {
    const value = JSON.parse(readFileSync(file, "utf8")) as unknown;
    return value && typeof value === "object" ? value as Record<string, unknown> : undefined;
  } catch {
    return undefined;
  }
}

function readPapers(dir: string): LedgerPaper[] {
  const file = join(dir, "items.jsonl");
  if (!existsSync(file)) return [];
  const papers: LedgerPaper[] = [];
  for (const line of readFileSync(file, "utf8").split("\n")) {
    if (!line.trim()) continue;
    try {
      const item = JSON.parse(line) as Record<string, unknown>;
      papers.push({
        index: Number(item.index) || 0,
        doi: String(item.doi ?? ""),
        paperId: String(item.paperId ?? item.doi ?? ""),
        title: String(item.title ?? ""),
        status: String(item.status ?? ""),
        path: String(item.path ?? ""),
        ...(Array.isArray(item.supplements) ? { supplements: item.supplements as SupplementFile[] } : {}),
        ...(Array.isArray(item.stages) && item.stages.some((stage) => (stage as Record<string, unknown>)?.stage === "entitled_access"
          && (stage as Record<string, unknown>)?.status === "ok") ? { byVisit: true } : {}),
      });
    } catch {
      // A line cut short (a run ended mid-write): that paper is not counted as saved.
    }
  }
  return papers;
}

/** Download batches in the ledger root, oldest first (their folders sort by start time). */
function batchRuns(root: string): Array<{ name: string; run: Record<string, unknown> }> {
  if (!existsSync(root)) return [];
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
export function planResume(which: string, env: Record<string, string | undefined> = process.env): ResumePlan | string {
  const root = resolveRunLogRoot(env);
  if (!root) return "运行记录已关闭（PAPER_SEARCH_RUNLOG=0），无法接着下。";
  const runs = batchRuns(root);
  const picked = which === "latest" ? runs.at(-1) : runs.find(({ name }) => name === which);
  if (!picked) return which === "latest" ? "没有找到批量下载的运行记录。" : `没有找到运行记录 ${which}。`;
  const first = String(picked.run.resumeOf || picked.name);
  const chain = runs.filter(({ name, run }) => name === first || run.resumeOf === first);
  const original = chain.find(({ name }) => name === first)?.run ?? picked.run;
  const folder = String(original.savePath ?? "");
  if (!folder) return `运行记录 ${first} 没有记下载文件夹，无法接着下。`;

  // The latest record of each paper. A saved paper is gone on with only for its files: those
  // runs change what files it has, the saved PDF stands.
  const papers = new Map<string, LedgerPaper>();
  for (const { name } of chain) {
    for (const paper of readPapers(join(root, name))) {
      const key = (paper.doi || paper.paperId).toLowerCase();
      if (!key) continue;
      const before = papers.get(key);
      // A run the user stopped before it tried this paper's files leaves what was known (2026-11-16).
      const tried = paper.supplements !== undefined && !notTried(paper.supplements);
      papers.set(key, before?.status === "ok"
        ? { ...before, path: paper.path || before.path, ...(tried ? { supplements: paper.supplements } : {}) }
        : { ...paper, path: paper.path || before?.path || "", title: paper.title || before?.title || "" });
    }
  }
  const content = (["main", "supplements", "both"] as const).find((kind) => kind === original.content)
    ?? ([...papers.values()].some((paper) => paper.supplements !== undefined) ? "both" : "main");

  const retry: DownloadBatchItem[] = [];
  const files: DownloadBatchItem[] = [];
  let complete = 0;
  const item = (paper: LedgerPaper): DownloadBatchItem => ({
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
    if (filesMissing) files.push({ ...item(paper), ...(paper.path ? { mainPath: paper.path } : {}) });
    else complete += 1;
  }
  return { runId: first, folder, content, retry, files, complete };
}
