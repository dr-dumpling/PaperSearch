/**
 * `paper-search uninstall` (user, 2026-11-11): everything PaperSearch keeps on the
 * computer, removed in one go once the user agrees. Downloaded papers, Chrome and
 * Node.js stay; the npm package itself is removed last by the user with
 * `npm uninstall -g papersearch` (a running program cannot reliably remove itself
 * on Windows).
 */
export declare const NPM_UNINSTALL = "npm uninstall -g papersearch";
export interface UninstallItem {
    /** What it is, in a few words. */
    label: string;
    path: string;
    /** A link goes alone, never what it points to; an entry is one line of another program's file. */
    kind: "folder" | "file" | "link" | "entry";
    bytes: number;
}
export interface UninstallPlan {
    items: UninstallItem[];
    kept: string[];
}
export interface UninstallResult {
    removed: string[];
    failed: Array<{
        path: string;
        error: string;
    }>;
}
/** What `paper-search uninstall` removes and keeps, read from the disk; nothing is changed. */
export declare function uninstallPlan(env?: NodeJS.ProcessEnv, home?: string, options?: {
    downloads?: string;
}): UninstallPlan;
/** Remove what the plan lists; what could not be removed is reported, the rest still goes. */
export declare function runUninstall(plan: UninstallPlan): UninstallResult;
export declare function renderUninstallPlan(plan: UninstallPlan): string[];
//# sourceMappingURL=index.d.ts.map