import type { CarsiBackend, CarsiBatchPaper } from "./carsi/index.js";

/**
 * A batch's papers for the progress window's lists behind 成功, 失败 and 剩余
 * (user, 2026-11-10): every paper once, then the ones that changed. What a
 * report did not get through goes again with the next one, so the list catches
 * up once the batch has its backend; a backend without the lists gets nothing.
 */
export class PaperList {
  private readonly papers: CarsiBatchPaper[];
  private readonly unsent = new Set<number>();

  constructor(
    private readonly backend: CarsiBackend | undefined,
    private readonly id: string,
    private readonly folder: string,
    papers: ReadonlyArray<Omit<CarsiBatchPaper, "index">>,
  ) {
    this.papers = papers.map((paper, offset) => ({ ...paper, index: offset + 1 }));
    this.papers.forEach((_, offset) => this.unsent.add(offset));
  }

  set(offset: number, paper: Omit<CarsiBatchPaper, "index">): void {
    const next = { ...paper, index: offset + 1 };
    if (JSON.stringify(next) === JSON.stringify(this.papers[offset])) return;
    this.papers[offset] = next;
    this.unsent.add(offset);
  }

  /** ``last``: the batch's final list, which may start the backend for itself. */
  async send(last = false): Promise<void> {
    if (!this.backend?.reportBatchPapers || !this.unsent.size) return;
    const offsets = [...this.unsent].sort((a, b) => a - b);
    this.unsent.clear();
    let sent = false;
    try {
      sent = await this.backend.reportBatchPapers(
        { id: this.id, folder: this.folder, papers: offsets.map((offset) => this.papers[offset]) }, last);
    } catch {
      sent = false;  // the lists are optional; they never change a download
    }
    if (!sent) offsets.forEach((offset) => this.unsent.add(offset));
  }
}
