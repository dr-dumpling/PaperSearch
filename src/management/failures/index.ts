import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import {
  describeFailure,
  FAILURE_CLASSES,
  FAILURE_CLASS_LABELS,
  hostOf,
  type FailureClass,
  type FailureDescription,
} from "../../infrastructure/runlog/failureClass.js";

/**
 * Failure summary from the run ledgers (ADR 0012): every failed institutional
 * download by class, publisher, site and code, with the evidence for "no
 * access" and, for each unexplained failure, where it stopped and its
 * diagnostic file. Run after a batch; the unexplained ones are what to look into.
 */
export interface FailureQuery {
  /** A run id, or "latest" (the default when nothing else is given). */
  run?: string;
  /** Runs started on or after this day (YYYY-MM-DD). */
  since?: string;
  /** The last N runs. */
  runs?: number;
  doi?: string;
}

export interface FailureItem {
  doi: string;
  runId: string;
  evidence?: string;
  stoppedAt?: string;
  diagnostic?: string;
  /** Only present for a supplementary-file failure. */
  part?: "supplements";
}

export interface FailureGroup {
  failureClass: FailureClass;
  publisher: string;
  site: string;
  code: string;
  count: number;
  /** no_access: the evidence of the first item. */
  evidence?: string;
  items: FailureItem[];
}

export interface FailureSummary {
  root: string;
  runs: string[];
  /** Failed items whose institutional download ran and failed. */
  failed: number;
  /** Failed items that never reached the institutional download. */
  notAttempted: number;
  classes: Record<FailureClass, number>;
  groups: FailureGroup[];
}

export interface ExportFailure extends FailureItem {
  publisher: string;
  site: string;
  code: string;
  failureClass: FailureClass;
  record?: string;
  detail: Record<string, unknown>;
  outcome: Record<string, unknown>;
}

