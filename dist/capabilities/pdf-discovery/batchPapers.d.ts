import type { CarsiBackend, CarsiBatchPaper } from "./carsi/index.js";
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
    private readonly papers;
    private readonly unsent;
    constructor(backend: CarsiBackend | undefined, id: string, folder: string, papers: ReadonlyArray<Omit<CarsiBatchPaper, "index">>);
    set(offset: number, paper: Omit<CarsiBatchPaper, "index">): void;
    /** ``last``: the batch's final list, which may start the backend for itself. */
    send(last?: boolean): Promise<void>;
}
//# sourceMappingURL=batchPapers.d.ts.map