import { spawnSync } from "child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { pathToFileURL } from "url";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";
import { textPdf } from "../fixtures/textPdf.js";

const shellQuote = (value: string) => `'${value.replace(/'/g, `'\\''`)}'`;

describe("CARSI serial batch through the CLI", () => {
  let tempDir: string;
  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "paper-search-carsi-batch-"));
  });
  afterEach(() => {
    rmSync(tempDir, { recursive: true, force: true });
  });

  function run(scenario: string, tool: string, args: Record<string, unknown>) {
    const binDir = join(tempDir, "bin");
    const logPath = join(tempDir, "fake.log");
    const pdfPath = join(tempDir, "fake.pdf");
    const windows = process.platform === "win32";
    const wrapper = join(binDir, windows ? "paper-search-carsi.cmd" : "paper-search-carsi");
    const fixture = join(process.cwd(), "tests/fixtures/carsi/fake/fake-carsi-mcp.mjs");
    mkdirSync(binDir, { recursive: true });
    writeFileSync(pdfPath, textPdf([["Example article", "https://doi.org/10.1000/one"]]));
    writeFileSync(
      wrapper,
      windows
        ? `@echo off\r\n"${process.execPath}" "${fixture}" --scenario ${scenario} --log "${logPath}" --file "${pdfPath}" %*\r\n`
        : `#!/bin/sh\nexec ${shellQuote(process.execPath)} ${shellQuote(fixture)} --scenario ${scenario} --log ${shellQuote(logPath)} --file ${shellQuote(pdfPath)} "$@"\n`,
    );
    chmodSync(wrapper, 0o755);
    writeFileSync(join(tempDir, "config.json"), JSON.stringify({ PAPER_SEARCH_CARSI_EXECUTABLE: wrapper }));
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      PATH: windows ? process.env.PATH : "",
      HOME: tempDir,
      XDG_DATA_HOME: join(tempDir, "xdg"),
      PAPER_SEARCH_CONFIG_FILE: join(tempDir, "config.json"),
      PAPER_SEARCH_HIDE_SETUP_HINT: "1",
      PAPER_SEARCH_CARSI_ENABLED: "true",
    };
    delete env.PAPER_SEARCH_UNPAYWALL_EMAIL;
    delete env.UNPAYWALL_EMAIL;
    delete env.PAPER_SEARCH_CARSI_EXECUTABLE;
    const result = spawnSync(
      process.execPath,
      ["--import", "tsx", "--import", pathToFileURL(join(process.cwd(), "tests/fixtures/carsi/fake/empty-pmc.mjs")).href,
        "src/cli.ts", "run", tool, "--json-args", JSON.stringify(args)],
      { cwd: process.cwd(), env, encoding: "utf8", timeout: 60_000 },
    );
    if (!existsSync(logPath)) {
      throw new Error(`Fake CARSI did not start (exit ${result.status}): ${result.error || result.stderr || result.stdout}`);
    }
    const events = readFileSync(logPath, "utf8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    return { result, calls: events.filter((event) => event.event === "call"),
      starts: events.filter((event) => event.event === "start").length };
  }

  it("download_batch sends every item's position and reports the batch end", () => {
    const { result, calls } = run("batch_capable", "download_batch", {
      // The preload gives these synthetic DOIs an empty PMC lookup; the real
      // CLI still executes the full funnel and the fake backend contract.
      items: [
        { source: "no_searcher", paperId: "10.1000/one" },
        { source: "no_searcher", paperId: "10.1000/two" },
      ],
      savePath: join(tempDir, "out"),
      useSciHub: false,
    });
    expect(result.status).toBe(0);
    const data = JSON.parse(result.stdout).data;
    // the fake returns the same PDF twice; only item 1 carries its DOI
    expect(data).toEqual(expect.objectContaining({ status: "partial", total: 2, succeeded: 1, failed: 1 }));
    const downloads = calls.filter((call) => call.tool === "carsi_download").map((call) => call.arguments);
    expect(downloads).toEqual([
      expect.objectContaining({ identifier: "10.1000/one", batch_index: 1, batch_total: 2, batch_done: 0, batch_succeeded: 0 }),
      expect.objectContaining({ identifier: "10.1000/two", batch_index: 2, batch_total: 2, batch_done: 1, batch_succeeded: 1 }),
    ]);
    expect(downloads[0].batch_id).toBe(downloads[1].batch_id);
    // The stretch's end, then the whole batch for the finished window; this
    // backend declares no ``results`` field, so it gets the totals only.
    const progress = calls.filter((call) => call.tool === "carsi_batch_progress").map((call) => call.arguments);
    expect(progress).toEqual([
      expect.objectContaining({ batch_id: downloads[0].batch_id, total: 2, done: 2, succeeded: 1, failed: 1, finished: true }),
      expect.objectContaining({ batch_id: downloads[0].batch_id, total: 2, done: 2, succeeded: 1, failed: 1, finished: true }),
    ]);
    expect(progress[1]).not.toHaveProperty("results");
    expect(result.stderr).toContain("[批量] 机构下载 2/2：10.1000/two");
  });

  it("keeps one backend through the CLI progress wrapper until the batch ends", () => {
    const { result, calls, starts } = run("batch_browser", "download_batch", {
      items: [
        { source: "no_searcher", paperId: "10.1000/one" },
        { source: "no_searcher", paperId: "10.1000/two" },
      ],
      mode: "entitled_only",
      savePath: join(tempDir, "out"),
      useSciHub: false,
    });
    expect(result.status).toBe(0);
    expect(starts).toBe(1);
    expect(calls.filter((call) => call.tool === "carsi_download").map((call) => call.arguments.keep_browser))
      .toEqual([true, true]);
    expect(calls.at(-1)?.tool).toBe("carsi_close_batch_browser");
    expect(result.stderr).toContain("[批量] 机构下载 2/2：10.1000/two");
  });

  it.each([
    ["batch_browser", false],
    ["batch_browser_phase", true],
  ])("%s: a large batch shows its open-access stretch through one backend before the first download", (scenario, phase) => {
    const { result, calls, starts } = run(scenario as string, "download_batch", {
      items: ["one", "two", "three", "four", "five"].map((id) => ({ source: "no_searcher", paperId: `10.1000/${id}` })),
      savePath: join(tempDir, "out"),
      useSciHub: false,
    });
    expect(result.status).toBe(0);
    const progress = calls.filter((call) => call.tool === "carsi_batch_progress").map((call) => call.arguments);
    // No open-access copy: nothing settles in the open stretch, and the school's stretch carries on.
    expect(progress.slice(0, 5).map((args) => [args.done, args.total, args.finished])).toEqual(
      [1, 2, 3, 4, 5].map(() => [0, 5, false]));
    if (phase) {
      expect(progress.slice(0, 5).map((args) => [args.phase, args.channel])).toEqual(
        [1, 2, 3, 4, 5].map((k) => [`开放获取：已查 ${k}/5 篇，找到 0 篇`, "开放获取"]));
    } else {
      expect(progress[0]).not.toHaveProperty("phase");
    }
    const downloads = calls.filter((call) => call.tool === "carsi_download").map((call) => call.arguments);
    expect(downloads.map((args) => [args.batch_index, args.batch_total])).toEqual(
      [1, 2, 3, 4, 5].map((k) => [k, 5]));
    // One backend for the open-access reports, then the download backend kept for the batch.
    expect(starts).toBe(2);
  });

  it("a backend without batch support gets the plain contract", () => {
    const { result, calls } = run("success", "download_with_fallback", {
      source: "no_searcher",
      paperId: "10.1000/one",
      savePath: join(tempDir, "out"),
      useSciHub: false,
      batch: { id: "b", index: 1, total: 1 },
    });
    expect(result.status).toBe(0);
    const download = calls.find((call) => call.tool === "carsi_download");
    expect(Object.keys(download.arguments).filter((key) => key.startsWith("batch_"))).toEqual([]);
    expect(calls.some((call) => call.tool === "carsi_batch_progress")).toBe(false);
  });
});
