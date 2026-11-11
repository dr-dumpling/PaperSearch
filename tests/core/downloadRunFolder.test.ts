import { join, resolve } from "path";
import { describe, expect, it } from "@jest/globals";
import { runDownloadFolder } from "../../src/config/ConfigService.js";
import { batchSaveFolder, downloadRunFolder } from "../../src/capabilities/pdf-discovery/handler.js";
import type { DownloadBatchOptions } from "../../src/capabilities/pdf-discovery/batch.js";

// Each download run saves into its own folder, so runs are not mixed (user, 2026-11-11).
describe("the download folder of one run", () => {
  it("is named after the run's start inside the download folder", () => {
    const at = new Date(2026, 10, 11, 1, 30, 45);
    expect(runDownloadFolder("/data/papers", at)).toBe(join("/data/papers", "20261111-013045_PaperSearchDownload"));
  });

  it("stays the same over a caller's own serial batch; another run gets its own", () => {
    const first = new Date(2026, 10, 11, 1, 30, 45), later = new Date(2026, 10, 11, 1, 31, 10);
    const batch = `batch-${process.pid}-${Date.now()}`;
    const folder = downloadRunFolder("/data/papers", batch, first);
    expect(folder).toBe(join("/data/papers", "20261111-013045_PaperSearchDownload"));
    expect(downloadRunFolder("/data/papers", batch, later)).toBe(folder);
    expect(downloadRunFolder("/data/papers", `${batch}-other`, later)).toBe(join("/data/papers", "20261111-013110_PaperSearchDownload"));
    expect(downloadRunFolder("/data/papers", undefined, later)).toBe(join("/data/papers", "20261111-013110_PaperSearchDownload"));
  });

  // Papers the caller sent to folders of their own, by topic, stay there (user, 2026-11-11):
  // the batch's own folder (its run log, the window's folder button) is the one holding them all.
  it("is the folder holding every paper's own folder when each paper has one", () => {
    const at = new Date(2026, 10, 11, 1, 30, 45);
    const batch = (savePath: string | undefined, ...own: Array<string | undefined>) =>
      ({ savePath, items: own.map((path, i) => ({ doi: `10.1000/${i}`, ...(path ? { savePath: path } : {}) })) }) as DownloadBatchOptions;
    const topics = resolve("/data/oa-weight");
    expect(batchSaveFolder(batch("/data/papers", `${topics}/1_sarcopenia`, `${topics}/2_glp1`, `${topics}/2_glp1`), at)).toBe(topics);
    expect(batchSaveFolder(batch(undefined, `${topics}/1_sarcopenia`), at)).toBe(join(topics, "1_sarcopenia"));
    // One paper without its own folder: the run's dated folder, as for every other batch.
    expect(batchSaveFolder(batch("/data/papers", `${topics}/1_sarcopenia`, undefined), at))
      .toBe(join("/data/papers", "20261111-013045_PaperSearchDownload"));
    // Nothing in common below the root: the dated folder too.
    expect(batchSaveFolder(batch("/data/papers", "/one/a", "/two/b"), at)).toBe(join("/data/papers", "20261111-013045_PaperSearchDownload"));
  });
});
