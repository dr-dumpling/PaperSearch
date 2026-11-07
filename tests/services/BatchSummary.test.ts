import { tmpdir } from "node:os";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "@jest/globals";
import { asWindowBatch } from "../../src/capabilities/pdf-discovery/batchSummary.js";
import type { CarsiBackend, CarsiBatchUpdate } from "../../src/capabilities/pdf-discovery/carsi/types.js";
import type { DownloadBatchPosition } from "../../src/capabilities/pdf-discovery/types.js";

function fakeBackend(updates: CarsiBatchUpdate[]): CarsiBackend {
  return {
    probe: async () => ({ state: "available", code: "ready", message: "", missing: [] }),
    downloadLegalDoi: async () => {
      throw new Error("downloads are faked");
    },
    reportBatchProgress: async (update) => {
      updates.push(update);
      return true;
    },
  };
}

describe("a lone download as a batch of one", () => {
  const roots: string[] = [];
  const root = () => {
    const dir = mkdtempSync(join(tmpdir(), "lone-download-"));
    roots.push(dir);
    return dir;
  };
  afterEach(() => roots.splice(0).forEach((dir) => rmSync(dir, { recursive: true, force: true })));

  it("ends the window with its reason once it reached the backend", async () => {
    const updates: CarsiBatchUpdate[] = [];
    const seen: Array<DownloadBatchPosition | undefined> = [];
    const savePath = root();
    await asWindowBatch({ source: "crossref", paperId: "10.1000/x", doi: "10.1000/x", savePath }, fakeBackend(updates),
      async (options) => {
        seen.push(options.batch);
        return { status: "error", title: "A Paper", journal: "Spine",
          attempts: [{ stage: "entitled_access", status: "error", code: "login_timeout", message: "" }] };
      });
    expect(seen).toEqual([{ id: expect.any(String), index: 1, total: 1, done: 0, succeeded: 0, failed: 0 }]);
    expect(updates).toEqual([expect.objectContaining({
      id: seen[0]!.id, total: 1, done: 1, succeeded: 0, failed: 1, finished: true,
      results: expect.objectContaining({
        folder: savePath,
        failures: [{ cls: "user_or_external", reason: "等学校登录超时", title: "A Paper", journal: "Spine", doi: "10.1000/x" }],
      }),
    })]);
  });

  it("points a saved paper's folder button at its own folder", async () => {
    const updates: CarsiBatchUpdate[] = [];
    const savePath = root();
    const paperDir = join(savePath, "papers", "Spine_2026_A Paper_abc");
    await asWindowBatch({ source: "crossref", paperId: "10.1000/x", doi: "10.1000/x", savePath }, fakeBackend(updates),
      async () => ({ status: "ok", path: join(paperDir, "A Paper.pdf"),
        attempts: [{ stage: "entitled_access", status: "ok", message: "" }] }));
    expect(updates.at(-1)?.results).toEqual(expect.objectContaining({ folder: paperDir, main: 1, sources: [["机构订阅", 1]] }));
  });

  it("opens no window for a copy that never reached the backend", async () => {
    const updates: CarsiBatchUpdate[] = [];
    await asWindowBatch({ source: "crossref", paperId: "10.1000/x", doi: "10.1000/x", savePath: root() }, fakeBackend(updates),
      async () => ({ status: "ok", path: "/tmp/x.pdf", attempts: [
        { stage: "unpaywall", status: "ok", message: "" },
        { stage: "entitled_access", status: "skipped", message: "" },
      ] }));
    expect(updates).toEqual([]);
  });
});
