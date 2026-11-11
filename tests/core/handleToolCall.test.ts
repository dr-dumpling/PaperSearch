import { readFileSync, mkdtempSync, rmSync, writeFileSync } from "fs";
import { textPdf } from "../fixtures/textPdf.js";
import { tmpdir } from "os";
import { join } from "path";
import { afterEach, describe, expect, it, jest } from "@jest/globals";
import {
  handleToolCall,
  TOOL_HANDLER_NAMES,
} from "../../src/core/handleToolCall.js";
import { getGenericSearchToolPlatform } from "../../src/registry/platformMetadata.js";
import { TOOLS } from "../../src/core/tools.js";
import { PaperFactory } from "../../src/models/Paper.js";
import CitationService from "../../src/capabilities/citation-expansion/CitationService.js";
import { OpenAlexGraph } from "../../src/capabilities/citation-expansion/OpenAlexGraph.js";
import { CrossrefReferences } from "../../src/capabilities/citation-expansion/CrossrefReferences.js";

function responseData(response: any): any {
  const text = response.content[0].text;
  const start = text.indexOf("{");
  return JSON.parse(text.slice(start));
}

/** A real PDF whose first page labels ``doi`` (what a correct download looks like). */
function articlePdf(doi: string): string {
  const dir = mkdtempSync(join(tmpdir(), "paper-search-article-"));
  const path = join(dir, "article.pdf");
  writeFileSync(path, textPdf([["Example article", `doi:${doi}`]]));
  return path;
}

