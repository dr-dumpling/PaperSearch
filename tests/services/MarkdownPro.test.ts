import axios from "axios";
import { mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, jest } from "@jest/globals";
import { handleDownloadWithFallback } from "../../src/capabilities/download/handler.js";
import { markdownMissing } from "../../src/capabilities/download/content/markdown/shortfall.js";
import { markdownBlocked, proEntry, useMarkdownPro } from "../../src/capabilities/download/content/markdown/pro.js";
import type { SchoolBackend, SchoolDownloadRequest } from "../../src/infrastructure/school/index.js";
import { fakeMarkdownPro } from "../helpers/fakeMarkdownPro.js";

// PaperSearch Pro's features on, whatever the edition (src/config/edition.ts).
process.env.PAPER_SEARCH_PRO_FEATURES = "1";

// The Markdown is PaperSearch Pro's (user, 2026-11-18): without Pro, or while Pro says it cannot
// be used, a paper's Markdown says why, and nothing is visited or fetched for it.
describe("the Markdown without PaperSearch Pro", () => {
  let dir: string;
  let visits: SchoolDownloadRequest[];
  let asked: string[];
  const backend = {
    downloadLegalDoi: async (request: SchoolDownloadRequest) => {
      visits.push(request);
      return { kind: "attempt_error", identifier: request.identifier, code: "fulltext_page_only", message: "" };
    },
  } as unknown as SchoolBackend;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "papersearch-markdown-pro-"));
    visits = [];
    asked = [];
    process.env.PAPER_SEARCH_RUNLOG_DIR = join(dir, ".runs");
    jest.spyOn(axios, "get").mockImplementation((async (url: string) => { asked.push(String(url)); throw new Error("offline"); }) as never);
    jest.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      asked.push(String(url));
      return new Response(JSON.stringify({ records: [{}] }), { status: 200 });
    });
  });
  afterEach(() => {
    useMarkdownPro(undefined);
    jest.restoreAllMocks();
    delete process.env.PAPER_SEARCH_RUNLOG_DIR;
    rmSync(dir, { recursive: true, force: true });
  });

  const markdownOnly = async () => {
    const response = await handleDownloadWithFallback({ source: "crossref", paperId: "10.9999/example.1", doi: "10.9999/example.1",
      savePath: dir, content: "markdown", fulltext: true } as never, {} as never, backend);
    const text = response.content[0].text;
    return JSON.parse(text.slice(text.indexOf("{")));
  };

  it("says Pro is needed, and opens no page for the Markdown", async () => {
    useMarkdownPro(undefined);
    const result = await markdownOnly();
    expect(result).toMatchObject({ status: "error", markdown: { status: "unavailable", code: "markdown_pro_required" } });
    expect(visits).toEqual([]);
    expect(asked.filter((url) => /ncbi|europepmc|elsevier/i.test(url))).toEqual([]);
    expect(readdirSync(dir).filter((name) => !name.startsWith("."))).toEqual([]);
    expect(markdownMissing(result.markdown)).toEqual({ cls: "user_side", reason: "需要 Pro" });
  });

  it("says why when Pro cannot be used now, in Pro's own words", async () => {
    useMarkdownPro(fakeMarkdownPro({ access: () => ({ ok: false, code: "markdown_pro_key_required", message: "Pro needs a key." }) }));
    const result = await markdownOnly();
    expect(result).toMatchObject({ markdown: { code: "markdown_pro_key_required", message: "Pro needs a key." } });
    expect(visits).toEqual([]);
    expect(markdownMissing(result.markdown)).toEqual({ cls: "user_side", reason: "Pro 暂不可用" });
  });

  it("asks Pro when it can be used, and only then", async () => {
    const asks: string[] = [];
    useMarkdownPro(fakeMarkdownPro({ fetchFulltext: async (request) => {
      asks.push(request.doi);
      return { status: "unavailable", code: "page_not_supported", message: "No rules." };
    } }));
    expect(markdownBlocked()).toBeUndefined();
    await markdownOnly();
    expect(asks).toEqual(["10.9999/example.1"]);
  });

  it("looks for Pro in PaperSearch's data folder, or where PAPER_SEARCH_PRO_PATH says", () => {
    expect(proEntry({ XDG_DATA_HOME: "/data" })).toBe(join(resolve("/data"), "paper-search-cli", "pro", "index.js"));
    expect(proEntry({ PAPER_SEARCH_PRO_PATH: "/opt/pro/index.js" })).toBe("/opt/pro/index.js");
  });
});
