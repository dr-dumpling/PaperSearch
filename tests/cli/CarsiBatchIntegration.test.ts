import { spawnSync } from "child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { pathToFileURL } from "url";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";
import { textPdf } from "../fixtures/textPdf.js";
import type { CarsiBatchPaper } from "../../src/capabilities/pdf-discovery/carsi/types.js";

const shellQuote = (value: string) => `'${value.replace(/'/g, `'\\''`)}'`;

describe("CARSI serial batch through the CLI", () => {
  let tempDir: string;
  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "paper-search-carsi-batch-"));
  });
  afterEach(() => {
    rmSync(tempDir, { recursive: true, force: true });
  });

  function run(scenario: string, tool: string, args: Record<string, unknown>, extraEnv: NodeJS.ProcessEnv = {}) {
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
      ...extraEnv,
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
    return { result, events, calls: events.filter((event) => event.event === "call"),
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
    // Item two's open-access check may still run when item one's download starts.
    expect(result.stderr).toMatch(/\[批量\] 机构下载( 2\/2|第 2 篇（开放来源还在查）)：10\.1000\/two/);
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

  it.each(["batch_browser", "batch_browser_phase"])(
    "%s: a backend that cannot show both lanes gets no open-access line beside its downloads", (scenario) => {
    const { result, calls, starts } = run(scenario, "download_batch", {
      items: ["one", "two", "three", "four", "five"].map((id) => ({ source: "no_searcher", paperId: `10.1000/${id}` })),
      savePath: join(tempDir, "out"),
      useSciHub: false,
    });
    expect(result.status).toBe(0);
    // No open-access copy: the first item goes to the school at once, and every
    // open-access report then carries the lanes line this backend does not declare.
    const progress = calls.filter((call) => call.tool === "carsi_batch_progress").map((call) => call.arguments);
    expect(progress.every((args) => args.finished)).toBe(true);
    const downloads = calls.filter((call) => call.tool === "carsi_download").map((call) => call.arguments);
    expect(downloads.map((args) => [args.batch_index, args.batch_total])).toEqual(
      [1, 2, 3, 4, 5].map((k) => [k, 5]));
    // Nor the papers' lists, which cost it no backend start of their own.
    expect(calls.some((call) => call.tool === "carsi_batch_papers")).toBe(false);
    expect(starts).toBe(1);
  });

  it("batch_browser_lanes: open access reports both lanes while the school's downloads run, through their backend", () => {
    const { result, events, calls, starts } = run("batch_browser_lanes", "download_batch", {
      items: ["one", "two", "three", "four", "five"].map((id) => ({ source: "no_searcher", paperId: `10.1000/${id}` })),
      savePath: join(tempDir, "out"),
      useSciHub: false,
    }, { PAPER_SEARCH_TEST_PMC_DELAY_MS: "600" });
    expect(result.status).toBe(0);
    const progress = calls.filter((call) => call.tool === "carsi_batch_progress").map((call) => call.arguments);
    const lanes = progress.filter((args) => !args.finished);
    expect(lanes.length).toBeGreaterThan(0);
    expect(lanes.every((args) => /^开放下载 0 篇 · 机构下载 [0-5] 篇$/.test(args.lanes))).toBe(true);
    expect(lanes.map((args) => args.done)).toEqual(lanes.map((args) => args.done).sort((a, b) => a - b));
    // At least one arrived while a download ran (between its call and its end).
    const during = events.some((event, at) => event.event === "call" && event.tool === "carsi_batch_progress"
      && !event.arguments.finished
      && events.slice(0, at).filter((e) => e.event === "call" && e.tool === "carsi_download").length
        > events.slice(0, at).filter((e) => e.event === "done").length);
    expect(during).toBe(true);
    const downloads = calls.filter((call) => call.tool === "carsi_download").map((call) => call.arguments);
    expect(downloads.map((args) => [args.batch_index, args.batch_total, args.keep_browser])).toEqual(
      [1, 2, 3, 4, 5].map((k) => [k, 5, true]));
    // The window's lists ride on the same backend: every paper first, then as each ended.
    const papers = calls.filter((call) => call.tool === "carsi_batch_papers")
      .map((call) => call.arguments as { folder: string; papers: CarsiBatchPaper[] });
    expect(papers[0].papers.map((paper) => paper.index)).toEqual([1, 2, 3, 4, 5]);
    expect(papers[0].folder).toBe(join(tempDir, "out"));
    const ended = new Map(papers.flatMap((args) => args.papers).map((paper) => [paper.index, paper]));
    // Each as the batch ended it (the fake gives every paper the first one's PDF).
    const items = JSON.parse(result.stdout).data.items as Array<{ index: number; status: string }>;
    expect([...ended.values()].map((paper) => [paper.index, paper.state])).toEqual(
      items.map((item) => [item.index, item.status === "ok" ? "ok" : "failed"]));
    expect(items.filter((item) => item.status === "ok").length).toBeGreaterThan(0);
    for (const paper of ended.values()) {
      if (paper.state === "ok") expect(paper).toMatchObject({ via: "机构下载", path: expect.any(String) });
      else expect(paper.reason).toBeTruthy();
    }
    // One backend for the downloads and the reports beside them.
    expect(starts).toBe(1);
  }, 90_000);

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
