import type { CapturedFulltextPage } from "../../types.js";
import type { FulltextOutcome, FulltextRequest } from "./types.js";
/** Raised when ``ProHost`` or ``MarkdownPro`` changes; Pro says which one it was built for. */
export declare const MARKDOWN_PRO_API = 1;
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
    /**
     * A batch's end: the figures a saved package (its article.md) was saved without, downloaded
     * once more; the package as it is then. An older Pro has none (it kept no Markdown missing a
     * figure).
     */
    retryMissingFigures?(markdownFile: string): Promise<FulltextOutcome>;
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
    triedFirst<T extends {
        doi?: string;
    }>(items: T[], hosts: Map<string, string>): {
        items: T[];
        sites: Array<{
            host: string;
            papers: number;
        }>;
    };
    /** The school's sign-in filled in for the user: Pro's Python part, for the backend. */
    schoolLogin?: {
        apiVersion: number;
        files(): Record<string, string>;
    };
}
/** No Pro on this computer. */
export declare const MARKDOWN_PRO_REQUIRED = "markdown_pro_required";
/** Where Pro is installed (the same path the backend and the settings window are given). */
export declare function proEntry(env?: Record<string, string | undefined>): string;
export declare function proHost(env?: Record<string, string | undefined>): ProHost;
/**
 * Pro, loaded once; undefined when it is not installed or was built for another core, and never
 * loaded without PaperSearch Pro's features (config/edition.ts).
 */
export declare function loadMarkdownPro(): Promise<MarkdownPro | undefined>;
/** Pro as loaded so far (loadMarkdownPro first). */
export declare function markdownPro(): MarkdownPro | undefined;
/** This Pro, or none: for tests, and for a program that embeds Pro itself. */
export declare function useMarkdownPro(pro: MarkdownPro | undefined): void;
/** Why no Markdown can be made now, or undefined when it can (loadMarkdownPro first). */
export declare function markdownBlocked(pro?: MarkdownPro | undefined): {
    code: string;
    message: string;
} | undefined;
/** Where the backend finds Pro's school sign-in (school/paper_search_school/school_login.py). */
export declare const SCHOOL_LOGIN_ENV = "PAPER_SEARCH_PRO_SCHOOL_LOGIN";
/** Maintainers testing a school Pro lists as still being tested. */
export declare const SCHOOL_LOGIN_TRIAL_ENV = "PAPER_SEARCH_SCHOOL_LOGIN_TRIAL";
export declare const SCHOOL_LOGIN_API = 1;
/**
 * Pro's school sign-in, for the backend this command starts: its package (the general rules, its
 * schools by federation) written into Pro's folder as ``school/`` when it changed, and its entry
 * named in ``env``, once Pro is installed, its access given and its interface this one. Otherwise
 * ``env`` names none and the user signs in as before. The entry's path, or undefined.
 */
export declare function prepareProSchoolLogin(env?: Record<string, string | undefined>): Promise<string | undefined>;
//# sourceMappingURL=pro.d.ts.map