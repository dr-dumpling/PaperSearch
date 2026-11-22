/**
 * Every failed institutional download is in one of five classes (ADR 0012; the list with every
 * reason and what follows it: docs/contracts/failure-reasons.zh.md): evidenced no access (the
 * school cannot have this paper: another saved school is tried at a batch's end); the user's to
 * do (their steps, settings or the school account); the site's, the school's or the network's
 * error (try again later); a site PaperSearch has no rules for yet, or whose rules missed this
 * journal's page (PaperSearch's to fix); or unexplained (tried once more at a batch's end,
 * investigated). "No access" is never concluded from a missing PDF, a timeout or an error.
 * Five since 2026-11-22 (user: eight classes and 58 phrasings were too many to follow; the
 * school's errors go with the site's and the network's; names of four characters at most, 外部原因
 * and 暂不支持, phrasings of ten at most): school_side, publisher_or_network and
 * article_or_site became external, adaptation went into unsupported.
 */
export type FailureClass = "no_access" | "user_side" | "external" | "unsupported" | "unexplained";
export declare const FAILURE_CLASSES: readonly FailureClass[];
/** Names, the same in counts, the progress window's tags and the failures list. */
export declare const FAILURE_CLASS_NAMES: Readonly<Record<FailureClass, string>>;
/** The name with what it means, for the failures list's headings. */
export declare const FAILURE_CLASS_LABELS: Readonly<Record<FailureClass, string>>;
/** The classes before 2026-11-22, as old run records keep them. */
export declare const OLD_FAILURE_CLASSES: Readonly<Record<string, FailureClass>>;
export declare function classifyFailureCode(code: string | undefined): FailureClass;
export interface FailureDescription {
    failureClass: FailureClass;
    /** no_access: the page's words or the decisive step. */
    evidence?: string;
    /** unexplained: the last step the browser reached. */
    stoppedAt?: string;
}
/**
 * The class of a failed entitled-access stage, from its code and the
 * backend's diagnostic (or record) as the run ledger keeps it.
 */
export declare function describeFailure(code: string | undefined, backend?: Record<string, unknown>, trace?: Record<string, unknown>): FailureDescription;
export declare function hostOf(url: unknown): string;
//# sourceMappingURL=failureClass.d.ts.map