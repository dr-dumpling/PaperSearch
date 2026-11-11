import type { CarsiBackend, CarsiBatchPaper } from "./carsi/index.js";
/** How soon a report that did not get through goes again, and how many times in a row (about a minute). */
export declare const PAPERS_RETRY_MS = 2000;
/**
 * A batch's papers for the progress window's lists behind 成功, 失败 and 剩余
 * (user, 2026-11-10): every paper once, then the ones that changed. What a
 * report did not get through goes again with the next one, so the list catches
 * up once the batch has its backend; a backend without the lists gets nothing.
 */
export declare class PaperList {
    private readonly backend;
    private readonly id;
    private readonly folder;
    private readonly retryMs;
    private readonly papers;
    private readonly unsent;
    private retry?;
    private retries;
    private finished;
    constructor(backend: CarsiBackend | undefined, id: string, folder: string, papers: ReadonlyArray<Omit<CarsiBatchPaper, "index">>, retryMs?: number);
    set(offset: number, paper: Omit<CarsiBatchPaper, "index">): void;
    /** ``last``: the batch's final list, which may start the backend for itself. */
    send(last?: boolean): Promise<void>;
    /**
     * A report that did not get through goes again shortly, not only after the next
     * paper: between two papers the batch's backend may be closed (a page that timed
     * out), and a failed paper was missing from the 失败 list while the next one
     * downloaded (Windows, user 2026-11-11). The next download's backend takes it.
     */
    private retryLater;
    private stopRetrying;
}
//# sourceMappingURL=batchPapers.d.ts.map