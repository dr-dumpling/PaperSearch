import { join } from "path";
import { describe, expect, it } from "@jest/globals";
import { runDownloadFolder } from "../../src/config/ConfigService.js";
import { downloadRunFolder } from "../../src/capabilities/pdf-discovery/handler.js";

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
});
