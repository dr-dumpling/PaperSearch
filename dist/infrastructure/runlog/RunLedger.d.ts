import type { DownloadStageRecord, DownloadWithFallbackResult } from "../../capabilities/pdf-discovery/types.js";
/**
 * Local record of every download run, so a failure can be traced afterwards:
 * which stages ran, how long each took, what the backend's browser reached and
 * where it stopped. One directory per run:
 *
 *   run.json      what was run, when, and the final counts
 *   items.jsonl   one line per finished item with all its stages and the
 *                 backend's collapsed page events
 *   timeline.log  human-readable, appended as each stage finishes
 *
 * Root: PAPER_SEARCH_RUNLOG_DIR, else $XDG_DATA_HOME/paper-search-cli/runs
 * (default ~/.local/share/paper-search-cli/runs). PAPER_SEARCH_RUNLOG=0
 * turns it off. Write failures are reported once on stderr and never change a
 * download outcome.
 */
export declare function resolveRunLogRoot(env?: Record<string, string | undefined>, home?: string): string | null;
/** Run folders (records, diagnostics) are kept this long, then removed as a new run starts (user, 2026-11-11). */
export declare const RUN_KEEP_DAYS = 30;
/** Remove the run folders started more than RUN_KEEP_DAYS ago; only run folders, nothing else in ``root``. */
export declare function pruneOldRuns(root: string, now?: Date): string[];
export interface RunLedgerStart {
    kind: "download" | "download_batch";
    total: number;
    mode?: string;
    batchId?: string;
    savePath?: string;
}
export interface RunItem {
    /** 1-based position in the run. */
    index: number;
    paperId: string;
    doi?: string;
    title?: string;
}
interface CollapsedEvent {
    state: string;
    at?: string;
    detail?: string;
    /** Consecutive repeats of the same state (e.g. challenge_wait). */
    count?: number;
    lastAt?: string;
}
export declare class RunLedger {
    readonly dir: string;
    private readonly run;
    private readonly stages;
    private readonly started;
    private succeeded;
    private failed;
    private warned;
    private constructor();
    static open(start: RunLedgerStart, env?: Record<string, string | undefined>, now?: Date): RunLedger | null;
    phase(text: string): void;
    stage(item: RunItem, record: DownloadStageRecord): void;
    item(item: RunItem, result: DownloadWithFallbackResult): void;
    /** Where the run's papers that went fine keep their backend records. */
    get records(): string;
    /**
     * Where the run's other papers keep their diagnostics: the run's folder, not the
     * download folder, which holds only papers (user, 2026-11-11).
     */
    get diagnostics(): string;
    close(extra?: Record<string, unknown>): void;
    private writeRun;
    private line;
    private append;
    private warn;
}
export declare function collapseEvents(events: unknown[]): CollapsedEvent[];
export {};
//# sourceMappingURL=RunLedger.d.ts.map