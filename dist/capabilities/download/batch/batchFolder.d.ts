import { type RunLedger } from "../../../infrastructure/runlog/RunLedger.js";
export declare const RUN_FOLDER = "_run";
export declare const INDEX_FILE = "article_index.csv";
/** A batch folder's name as given ("Osteoarthritis Cartilage_2024-2026"), safe on every system; undefined when none is left. */
export declare function batchFolderName(name: string | undefined): string | undefined;
export interface BatchFolderRecord {
    /** One progress line, into _run/batch.log. */
    log: (line: string) => void;
    /** The run's ledger, once open: its files are kept in _run/<run id> as they are written. */
    attach: (ledger: RunLedger | null) => void;
    /** The run's records and the folder's list, written again. */
    refresh: () => void;
}
/**
 * The batch's records in ``folder`` from now on: what it was asked (``args``), its lines, and
 * its run's files once the run ledger is attached. Undefined when the folder cannot be written.
 */
export declare function openBatchFolder(folder: string, args: Record<string, unknown>): BatchFolderRecord | undefined;
/** _run/article_index.csv of ``folder``: every paper of its runs, as of the latest, its paths from ``folder``. */
export declare function writeIndex(folder: string): void;
//# sourceMappingURL=batchFolder.d.ts.map