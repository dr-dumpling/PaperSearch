import { describe, it, expect, jest, afterEach } from '@jest/globals';
import { PaperList, PAPERS_RETRY_MS } from '../../src/capabilities/pdf-discovery/batchPapers.js';
import type { SchoolBatchPapers } from '../../src/capabilities/pdf-discovery/school/index.js';

const waiting = (doi: string) => ({ doi, title: doi, journal: '', state: 'school' as const });

/** A backend that takes the lists only while ``up`` (the batch's backend process is there). */
function backend() {
  const state = { up: false, calls: 0, sent: [] as Array<Array<[number, string]>> };
  const reportBatchPapers = async (update: SchoolBatchPapers) => {
    state.calls += 1;
    if (!state.up) return false;
    state.sent.push(update.papers.map((paper) => [paper.index, paper.state]));
    return true;
  };
  return { state, backend: { reportBatchPapers } as any };
}

describe('the progress window\'s paper lists', () => {
  afterEach(() => {
    jest.useRealTimers();
  });

  it('sends a failed paper again within seconds when the backend was closed between two papers', async () => {
    // Windows 2026-11-11: a page timed out, the backend closed, and the failed paper
    // reached the 失败 list only after the next paper had downloaded.
    jest.useFakeTimers();
    const { state, backend: fake } = backend();
    state.up = true;
    const list = new PaperList(fake, 'batch', '/downloads', [waiting('10.1000/a'), waiting('10.1000/b')]);
    await list.send();
    state.up = false;
    list.set(0, { ...waiting('10.1000/a'), state: 'failed', cls: 'unexplained', reason: '页面处理超时' } as any);
    await list.send();
    expect(state.sent).toEqual([[[1, 'school'], [2, 'school']]]);
    // The next paper's backend starts: the list catches up on its own.
    state.up = true;
    await jest.advanceTimersByTimeAsync(PAPERS_RETRY_MS);
    expect(state.sent.at(-1)).toEqual([[1, 'failed']]);
    // Nothing left to send: no more reports.
    const calls = state.calls;
    await jest.advanceTimersByTimeAsync(PAPERS_RETRY_MS * 5);
    expect(state.calls).toBe(calls);
  });

  it('stops trying after about a minute without a backend, and once the last list is sent', async () => {
    jest.useFakeTimers();
    const { state, backend: fake } = backend();
    const list = new PaperList(fake, 'batch', '/downloads', [waiting('10.1000/a')]);
    await list.send();
    await jest.advanceTimersByTimeAsync(PAPERS_RETRY_MS * 100);
    expect(state.calls).toBe(31);  // the first report and 30 more

    const second = backend();
    const other = new PaperList(second.backend, 'batch', '/downloads', [waiting('10.1000/a')]);
    await other.send();
    await other.send(true);  // the batch's end: its own report, no retry after it
    const calls = second.state.calls;
    await jest.advanceTimersByTimeAsync(PAPERS_RETRY_MS * 10);
    expect(second.state.calls).toBe(calls);
  });
});
