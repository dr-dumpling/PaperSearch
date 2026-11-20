/**
 * PaperSearch Pro: the Markdown converter, apart from the open core (user, 2026-11-18). The core arranges each paper's folders, visits and
 * records (step.ts) and asks Pro for the conversion through ``MarkdownPro``, handing it the
 * little it needs of the core (``ProHost``). Pro is loaded from PaperSearch's data folder
 * (or ``PAPER_SEARCH_PRO_PATH``); without it, or while it says it cannot be used now
 * (``access``), a paper's Markdown says so and the PDF and supplementary files go on.
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { pathToFileURL } from "node:url";
import { USER_AGENT } from "../../../../config/constants.js";
import { proFeatures } from "../../../../config/edition.js";
import { markdownProEntry, paperSearchDataHome } from "../../../../infrastructure/school/index.js";
import type { CapturedFulltextPage } from "../../types.js";
import { pmcidForDoi } from "../pdf/open/pmcCloud.js";
import type { FulltextOutcome, FulltextRequest } from "./types.js";

/** Raised when ``ProHost`` or ``MarkdownPro`` changes; Pro says which one it was built for. */
export const MARKDOWN_PRO_API = 1;

/** What the core hands Pro: Pro calls no other code of the core's. */
export interface ProHost {
  apiVersion: number;
  userAgent: string;
  /** PaperSearch's data folder; Pro keeps its own records in ``pro/`` there. */
  dataHome: string;
  /** PubMed Central's id for a DOI ("" when it has none). */
  pmcidForDoi(doi: string, timeoutMs: number): Promise<string>;
}

/** Whether the Markdown can be made now; when not, the code and message the paper's Markdown gets. */
export interface ProAccess {
  ok: boolean;
  code?: string;
  message?: string;
}

export interface MarkdownPro {
  apiVersion: number;
  version: string;
  access(): ProAccess;
  /** The paper's package: PubMed Central, Elsevier's API or the page given, in that order. */
  fetchFulltext(request: FulltextRequest): Promise<FulltextOutcome>;
  /** The package from an article page the browser saved. */
  fulltextFromPage(page: CapturedFulltextPage, doi: string, request: Omit<FulltextRequest, "doi">): Promise<FulltextOutcome>;
  /** Pro has rules for the site at this address, or the one this DOI leads to. */
  hasRulesForUrl(url: string): boolean;
  hasRulesForDoi(doi: string): boolean;
  /** The rules' name, for lists ("Elsevier 期刊网站"). */
  rulesName(template: string | undefined): string | undefined;
  /** The site of a DOI this batch gave up (its first papers did not convert), and its outcome. */
  givenUpForDoi(doi: string): string | undefined;
  givenUpOutcome(host: string): FulltextOutcome;
  /** A batch begins: the sites given up start afresh. */
  batchStarted(): void;
  /** How many papers of a site without rules a batch tries first. */
  triedFirstCount: number;
  landingHosts(dois: string[]): Promise<Map<string, string>>;
  triedFirst<T extends { doi?: string }>(items: T[], hosts: Map<string, string>):
    { items: T[]; sites: Array<{ host: string; papers: number }> };
  /** The school's sign-in filled in for the user: Pro's Python part, for the backend. */
  schoolLogin?: { apiVersion: number; files(): Record<string, string> };
}

/** No Pro on this computer. */
export const MARKDOWN_PRO_REQUIRED = "markdown_pro_required";

let loading: Promise<MarkdownPro | undefined> | undefined;
let current: MarkdownPro | undefined;

/** Where Pro is installed (the same path the backend and the settings window are given). */
export function proEntry(env: Record<string, string | undefined> = process.env): string {
  return markdownProEntry(env);
}

export function proHost(env: Record<string, string | undefined> = process.env): ProHost {
  return { apiVersion: MARKDOWN_PRO_API, userAgent: USER_AGENT, dataHome: paperSearchDataHome(env), pmcidForDoi };
}

/**
 * Pro, loaded once; undefined when it is not installed or was built for another core, and never
 * loaded without PaperSearch Pro's features (config/edition.ts).
 */
