import { existsSync, readdirSync, readFileSync } from "node:fs";
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
}

export interface FailureItem {
  doi: string;
  runId: string;
  evidence?: string;
  stoppedAt?: string;
  diagnostic?: string;
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

export function summarizeFailures(root: string, query: FailureQuery = {}): FailureSummary {
  const runs = selectRuns(root, query);
  const classes = Object.fromEntries(FAILURE_CLASSES.map((c) => [c, 0])) as Record<FailureClass, number>;
  const groups = new Map<string, FailureGroup>();
  let failed = 0;
  let notAttempted = 0;
  for (const runId of runs) {
    for (const item of readItems(join(root, runId, "items.jsonl"))) {
      if (item.status === "ok") continue;
      const stages = Array.isArray(item.stages) ? (item.stages as Array<Record<string, unknown>>) : [];
      const stage = [...stages].reverse().find((s) => s.stage === "entitled_access");
      if (!stage || stage.status !== "error") {
        notAttempted += 1;
        continue;
      }
      failed += 1;
      const code = typeof stage.code === "string" && stage.code ? stage.code : "download_failed";
      const backend = stage.backend as Record<string, unknown> | undefined;
      const description: FailureDescription =
        typeof stage.failureClass === "string"
          ? {
              failureClass: stage.failureClass as FailureClass,
              ...(typeof stage.evidence === "string" ? { evidence: stage.evidence } : {}),
              ...(typeof stage.stoppedAt === "string" ? { stoppedAt: stage.stoppedAt } : {}),
            }
          : describeFailure(code, backend, stage.trace as Record<string, unknown> | undefined);
      const detail = (backend?.diagnostic ?? backend?.record) as Record<string, unknown> | undefined;
      const trace = (stage.trace ?? {}) as Record<string, unknown>;
      const publisher = typeof trace.publisher === "string" && trace.publisher ? trace.publisher : "-";
      const site = hostOf(detail?.final_url) || hostOf(detail?.article_url) || "-";
      classes[description.failureClass] += 1;
      const key = [description.failureClass, publisher, site, code].join("\u0000");
      const group = groups.get(key) ?? {
        failureClass: description.failureClass, publisher, site, code, count: 0, items: [],
      };
      group.count += 1;
      if (!group.evidence && description.evidence) group.evidence = description.evidence;
      const diagnostic = (backend?.diagnostic as Record<string, unknown> | undefined)?.file;
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
  const order = (c: FailureClass) => FAILURE_CLASSES.indexOf(c);
  return {
    root,
    runs,
    failed,
    notAttempted,
    classes,
    groups: [...groups.values()].sort(
      (a, b) => order(a.failureClass) - order(b.failureClass) || b.count - a.count,
    ),
  };
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
