/** How soon a report that did not get through goes again, and how many times in a row (about a minute). */
export const PAPERS_RETRY_MS = 2_000;
const PAPERS_RETRIES = 30;
/**
 * A batch's papers for the progress window's lists behind 成功, 失败 and 剩余
 * (user, 2026-11-10): every paper once, then the ones that changed. What a
 * report did not get through goes again with the next one, so the list catches
 * up once the batch has its backend; a backend without the lists gets nothing.
 */
export class PaperList {
    backend;
    id;
    folder;
    retryMs;
    papers;
    unsent = new Set();
    retry;
    retries = 0;
    finished = false;
    constructor(backend, id, folder, papers, retryMs = PAPERS_RETRY_MS) {
        this.backend = backend;
        this.id = id;
        this.folder = folder;
        this.retryMs = retryMs;
        this.papers = papers.map((paper, offset) => ({ ...paper, index: offset + 1 }));
        this.papers.forEach((_, offset) => this.unsent.add(offset));
    }
    set(offset, paper) {
        const next = { ...paper, index: offset + 1 };
        if (JSON.stringify(next) === JSON.stringify(this.papers[offset]))
            return;
        this.papers[offset] = next;
        this.unsent.add(offset);
    }
    /** ``last``: the batch's final list, which may start the backend for itself. */
    async send(last = false) {
        if (last)
            this.stopRetrying();
        if (!this.backend?.reportBatchPapers || !this.unsent.size)
            return;
        const offsets = [...this.unsent].sort((a, b) => a - b);
        this.unsent.clear();
        let sent = false;
        try {
            sent = await this.backend.reportBatchPapers({ id: this.id, folder: this.folder, papers: offsets.map((offset) => this.papers[offset]) }, last);
        }
        catch {
            sent = false; // the lists are optional; they never change a download
        }
        if (sent) {
            this.retries = 0;
            return;
        }
        offsets.forEach((offset) => this.unsent.add(offset));
        this.retryLater();
    }
    /**
     * A report that did not get through goes again shortly, not only after the next
     * paper: between two papers the batch's backend may be closed (a page that timed
     * out), and a failed paper was missing from the 失败 list while the next one
     * downloaded (Windows, user 2026-11-11). The next download's backend takes it.
     */
    retryLater() {
        if (this.finished || this.retry || this.retries >= PAPERS_RETRIES)
            return;
        this.retries += 1;
        this.retry = setTimeout(() => {
            this.retry = undefined;
            void this.send();
        }, this.retryMs);
        this.retry.unref?.();
    }
    stopRetrying() {
        this.finished = true;
        if (this.retry)
            clearTimeout(this.retry);
        this.retry = undefined;
    }
}
//# sourceMappingURL=batchPapers.js.map