export function loadMarkdownPro(): Promise<MarkdownPro | undefined> {
  if (!proFeatures()) return Promise.resolve(undefined);
  loading ??= (async () => {
    const entry = proEntry();
    if (!existsSync(entry)) return undefined;
    try {
      const module = await import(pathToFileURL(entry).href) as
        { createMarkdownPro?: (host: ProHost) => MarkdownPro | Promise<MarkdownPro> };
      const pro = await module.createMarkdownPro?.(proHost());
      if (!pro || pro.apiVersion !== MARKDOWN_PRO_API) {
        process.stderr.write(`[Markdown] 本机的 PaperSearch Pro 与当前版本不配套（接口 ${pro?.apiVersion ?? "?"}，需要 ${MARKDOWN_PRO_API}），请更新 Pro。\n`);
        return undefined;
      }
      current = pro;
      return pro;
    } catch (error) {
      process.stderr.write(`[Markdown] PaperSearch Pro 没能加载：${error instanceof Error ? error.message : String(error)}\n`);
      return undefined;
    }
  })();
  return loading;
}

/** Pro as loaded so far (loadMarkdownPro first). */
export function markdownPro(): MarkdownPro | undefined {
  return current;
}

/** This Pro, or none: for tests, and for a program that embeds Pro itself. */
export function useMarkdownPro(pro: MarkdownPro | undefined): void {
  current = pro;
  loading = Promise.resolve(pro);
}

/** Why no Markdown can be made now, or undefined when it can (loadMarkdownPro first). */
export function markdownBlocked(pro: MarkdownPro | undefined = current): { code: string; message: string } | undefined {
  if (!pro) {
    return { code: MARKDOWN_PRO_REQUIRED,
      message: "Markdown full texts come with PaperSearch Pro, which is not installed on this computer; the PDF and supplementary files are not affected. Install it with `paper-search pro install`, or 安装 on the settings window's Markdown page (`paper-search settings markdown`); then 接着下 makes the Markdown left out." };
  }
  const access = pro.access();
  return access.ok ? undefined
    : { code: access.code || "markdown_pro_unavailable", message: access.message || "PaperSearch Pro cannot be used now." };
}

/** Where the backend finds Pro's school sign-in (school/paper_search_school/school_login.py). */
export const SCHOOL_LOGIN_ENV = "PAPER_SEARCH_PRO_SCHOOL_LOGIN";
/** Maintainers testing a school Pro lists as still being tested. */
export const SCHOOL_LOGIN_TRIAL_ENV = "PAPER_SEARCH_SCHOOL_LOGIN_TRIAL";
export const SCHOOL_LOGIN_API = 1;

/**
 * Pro's school sign-in, for the backend this command starts: its package (the general rules, its
 * schools by federation) written into Pro's folder as ``school/`` when it changed, and its entry
 * named in ``env``, once Pro is installed, its access given and its interface this one. Otherwise
 * ``env`` names none and the user signs in as before. The entry's path, or undefined.
 */
export async function prepareProSchoolLogin(env: Record<string, string | undefined> = process.env): Promise<string | undefined> {
  delete env[SCHOOL_LOGIN_ENV];
  const pro = await loadMarkdownPro();
  if (!pro || markdownBlocked(pro) || pro.schoolLogin?.apiVersion !== SCHOOL_LOGIN_API) return undefined;
  const folder = join(dirname(proEntry(env)), "school");
  const files = pro.schoolLogin.files();
  const there = existsSync(folder) ? readdirSync(folder, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile()).map((entry) => relative(folder, join(entry.parentPath, entry.name)).split("\\").join("/"))
    .filter((path) => !path.includes("__pycache__")) : [];
  const changed = there.length !== Object.keys(files).length || Object.entries(files).some(([path, text]) =>
    !existsSync(join(folder, path)) || readFileSync(join(folder, path), "utf8") !== text);
  if (changed) {
    // Written afresh: a school's file Pro no longer has goes with the old copy.
    rmSync(folder, { recursive: true, force: true });
    for (const [path, text] of Object.entries(files)) {
      mkdirSync(dirname(join(folder, path)), { recursive: true, mode: 0o700 });
      writeFileSync(join(folder, path), text, { mode: 0o600 });
    }
  }
  const entry = join(folder, "school_login", "__init__.py");
  env[SCHOOL_LOGIN_ENV] = entry;
  return entry;
}
