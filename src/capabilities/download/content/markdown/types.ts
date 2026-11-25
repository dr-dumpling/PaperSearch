/**
 * What the core and the Markdown converter (PaperSearch Pro, pro/) pass each other: the
 * request, its outcome, and the package's folder names. The core arranges the paper's
 * folders and records; the converter writes the package into the folder it is given.
 */
import type { CapturedFulltextPage } from "../../types.js";

export const FULLTEXT_MARKDOWN = "article.md";
export const FULLTEXT_MANIFEST = "fulltext.json";
/** The original and fulltext.json, in a folder of their own inside the package's. */
export const FULLTEXT_SOURCE_FOLDER = "source";
/** The package's folder inside the paper's, beside its PDF and supplements/ (user, 2026-11-15). */
export const FULLTEXT_FOLDER = "markdown";
export const FIGURES_FOLDER = "figures";

/** API keys for Elsevier's Article Retrieval API (process.env when a request gives none). */
export interface ElsevierEnv {
  ELSEVIER_API_KEY?: string;
  ELSEVIER_INSTTOKEN?: string;
}

/** What a page's conversion may lack: figures and references in numbers, the text in percent. */
export interface Shortfall {
  figures?: number;
  references?: number;
  /** Percent of the article's paragraph text not found in the Markdown. */
  text?: number;
  tables?: boolean;
}

export type FulltextVia = "pmc" | "europepmc" | "elsevier" | "publisher_page";

export interface FulltextFigure {
  label: string;
  kind: "figure" | "table";
  /** Saved file, relative to the package folder. */
  file?: string;
  url: string;
  status: "saved" | "failed" | "skipped";
  bytes?: number;
  reason?: string;
}

export interface FulltextOutcome {
  /**
   * incomplete: a full text missing figures or a table, not kept (code figures_missing: a
   * record without its figures' files, or an earlier whole package kept in its place;
   * tables_missing).
   */
  status: "ok" | "incomplete" | "abstract_only" | "unavailable" | "error";
  source?: FulltextVia;
  /** The package's files, when written. */
  markdown?: string;
  raw?: string;
  manifest?: string;
  /** ok: all saved; incomplete: how many the source gave of those its text shows. */
  figures?: { saved: number; total: number };
  code?: string;
  message: string;
  warnings?: string[];
  /** From a site not yet supported: its host, the rules tried, and what they lacked. */
  unverified?: UnverifiedSite;
  /** Saved from a registered site's page whose checks found something short (user, 2026-11-17). */
  possiblyMissing?: Shortfall;
  /**
   * Saved without these figures (their labels), which did not download: each is marked at its
   * place in article.md, and a batch tries them once more at its end (user, 2026-11-23).
   */
  missingFigures?: string[];
  /** A registered site's page its listed rules did not convert, converted by other rules (user, 2026-11-18). */
  rulesFallback?: RulesFallback;
}

/**
 * A registered site whose listed rules saw only an abstract or left figures or tables out (its
 * pages changed, or the paper's kind is one the rules do not know): the other rules were tried
 * as for a site not yet supported, and these converted the page completely (user, 2026-11-18).
 */
export interface RulesFallback {
  host: string;
  /** The listed rules, and what they made of the page. */
  listed: string;
  listedResult: "unrecognized" | "abstract" | "incomplete";
  listedShortfall?: Shortfall;
  /** The rules that converted it, and why they were tried: the page's publisher's, its platform's or another's. */
  used: string;
  matchedBy: "publisher" | "platform" | "other";
  basis?: string;
  /** The page and these facts, kept in the run's records ("<DOI>_markdown-fallback.json"). */
  report?: string;
}

/** A page from a site not yet supported (sites/unverified.ts). */
export interface UnverifiedSite {
  host: string;
  template?: string;
  shortfall?: Shortfall;
  /** The saved page and its check results, kept in the run's records for a report. */
  report?: string;
  /** Not tried: the site's first three papers in this batch did not convert completely. */
  skipped?: boolean;
  /** Why these rules: the page's publisher's, its platform's or another's ("Elsevier", "Atypon"). */
  matchedBy?: "publisher" | "platform" | "other";
  basis?: string;
  /**
   * Converted completely by its own publisher's rules: counted as a supported site, with no
   * site file and no 未登记 mark (user, 2026-11-17); only the batch's tally keeps it.
   */
  supported?: boolean;
  /** What each rule made of the page and the page itself (kept in the report, not passed on to the window). */
  checks?: unknown;
  /** The closest rules' Markdown (kept in the report as it is, not passed on). */
  attempt?: string;
}

export interface FulltextRequest {
  doi: string;
  /** The paper's folder: the package's files go into it. */
  dir: string;
  timeoutMs?: number;
  /** "PaperSearch 0.6.4", for fulltext.json. */
  tool?: string;
  /** The article's full-text page the browser saved during the download, when it did. */
  page?: CapturedFulltextPage;
  /**
   * A visit for the article's page, when a PubMed Central record lacks the figures its text
   * shows (called at most once); "later": the caller visits it later (a batch's open lane).
   */
  visit?: () => Promise<CapturedFulltextPage | "later" | undefined>;
  /** API keys (ELSEVIER_API_KEY, ELSEVIER_INSTTOKEN); process.env when not given. */
  env?: ElsevierEnv;
  /** The publisher's page alone (a batch's entitled_only mode): PubMed Central and the publisher API are not asked. */
  pageOnly?: boolean;
}