describe("handleToolCall", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe("tool routing", () => {
    it("keeps every non-generic tool wired to the explicit handler map", () => {
      const nonGenericToolNames = TOOLS.map((tool) => tool.name)
        .filter((toolName) => !getGenericSearchToolPlatform(toolName))
        .sort();

      expect(TOOL_HANDLER_NAMES).toEqual(nonGenericToolNames);
    });

    it("keeps generic registry tools outside the explicit handler map", () => {
      expect(getGenericSearchToolPlatform("search_dblp")).toBe("dblp");
      expect(getGenericSearchToolPlatform("search_springerlink")).toBe(
        "springerlink",
      );
      expect(TOOL_HANDLER_NAMES).not.toContain("search_dblp");
      expect(TOOL_HANDLER_NAMES).not.toContain("search_springerlink");
    });
  });

  describe("download_paper fallback", () => {
    it("rejects Wiley before any removed native downloader can run", async () => {
      const legacyDownload = jest.fn(async () => "/tmp/legacy-wiley.pdf");

      await expect(
        handleToolCall(
          "download_paper",
          {
            paperId: "10.1002/example",
            platform: "wiley",
            savePath: "./downloads",
          },
          {
            wiley: {
              getCapabilities: () => ({ download: true }),
              downloadPdf: legacyDownload,
            },
          } as any,
        ),
      ).rejects.toThrow("Unsupported download platform");
      expect(legacyDownload).not.toHaveBeenCalled();
    });

    it("routes unsupported platform downloads through the fallback funnel including Sci-Hub", async () => {
      const fallbackPdf = articlePdf("10.1000/example");
      const searchers = {
        crossref: {
          getCapabilities: () => ({ download: false }),
          getPaperByDoi: async () => null,
        },
        scihub: {
          downloadPdf: async () => fallbackPdf,
        },
      } as any;

      const response = await handleToolCall(
        "download_paper",
        {
          paperId: "10.1000/example",
          platform: "crossref",
          savePath: "./downloads",
        },
        searchers,
      );
      const text = response.content[0].text;
      const data = responseData(response);

      expect(text).toContain("Download paper ok");
      expect(data.status).toBe("ok");
      expect(readFileSync(data.path)).toEqual(readFileSync(fallbackPdf));
      expect(data.attempts.map((attempt: any) => attempt.stage)).toContain(
        "scihub",
      );
    });

    it("runs a successful native downloader exactly once through the primary tier", async () => {
      const nativeDownload = jest.fn(async () => "/tmp/native.pdf");
      const response = await handleToolCall(
        "download_paper",
        { paperId: "PMC11466435", platform: "pmc", savePath: "./downloads" },
        {
          pmc: {
            getCapabilities: () => ({ download: true }),
            downloadPdf: nativeDownload,
          },
        } as any,
      );
      const data = responseData(response);

      expect(nativeDownload).toHaveBeenCalledTimes(1);
      expect(data).toEqual({
        runLog: expect.any(String),
        status: "ok",
        path: "/tmp/native.pdf",
        attempts: [
          { stage: "primary", status: "ok", message: "/tmp/native.pdf" }
        ],
      });
    });

    it("runs a failing native downloader once, then continues through the single funnel", async () => {
      const nativeDownload = jest.fn(async () => {
        throw new Error("native failed");
      });
      const scihubPdf = articlePdf("10.1000/example");
      const scihubDownload = jest.fn(async () => scihubPdf);
      const response = await handleToolCall(
        "download_paper",
        {
          paperId: "10.1000/example",
          platform: "crossref",
          savePath: "./downloads",
        },
        {
          crossref: {
            getCapabilities: () => ({ download: true }),
            downloadPdf: nativeDownload,
            getPaperByDoi: async () => null,
          },
          scihub: { downloadPdf: scihubDownload },
        } as any,
      );
      const data = responseData(response);

      expect(nativeDownload).toHaveBeenCalledTimes(1);
      expect(scihubDownload).toHaveBeenCalledTimes(1);
      expect(data.status).toBe("ok");
      expect(data.attempts[0]).toEqual({
        stage: "primary",
        status: "error",
        message: "native failed",
      });
      expect(data.attempts.at(-1)).toEqual(
        expect.objectContaining({ stage: "scihub", status: "ok" }),
      );
      expect(data.attempts.map((attempt: any) => attempt.stage)).not.toContain(
        "entitled_access",
      );
    });

    it("injects CARSI only into download handlers through ToolCallDependencies", async () => {
      const tempDir = mkdtempSync(
        join(tmpdir(), "paper-search-handler-entitled-"),
      );
      const pdfPath = join(tempDir, "paper.pdf");
      writeFileSync(
        pdfPath,
        textPdf([["Example article", "doi:10.1000/example"]]),
      );
      const downloadLegalDoi = jest.fn(async () => ({
        kind: "success" as const,
        identifier: "10.1000/example",
        path: pdfPath,
      }));

      try {
        const response = await handleToolCall(
          "download_with_fallback",
          {
            source: "crossref",
            paperId: "10.1000/example",
            doi: "10.1000/example",
            savePath: tempDir,
            useSciHub: false,
          },
          {
            crossref: {
              getCapabilities: () => ({ download: false }),
              getPaperByDoi: async () => null,
            },
          } as any,
          { carsiBackend: { downloadLegalDoi } as any },
        );
        const data = responseData(response);

        expect(data.status).toBe("ok");
        expect(readFileSync(data.path)).toEqual(readFileSync(pdfPath));
        expect(downloadLegalDoi).toHaveBeenCalledTimes(1);
      } finally {
        rmSync(tempDir, { recursive: true, force: true });
      }
    });
  });

  describe("citation expansion tools", () => {
    const work = (citedByCount = 0, referencedWorks: string[] = []) => ({ id: "W1", citedByCount, referencedWorks });
    const openalexPaper = (paperId: string, title: string, doi: string, year?: number) =>
      ({ paperId, title, citationCount: 0, referenceCount: 0, doi, year, source: "openalex" as const });
    const deposited = (title: string, doi?: string, number?: number) =>
      ({ paperId: doi || title, title, citationCount: 0, referenceCount: 0, doi, source: "crossref" as const, ...(number ? { number } : {}) });

    it("takes every citing paper from OpenAlex", async () => {
      const getCitations = jest.spyOn(CitationService.prototype, "getCitations");
      jest.spyOn(OpenAlexGraph.prototype, "work").mockResolvedValue(work(2));
      const citedBy = jest.spyOn(OpenAlexGraph.prototype, "citedBy").mockResolvedValue([
        openalexPaper("W8", "Citing one", "10.1000/one"),
        openalexPaper("W9", "Citing two", "10.1000/two"),
      ]);

      const data = responseData(await handleToolCall("get_paper_citations", { doi: "10.1000/example" }, {} as any));

      expect(citedBy).toHaveBeenCalledWith("W1");
      expect(getCitations).not.toHaveBeenCalled();
      expect(data).toMatchObject({ target: "DOI:10.1000/example", relation: "citations", provider: "openalex", total: 2, citedByCount: 2 });
      expect(data.notes).toBeUndefined();
    });

    it("says so when a paper is cited more often than OpenAlex lists without a key", async () => {
      jest.spyOn(OpenAlexGraph.prototype, "work").mockResolvedValue(work(29491));
      jest.spyOn(OpenAlexGraph.prototype, "citedBy").mockResolvedValue(
        Array.from({ length: 10000 }, (_, i) => openalexPaper(`W${i}`, `Citing ${i}`, `10.1000/${i}`)),
      );

      const data = responseData(await handleToolCall("get_paper_citations", { doi: "10.1038/s41586-020-2649-2" }, {} as any));

      expect(data.total).toBe(10000);
      expect(data.notes[0]).toMatch(/^OpenAlex counts 29491 citing papers; without an API key it lists the newest 10000\. OPENALEX_API_KEY \(free\) lists them all: Get one at https:\/\/openalex\.org\/settings\/api/);
    });

    it("asks Semantic Scholar for citing papers only when OpenAlex has no record of the paper", async () => {
      const citation = { paperId: "citing-1", title: "Citing Paper", citationCount: 12, referenceCount: 34, doi: "10.1000/citing" };
      jest.spyOn(OpenAlexGraph.prototype, "work").mockResolvedValue(null);
      const getCitations = jest.spyOn(CitationService.prototype, "getCitations").mockResolvedValue([citation]);

      const data = responseData(await handleToolCall("get_paper_citations", { doi: "10.1000/example" }, {} as any));

      expect(getCitations).toHaveBeenCalledWith("DOI:10.1000/example", 1000);
      expect(data.provider).toBe("semantic_scholar");
      expect(data.papers).toEqual([citation]);
      expect(data.notes[0]).toMatch(/OpenAlex has no record/);
    });

    it("uses paperId before doi and arxivId when multiple citation identifiers are present", async () => {
      jest.spyOn(CitationService.prototype, "getCitationData").mockResolvedValue(null);
      const getCitations = jest.spyOn(CitationService.prototype, "getCitations").mockResolvedValue([]);

      await handleToolCall("get_paper_citations", { paperId: "semantic-paper-id", doi: "10.1000/example", arxivId: "2401.00001" }, {} as any);

      expect(getCitations).toHaveBeenCalledWith("semantic-paper-id", 1000);
    });

    it("lists references from the publisher's deposit alone when it describes them, numbered as in the paper", async () => {
      const work_ = jest.spyOn(OpenAlexGraph.prototype, "work");
      jest.spyOn(CrossrefReferences.prototype, "list").mockResolvedValue([
        deposited("The Global Epidemic of the Metabolic Syndrome", "10.1007/s11906-018-0812-z", 1),
        deposited("Smith J. An unlinked reference. 2019.", undefined, 2),
        deposited("Pathophysiology of acute kidney injury", "10.1002/cphy.c110041", 4),
      ]);

      const response = await handleToolCall("get_paper_references", { doi: "10.1016/j.arth.2024.06.028" }, {} as any);
      const data = responseData(response);

      expect(work_).not.toHaveBeenCalled();
      expect(data.papers.map((p: any) => p.number)).toEqual([1, 2, 4]);
      expect(data).toMatchObject({ provider: "crossref", total: 3, numberedTo: 4, missing: [3] });
      expect(response.content[0].text).toMatch(/^Found 3 cited reference\(s\)\. The paper's list is numbered to 4; the publisher deposited 3 of them with Crossref, not #3\./);
    });

    it("takes OpenAlex's list, newest first, when the publisher deposited little more than DOIs", async () => {
      jest.spyOn(CrossrefReferences.prototype, "list").mockResolvedValue([
        deposited("", "10.1000/a"), deposited("", "10.1000/b"), deposited("Only one has a title", "10.1000/c"),
      ]);
      jest.spyOn(OpenAlexGraph.prototype, "work").mockResolvedValue(work(0, ["W2", "W3", "W4"]));
      jest.spyOn(OpenAlexGraph.prototype, "works").mockResolvedValue([
        openalexPaper("W2", "Older", "10.1000/a", 2010),
        openalexPaper("W3", "Newer", "10.1000/b", 2020),
      ]);

      const data = responseData(await handleToolCall("get_paper_references", { doi: "10.1002/art.70156" }, {} as any));

      expect(data.provider).toBe("openalex");
      expect(data.papers.map((p: any) => p.title)).toEqual(["Newer", "Older"]);
      expect(data.notes).toEqual([
        "The publisher deposited little more than DOIs with Crossref; this is OpenAlex's list.",
        "OpenAlex lists 3 references; 1 of them it has no record of any more.",
      ]);
    });

    it("takes Semantic Scholar's list for a paper without a DOI", async () => {
      const reference = { paperId: "reference-1", title: "Reference Paper", citationCount: 7, referenceCount: 21, doi: "10.1000/reference" };
      jest.spyOn(CitationService.prototype, "getCitationData").mockResolvedValue(null);
      const list = jest.spyOn(CrossrefReferences.prototype, "list");
      const getReferenceList = jest.spyOn(CitationService.prototype, "getReferenceList").mockResolvedValue({ papers: [reference], withheld: false });

      const data = responseData(await handleToolCall("get_paper_references", { arxivId: "2401.00001" }, {} as any));

      expect(list).not.toHaveBeenCalled();
      expect(getReferenceList).toHaveBeenCalledWith("ARXIV:2401.00001", 1000);
      expect(data.provider).toBe("semantic_scholar");
      expect(data.papers).toEqual([reference]);
    });

    it("says why when no source lists the references", async () => {
      jest.spyOn(CrossrefReferences.prototype, "list").mockResolvedValue([]);
      jest.spyOn(OpenAlexGraph.prototype, "work").mockResolvedValue(null);
      jest.spyOn(CitationService.prototype, "getReferenceList").mockResolvedValue({ papers: [], withheld: true });

      const response = await handleToolCall("get_paper_references", { doi: "10.1000/none" }, {} as any);

      expect(response.content[0].text).toMatch(/^Found 0 cited reference\(s\)\. Neither Crossref nor OpenAlex lists references for this paper, and Semantic Scholar withholds them/);
    });
  });

  describe("get_paper_by_doi", () => {
    // Waiting on all nine sources made each DOI take as long as the slowest (Windows 2026-11-11).
    const paperFor = (doi: string, source: string) =>
      PaperFactory.create({ paperId: doi, title: `Paper ${doi}`, doi, source });
    const sources = (known: Record<string, string[]>, calls: string[] = [], failing: string[] = []) =>
      Object.fromEntries(["crossref", "openalex", "unpaywall", "pubmed", "europepmc"].map((source) => [source, {
        getPaperByDoi: async (doi: string) => {
          calls.push(`${source} ${doi}`);
          if (failing.includes(source)) throw new Error(`${source} unreachable`);
          return (known[source] || []).includes(doi) ? paperFor(doi, source) : null;
        },
      }])) as any;

    it("asks Crossref alone when it knows the DOI", async () => {
      const calls: string[] = [];
      const response = await handleToolCall("get_paper_by_doi", { doi: "10.1000/a" },
        sources({ crossref: ["10.1000/a"], openalex: ["10.1000/a"] }, calls));
      expect(calls).toEqual(["crossref 10.1000/a"]);
      expect(response.content[0].text.split("\n")[0]).toBe("DOI lookup: 1 of 1 found.");
      const data = responseData(response);
      expect(data).toMatchObject({ doi: "10.1000/a", sources_requested: "auto", requested: 1, found: 1,
        not_found: [], lookup_failed: [], total: 1, sources_used: ["crossref"] });
      expect(data.papers.map((paper: any) => paper.source)).toEqual(["crossref"]);
    });

    it("asks the other sources only for a DOI Crossref does not know, and keeps the first match", async () => {
      const calls: string[] = [];
      const data = responseData(await handleToolCall("get_paper_by_doi", { doi: "10.5281/zenodo.1" },
        sources({ openalex: ["10.5281/zenodo.1"], unpaywall: ["10.5281/zenodo.1"] }, calls)));
      expect(calls[0]).toBe("crossref 10.5281/zenodo.1");
      expect(calls).toHaveLength(5);
      expect(data.papers.map((paper: any) => paper.source)).toEqual(["openalex"]);
      expect(data.source_results).toMatchObject({ crossref: 0, openalex: 1, unpaywall: 1 });
    });

    it("looks up several DOIs in one call, in the order given, telling not found from not checked", async () => {
      const response = await handleToolCall("get_paper_by_doi",
        { dois: "10.1000/a, 10.1000/b;10.1000/missing 10.1000/A", platform: "auto" },
        sources({ crossref: ["10.1000/a", "10.1000/b"] }));
      const data = responseData(response);
      expect(data).toMatchObject({ requested: 3, found: 2, not_found: ["10.1000/missing"], lookup_failed: [], total: 2 });
      expect(data.papers.map((paper: any) => paper.doi)).toEqual(["10.1000/a", "10.1000/b"]);
      expect(data).not.toHaveProperty("doi");
      // No source could answer: not checked, rather than not found.
      const down = responseData(await handleToolCall("get_paper_by_doi", { dois: ["10.1000/a", "10.1000/b"] },
        sources({}, [], ["crossref", "openalex", "unpaywall", "pubmed", "europepmc"])));
      expect(down).toMatchObject({ found: 0, not_found: [], lookup_failed: ["10.1000/a", "10.1000/b"] });
      expect(down.warnings).toContain("10.1000/a crossref: crossref unreachable");
    });

    it("answers in the same shape for one source, a failing source included", async () => {
      const data = responseData(await handleToolCall("get_paper_by_doi", { doi: "10.1000/a", platform: "openalex" },
        sources({ openalex: ["10.1000/a"] })));
      expect(data).toMatchObject({ sources_requested: "openalex", found: 1, sources_used: ["openalex"] });
      expect(data.papers[0].source).toBe("openalex");
      const failed = responseData(await handleToolCall("get_paper_by_doi", { doi: "10.1000/a", platform: "pubmed" },
        sources({}, [], ["pubmed"])));
      expect(failed).toMatchObject({ found: 0, lookup_failed: ["10.1000/a"], failed_sources: ["pubmed"] });
      await expect(handleToolCall("get_paper_by_doi", { platform: "crossref" }, sources({}))).rejects.toThrow();
    });
  });

  describe("get_paper_by_doi all", () => {
    it("keeps DOI all-source lookup order derived from registry without adding unsupported sources", async () => {
      const calls: string[] = [];
      const lookupSource = (source: string) => ({
        getPaperByDoi: async () => {
          calls.push(source);
          return null;
        },
      });
      const searchers = Object.fromEntries(
        [
          "crossref",
          "openalex",
          "unpaywall",
          "pubmed",
          "pmc",
          "europepmc",
          "core",
          "webofscience",
          "semantic"
        ].map((source) => [source, lookupSource(source)]),
      ) as any;

      const response = await handleToolCall(
        "get_paper_by_doi",
        { doi: "10.1000/example", platform: "all" },
        searchers,
      );
      const data = responseData(response);

      expect(data.sources_used).toEqual([
        "crossref",
        "openalex",
        "unpaywall",
        "pubmed",
        "pmc",
        "europepmc",
        "core",
        "webofscience"
      ]);
      expect(calls).toEqual(data.sources_used);
      expect(data.sources_used).not.toEqual(
        expect.arrayContaining(["semantic", "wiley"]),
      );
    });

    it("skips failed sources and reports warnings without failing the whole lookup", async () => {
      const matchingPaper = PaperFactory.create({
        paperId: "10.1000/example",
        title: "Matched DOI",
        doi: "10.1000/example",
        source: "crossref",
      });
      const wrongPaper = PaperFactory.create({
        paperId: "openalex-1",
        title: "Wrong DOI",
        doi: "10.1000/wrong",
        source: "openalex",
      });
      const searchers = {
        crossref: {
          getPaperByDoi: async () => matchingPaper,
        },
        openalex: {
          getPaperByDoi: async () => wrongPaper,
        },
        pubmed: {
          getPaperByDoi: async () => {
            throw new Error("PubMed temporary failure");
          },
        },
      } as any;

      const response = await handleToolCall(
        "get_paper_by_doi",
        { doi: "10.1000/example", platform: "all" },
        searchers,
      );
      const data = responseData(response);

      expect(data.total).toBe(1);
      expect(data.papers[0].source).toBe("crossref");
      expect(data.source_results.crossref).toBe(1);
      expect(data.source_results.openalex).toBe(0);
      expect(data.source_results.pubmed).toBe(0);
      expect(data.failed_sources).toEqual(["openalex", "pubmed"]);
      expect(data.errors.openalex).toContain("did not match requested DOI");
      expect(data.errors.pubmed).toContain("temporary failure");
      expect(data.warnings).toHaveLength(2);
    });
  });
});
