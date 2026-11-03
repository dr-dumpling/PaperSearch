/**
 * Every failed institutional download is in one of four classes (ADR 0012):
 * evidenced no access, the user's or another party's doing, a site without
 * rules yet, or unexplained. "No access" is never concluded from a missing
 * PDF, a timeout or an error; unexplained failures are investigated.
 */
export type FailureClass = "no_access" | "user_or_external" | "unsupported" | "unexplained";
export declare const FAILURE_CLASSES: readonly FailureClass[];
/** Short names, for one-line counts. */
export declare const FAILURE_CLASS_NAMES: Readonly<Record<FailureClass, string>>;
export declare const FAILURE_CLASS_LABELS: Readonly<Record<FailureClass, string>>;
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