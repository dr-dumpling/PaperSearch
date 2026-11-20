import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { isAbsolute, join, resolve } from "node:path";
import { readItems, selectRuns, type FailureQuery } from "./index.js";
import { runBackendExport } from "./exportReport.js";

/**
 * Pages from sites not yet supported (user, 2026-11-16): the download keeps each with its
 * check results in the run's records (<DOI>_markdown-report.json beside
 * <DOI>_markdown-page.html), those another site's rules converted completely and saved too
 * (user, 2026-11-17: one report, saying which rules did). Listed by site here, and exported
 * by the school backend (markdown-report-export) into a ZIP to look over and attach to an
 * issue; nothing is uploaded.
 */
export interface MarkdownSitePage {
  runId: string;
  doi: string;
  title?: string;
  host: string;
  /** The report's path (absolute). */
  report: string;
  /** Converted completely (by another site's rules) and saved. */
  saved: boolean;
  /** Whose rules converted it, or came closest ("Atypon"). */
  rules?: string;
  /** What the closest rules lacked, in the window's words; none when saved. */
  lacks: string[];
}

export interface MarkdownSite {
  host: string;
  papers: number;
  saved: number;
  /** Whose rules its pages went by, most papers first. */
  rules: string[];
  lacks: Record<string, number>;
}

const LACKS: Array<[string, string]> = [["references", "参考文献不全"], ["figures", "图片不全"], ["tables", "表格没取到"], ["text", "正文不全"]];

const REASONS: Record<string, string> = { abstract_only: "只读到摘要", page_not_entitled: "网页显示没有权限" };

function lacksOf(report: Record<string, unknown>): string[] {
  if (report.status === "ok") return [];
  if (typeof report.code === "string" && REASONS[report.code]) return [REASONS[report.code]];
  const shortfall = (report.shortfall && typeof report.shortfall === "object" ? report.shortfall : {}) as Record<string, unknown>;
  const lacks = LACKS.filter(([key]) => shortfall[key]).map(([, label]) => label);
  return lacks.length ? lacks : [report.template ? "核对没通过" : "没有规则能读出正文"];
}

/** The pages kept in the runs the query names (the latest by default). */
export function markdownPages(root: string, query: FailureQuery = {}): MarkdownSitePage[] {
  const pages: MarkdownSitePage[] = [];
  for (const runId of selectRuns(root, query)) {
    const records = join(root, runId, "records");
    if (!existsSync(records)) continue;
    const titles = new Map(readItems(join(root, runId, "items.jsonl"))
      .map((item) => [String(item.doi ?? "").toLowerCase(), typeof item.title === "string" ? item.title : ""]));
    for (const name of readdirSync(records).filter((file) => file.endsWith("_markdown-report.json")).sort()) {
      const file = join(records, name);
      let report: Record<string, unknown>;
      try {
        if (statSync(file).size > 1024 * 1024) continue;
        report = JSON.parse(readFileSync(file, "utf8")) as Record<string, unknown>;
      } catch {
        continue;
      }
      if (report?.schemaVersion !== 1 || typeof report.doi !== "string" || typeof report.host !== "string") continue;
      if (query.doi && report.doi.toLowerCase() !== query.doi.toLowerCase()) continue;
      const title = titles.get(report.doi.toLowerCase());
      const rules = typeof report.rules === "string" && report.rules ? report.rules : undefined;
      pages.push({ runId, doi: report.doi, ...(title ? { title } : {}), host: report.host, report: file, saved: report.status === "ok",
        ...(rules ? { rules } : {}), lacks: lacksOf(report) });
    }
  }
  return pages;
}

/** By site, most papers first, with whose rules they went by and what the unsaved lacked. */
export function markdownSites(pages: MarkdownSitePage[]): MarkdownSite[] {
  const sites = new Map<string, MarkdownSite & { tally: Map<string, number> }>();
  for (const page of pages) {
    const site = sites.get(page.host) ?? { host: page.host, papers: 0, saved: 0, rules: [], lacks: {} as Record<string, number>,
      tally: new Map<string, number>() };
    site.papers += 1;
    if (page.saved) site.saved += 1;
    if (page.rules) site.tally.set(page.rules, (site.tally.get(page.rules) ?? 0) + 1);
    for (const lack of page.lacks) site.lacks[lack] = (site.lacks[lack] ?? 0) + 1;
    sites.set(page.host, site);
  }
  return [...sites.values()].sort((a, b) => b.papers - a.papers).map(({ tally, ...site }) =>
    ({ ...site, rules: [...tally].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([name]) => name) }));
}

export function renderMarkdownSitesText(sites: MarkdownSite[]): string {
  if (!sites.length) return "这些批次没有暂未正式支持 Markdown 的网站留下网页。";
  return ["暂未正式支持 Markdown 的网站：",
    ...sites.map((site) => `- ${site.host}：${site.papers} 篇` + (site.rules.length ? `，采用 ${site.rules.join(" / ")} 规则` : "")
      + `；完整已保存 ${site.saved} 篇` + (site.papers > site.saved
        ? `，没保存 ${site.papers - site.saved} 篇（${Object.entries(site.lacks).map(([lack, n]) => `${lack} ${n}`).join("、")}）` : "")),
    "导出报告：paper-search failures --markdown --export（ZIP 在这批的下载文件夹，附到 GitHub issue：转全的申请正式登记，没转全的请求补规则；不会自动上传）"].join("\n");
}

export interface MarkdownReportResult {
  ok: true;
  path: string;
  name: string;
  papers: number;
  sites: string[];
  bytes: number;
  /** GitHub's new issue page with the Markdown site template filled in (no DOI or title). */
  issueUrl: string;
}

/** The ZIP: at ``output`` (a new .zip) or as PaperSearch-Markdown报告-<date>.zip in ``folder``. */
export async function exportMarkdownReport(options: {
  pages: MarkdownSitePage[]; folder: string; output?: string; version: string; command: string;
}): Promise<MarkdownReportResult> {
  if (!options.pages.length) throw new Error("这些批次没有暂未正式支持 Markdown 的网站留下网页。");
  if (options.output !== undefined && !options.output.toLowerCase().endsWith(".zip")) throw new Error("导出路径须以 .zip 结尾。");
  const input = JSON.stringify({ schemaVersion: 1, version: options.version,
    reports: options.pages.slice(0, 100).map((page) => ({ report: page.report, doi: page.doi, ...(page.title ? { title: page.title } : {}) })) });
  const args = ["markdown-report-export", ...(options.output ? ["--output", resolve(options.output)] : ["--folder", resolve(options.folder)])];
  const data = await runBackendExport(options.command, args, input, "Markdown 报告导出",
    "学校订阅下载未返回 Markdown 报告，请运行 paper-search school update 更新。");
  if (data.ok !== true) {
    const code = typeof data.error === "string" ? data.error.split(";")[0] : "";
    const known = new Set(["no_reports", "invalid_export_request", "export_request_too_large", "export_path_must_end_in_zip",
      "export_target_exists", "package_size_limit", "export_permission_denied", "export_io_or_input_error"]);
    throw new Error(`Markdown 报告导出未完成：${known.has(code) ? code : "export_failed"}`);
  }
  if (typeof data.path !== "string" || !isAbsolute(data.path) || typeof data.issueUrl !== "string"
      || !data.issueUrl.startsWith("https://github.com/dr-dumpling/PaperSearch/issues/new?")) {
    throw new Error("学校订阅下载返回了不兼容的导出结果。");
  }
  return data as unknown as MarkdownReportResult;
}
