import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "@jest/globals";
import { downloadBatch } from "../../src/capabilities/download/batch/batch.js";
import { batchFolderName, INDEX_FILE, RUN_FOLDER, writeIndex } from "../../src/capabilities/download/batch/batchFolder.js";
import { batchSaveFolder } from "../../src/capabilities/download/handler.js";
import type { DownloadTier } from "../../src/capabilities/download/content/pdf/DownloadTier.js";

/**
 * A batch's own folder, as the ARD batch was laid out (user, 2026-11-17): named for what it
 * holds, the papers' folders straight inside, _run/ with what was asked, the progress lines and
 * each run's records, and in it article_index.csv with every paper and how it went.
 */
const root = mkdtempSync(join(tmpdir(), "batch-folder-"));
afterAll(() => rmSync(root, { recursive: true, force: true }));

const csv = (folder: string) => readFileSync(join(folder, RUN_FOLDER, INDEX_FILE), "utf8").replace(/^﻿/, "").trim().split("\r\n");

describe("a batch's own folder", () => {
  it("is named for the batch inside the download folder, safe on every system", () => {
    expect(batchSaveFolder({ items: [{ doi: "10.1/x" }], savePath: root, folderName: "Osteoarthritis Cartilage_2024-2026" })).toBe(join(root, "Osteoarthritis Cartilage_2024-2026"));
    expect(batchFolderName("a/b:c?")).toBe("a_b_c_");
    expect(batchFolderName(" .. ")).toBeUndefined();
    expect(batchFolderName("_run")).toBeUndefined();
    // Without a name, a new <time>_PaperSearchDownload folder as before.
    expect(batchSaveFolder({ items: [{ doi: "10.1/x" }], savePath: root }, new Date(2026, 10, 17, 8, 0, 0)))
      .toBe(join(root, "20261117-080000_PaperSearchDownload"));
  });

  it("keeps what was asked, the progress lines and each run's records beside the papers, and lists them", async () => {
    const folder = join(root, "Osteoarthritis Cartilage_2024-2026");
    let missing = true;
    const tiers = (): DownloadTier[] => [{ id: "oa", stage: "unpaywall", run: async (context) => {
      if (context.doi === "10.1000/b" && missing) return { status: "error", code: "network", message: "HTTP 500" };
      const path = join(folder, `${context.doi!.split("/")[1]}.pdf`);
      writeFileSync(path, "%PDF-1.7");
      return { status: "ok", verified: true, path, message: "saved" };
    } }];
    const items = [{ doi: "10.1000/a", title: "Knees" }, { doi: "10.1000/b", title: "Hips, \"and\" more" }];
    const first = await downloadBatch({} as never, { items, savePath: folder, mode: "per_item" }, undefined, () => {}, tiers);
    const runs = join(folder, RUN_FOLDER);
    expect(JSON.parse(readFileSync(join(runs, "batch-args.json"), "utf8"))).toMatchObject({ items, savePath: folder, mode: "per_item" });
    expect(readFileSync(join(runs, "batch.log"), "utf8")).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[批量\] 运行记录：/);
    const own = join(runs, first.runLog!.split(/[\\/]/).pop()!);
    for (const file of ["run.json", "items.jsonl", "timeline.log", "batch-args.json"]) expect(existsSync(join(own, file))).toBe(true);
    expect(readFileSync(join(own, "items.jsonl"), "utf8")).toBe(readFileSync(join(first.runLog!, "items.jsonl"), "utf8"));
    // The markdown column only with PaperSearch Pro's features (src/config/edition.ts).
    const edition = process.env.PAPER_SEARCH_PRO_FEATURES;
    for (const pro of ["1", "0"]) {
      process.env.PAPER_SEARCH_PRO_FEATURES = pro;
      writeIndex(folder);
      const rows = csv(folder);
      expect(rows[0]).toBe(`index,doi,title,status,pdf,source,supplements,${pro === "1" ? "markdown," : ""}reason,folder`);
      expect(rows[1]).toMatch(/^1,10\.1000\/a,Knees,成功,.+\.pdf,开放下载 · 开放获取,/);
      expect(rows[2]).toMatch(pro === "1" ? /^2,10\.1000\/b,"Hips, ""and"" more",失败,,,,,/ : /^2,10\.1000\/b,"Hips, ""and"" more",失败,,,,(?!,)/);
    }
    process.env.PAPER_SEARCH_PRO_FEATURES = edition;

    // 接着下 into the same folder: its run is kept beside the first, the list as of the latest.
    missing = false;
    await downloadBatch({} as never, { items: [items[1]], savePath: folder, mode: "per_item", resumeOf: "x" }, undefined, () => {}, tiers);
    expect(readdirSync(runs).filter((name) => /^\d{8}-/.test(name))).toHaveLength(2);
    // What was first asked stays.
    expect(JSON.parse(readFileSync(join(runs, "batch-args.json"), "utf8")).items).toHaveLength(2);
    const rows = csv(folder);
    expect(rows).toHaveLength(3);
    expect(rows[2]).toMatch(/^2,10\.1000\/b,"Hips, ""and"" more",成功,"未知期刊_未知年份_Hips, _and_ more\.pdf",/);
  });
});