/** One entry per failed paper, including a saved main text with incomplete attachments. */
export function selectFailures(root: string, query: FailureQuery = {}, options: { forExport?: boolean } = {}): {
  runs: string[]; papers: ExportFailure[]; notAttempted: number;
} {
  const runs = selectRuns(root, query);
  const papers: ExportFailure[] = [];
  let notAttempted = 0;
  let exportBytes = 0;
  for (const runId of runs) {
    for (const item of readItems(join(root, runId, "items.jsonl"))) {
      const doi = String(item.doi ?? item.paperId ?? "");
      if (query.doi && doi.toLowerCase() !== query.doi.toLowerCase()) continue;
      const supplements = Array.isArray(item.supplements) ? item.supplements as Record<string, unknown>[] : [];
      const incomplete = supplements.find((f) => f.status === "failed" ||
        (f.status === "skipped" && !["no_supplements", "not_requested"].includes(String(f.reason))));
      if (item.status === "ok" && !incomplete) continue;
      const stages = Array.isArray(item.stages) ? item.stages as Record<string, unknown>[] : [];
      const main = [...stages].reverse().find((s) => s.stage === "entitled_access");
      const attachment = [...stages].reverse().find((s) => s.stage === "supplements");
      const part = incomplete && (item.status === "ok" || !main || main.status !== "error") ? "supplements" : undefined;
      const stage = part ? attachment ?? main : main;
      if (!stage || (!part && stage.status !== "error")) {
        notAttempted += 1;
        continue;
      }
      const code = String((part ? incomplete?.reason : stage.code) || "download_failed");
      const backend = stage.backend as Record<string, unknown> | undefined;
      const current = describeFailure(code, backend, stage.trace as Record<string, unknown> | undefined);
      const description: FailureDescription = !part && FAILURE_CLASSES.includes(stage.failureClass as FailureClass)
        && (current.failureClass === "unexplained" || current.failureClass === stage.failureClass)
        ? { failureClass: stage.failureClass as FailureClass,
            ...(typeof stage.evidence === "string" ? { evidence: stage.evidence } : {}),
            ...(typeof stage.stoppedAt === "string" ? { stoppedAt: stage.stoppedAt } : {}) }
        : current;
      const detail = (backend?.diagnostic ?? backend?.record ?? {}) as Record<string, unknown>;
      const trace = (stage.trace ?? {}) as Record<string, unknown>;
      const diagnostic = (backend?.diagnostic as Record<string, unknown> | undefined)?.file ?? trace.diagnostic;
      const record = (backend?.record as Record<string, unknown> | undefined)?.file ?? trace.record;
      const paper: ExportFailure = { doi, runId, ...description,
        publisher: typeof trace.publisher === "string" && trace.publisher ? trace.publisher : "-",
        site: hostOf(detail.final_url) || hostOf(detail.article_url) || "-", code,
        ...(part ? { part } : {}),
        ...(typeof diagnostic === "string" && diagnostic ? { diagnostic } : {}),
        ...(typeof record === "string" && record ? { record } : {}),
        detail: options.forExport ? detail : {},
        outcome: options.forExport ? { status: item.status, supplements,
          stages: stages.map(({ stage, status, code, message, startedAt, durationMs }) =>
            ({ stage, status, code, message, startedAt, durationMs })) } : {},
      };
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

export function summarizeFailures(root: string, query: FailureQuery = {}): FailureSummary {
  const { runs, papers, notAttempted } = selectFailures(root, query);
  const classes = Object.fromEntries(FAILURE_CLASSES.map((c) => [c, 0])) as Record<FailureClass, number>;
  const groups = new Map<string, FailureGroup>();
  for (const paper of papers) {
    const { failureClass, publisher, site, code } = paper;
    classes[failureClass] += 1;
    const key = [failureClass, publisher, site, code].join("\u0000");
    const group = groups.get(key) ?? { failureClass, publisher, site, code, count: 0, items: [] };
    group.count += 1;
    if (!group.evidence && paper.evidence) group.evidence = paper.evidence;
    group.items.push({ doi: paper.doi, runId: paper.runId,
      ...(paper.evidence ? { evidence: paper.evidence } : {}),
      ...(paper.stoppedAt ? { stoppedAt: paper.stoppedAt } : {}),
      ...(paper.diagnostic ? { diagnostic: paper.diagnostic } : {}),
      ...(paper.part ? { part: paper.part } : {}),
    });
    groups.set(key, group);
  }
  const order = (c: FailureClass) => FAILURE_CLASSES.indexOf(c);
  return { root, runs, failed: papers.length, notAttempted, classes,
    groups: [...groups.values()].sort((a, b) => order(a.failureClass) - order(b.failureClass) || b.count - a.count) };
}

/** Run directories are named <yyyymmdd>-<hhmmss>-<id>, so names sort by start time. */
function selectRuns(root: string, query: FailureQuery): string[] {
  if (!existsSync(root)) return [];
  const all = readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && /^\d{8}-\d{6}-/.test(entry.name))
    .map((entry) => entry.name)
    .sort();
  if (query.run && query.run !== "latest") return all.filter((name) => name === query.run);
  if (query.since) {
    const day = query.since.replace(/-/g, "");
    return all.filter((name) => name.slice(0, 8) >= day);
  }
  if (query.runs && query.runs > 0) return all.slice(-query.runs);
  return all.slice(-1);
}

function readItems(file: string): Array<Record<string, unknown>> {
  if (!existsSync(file)) return [];
  if (statSync(file).size > 64 * 1024 * 1024) throw new Error("运行记录超过 64 MiB，无法安全汇总此批次。");
  const items: Array<Record<string, unknown>> = [];
  for (const line of readFileSync(file, "utf8").split("\n")) {
    if (!line.trim()) continue;
    try {
      const item: unknown = JSON.parse(line);
      if (item && typeof item === "object" && !Array.isArray(item)) items.push(item as Record<string, unknown>);
    } catch {
      // A line cut off by an interrupted run.
    }
  }
  return items;
}

export function renderFailuresText(summary: FailureSummary, options: { all?: boolean } = {}): string {
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
    if (!groups.length) continue;
    lines.push("", `${FAILURE_CLASS_LABELS[failureClass]}  ${summary.classes[failureClass]}`);
    for (const group of groups) {
      lines.push(`  ${group.publisher} · ${group.site} · ${group.code}  ${group.count}`);
      if (failureClass === "no_access" && group.evidence) lines.push(`    依据：${group.evidence}`);
      if (failureClass !== "unexplained") continue;
      for (const item of group.items.slice(0, shown)) {
        lines.push(
          `    ${item.doi}` +
            (item.stoppedAt ? `  停在 ${item.stoppedAt}` : "") +
            (item.diagnostic ? `\n      ${item.diagnostic}` : ""),
        );
      }
      if (group.items.length > shown) lines.push(`    …另 ${group.items.length - shown} 篇（--all 全部列出）`);
    }
  }
  return lines.join("\n");
}

function day(runId: string): string {
  return `${runId.slice(0, 4)}-${runId.slice(4, 6)}-${runId.slice(6, 8)}`;
}
