import { spawnSync } from "child_process";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
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
    const wrapper = join(binDir, "paper-search-carsi");
    const fixture = join(process.cwd(), "tests/fixtures/carsi/fake/fake-carsi-mcp.mjs");
    mkdirSync(binDir, { recursive: true });
    writeFileSync(pdfPath, textPdf([["Example article", "https://doi.org/10.1000/one"]]));
    writeFileSync(
      wrapper,
      `#!/bin/sh\nexec ${shellQuote(process.execPath)} ${shellQuote(fixture)} --scenario ${scenario} --log ${shellQuote(logPath)} --file ${shellQuote(pdfPath)} "$@"\n`,
    );
    chmodSync(wrapper, 0o755);
    writeFileSync(join(tempDir, "config.json"), JSON.stringify({ PAPER_SEARCH_CARSI_EXECUTABLE: wrapper }));
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      PATH: "",
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
      [join(process.cwd(), "node_modules/.bin/tsx"), "src/cli.ts", "run", tool, "--json-args", JSON.stringify(args)],
      { cwd: process.cwd(), env, encoding: "utf8", timeout: 60_000 },
    );
    const calls = readFileSync(logPath, "utf8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line))
      .filter((event) => event.event === "call");
    return { result, calls };
  }

  it("download_batch sends every item's position and reports the batch end", () => {
    const { result, calls } = run("batch_capable", "download_batch", {
      // paperId without doi keeps the open-access stages offline (as in the
      // single-download integration test); entitled access uses the paperId.
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
    expect(calls.filter((call) => call.tool === "carsi_batch_progress").map((call) => call.arguments)).toEqual([
      expect.objectContaining({ batch_id: downloads[0].batch_id, total: 2, done: 2, succeeded: 1, failed: 1, finished: true }),
    ]);
    expect(result.stderr).toContain("[批量] 机构下载 2/2：10.1000/two");
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
