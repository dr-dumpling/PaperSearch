import axios from "axios";
import { textPdf } from "../fixtures/textPdf.js";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { afterEach, describe, expect, it, jest } from "@jest/globals";
import {
  createDefaultDownloadTiers,
  downloadWithFallback,
  insertDownloadTierBefore,
  type DownloadTier,
} from "../../src/capabilities/pdf-discovery/OpenAccessFallbackService.js";
import { hasOpenAccessProvenance } from "../../src/capabilities/pdf-discovery/tiers/directPdfUrl.js";

function validPdfBuffer(size = 10_100): Buffer {
  const buffer = Buffer.alloc(size, 0x20);
  buffer.write("%PDF-1.7\n", 0, "latin1");
  buffer.write("\n%%EOF\n", buffer.length - 7, "latin1");
  return buffer;
}

function unavailablePrimarySearchers(
  scihubDownload = jest.fn(async () => "/tmp/scihub.pdf"),
) {
  return {
    crossref: {
      getCapabilities: () => ({ download: false }),
      getPaperByDoi: async () => null,
    },
    scihub: {
      downloadPdf: scihubDownload,
    },
  } as any;
}

/** A real PDF whose first page labels ``doi`` (what a correct download looks like). */
function articlePdf(doi: string): string {
  const dir = mkdtempSync(join(tmpdir(), "paper-search-article-"));
  const path = join(dir, "article.pdf");
  writeFileSync(path, textPdf([["Example article", `doi:${doi}`]]));
  return path;
}

describe("OpenAccessFallbackService", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("accepts only registry OA sources or explicit paper-level OA provenance", () => {
    const paper = (extra?: Record<string, unknown>) => ({ extra }) as any;

    expect(hasOpenAccessProvenance("pmc", paper())).toBe(true);
    expect(
      hasOpenAccessProvenance("crossref", paper({ openAccess: true })),
    ).toBe(true);
    expect(
      hasOpenAccessProvenance("crossref", paper({ isOpenAccess: true })),
    ).toBe(true);
    expect(
      hasOpenAccessProvenance("crossref", paper({ openAccess: false })),
    ).toBe(false);
    expect(hasOpenAccessProvenance("sciencedirect", paper())).toBe(false);
  });

  describe("identity of every downloaded PDF", () => {
    const searchers = { crossref: { getCapabilities: () => ({ download: false }) } } as any;
    const tier = (stage: string, path: string) => ({
      id: stage,
      stage,
      run: async () => ({ status: "ok" as const, path, message: path }),
    });

    it("keeps an open tier's wrong article for review and lets the next tier deliver", async () => {
      const wrong = articlePdf("10.1000/other");
      const right = articlePdf("10.1000/example");
      const result = await downloadWithFallback(
        searchers,
        { source: "crossref", paperId: "10.1000/example", doi: "10.1000/example" },
        [tier("repositories", wrong), tier("unpaywall", right)],
      );
      expect(result.status).toBe("ok");
      expect(result.path).toBe(right);
      expect(result.attempts[0]).toEqual(
        expect.objectContaining({ stage: "repositories", status: "error", code: "pdf_identity_mismatch" }),
      );
      expect(existsSync(wrong)).toBe(false);
    });

    it("reports an unverified PDF for review when no tier proves the article", async () => {
      const dir = mkdtempSync(join(tmpdir(), "paper-search-unverified-"));
      const unlabelled = join(dir, "unlabelled.pdf");
      writeFileSync(unlabelled, textPdf([["Some article without its DOI"]]));
      const result = await downloadWithFallback(
        searchers,
        { source: "crossref", paperId: "10.1000/example", doi: "10.1000/example" },
        [tier("unpaywall", unlabelled)],
      );
      expect(result.status).toBe("error");
      expect(result.review).toEqual({ path: unlabelled, reason: "pdf_identity_unverified" });
    });

    it("looks up the title when only a DOI is given, to corroborate a DOI printed in a sentence", async () => {
      const dir = mkdtempSync(join(tmpdir(), "paper-search-title-"));
      const path = join(dir, "inline.pdf");
      writeFileSync(path, textPdf([["Sex differences in human performance", "Published online 2024 in Wiley Online Library DOI: 10.1000/example", "Abstract"]]));
      const withCrossref = { ...searchers, crossref: { ...searchers.crossref, getPaperByDoi: async () => ({ title: "Sex differences in human performance" }) } };
      const result = await downloadWithFallback(
        withCrossref,
        { source: "crossref", paperId: "10.1000/example", doi: "10.1000/example" },
        [tier("repositories", path)],
      );
      expect(result.status).toBe("ok");
    });

    it("gives self-verifying tiers the title before they run", async () => {
      let seenTitle: string | undefined;
      const withCrossref = { ...searchers, crossref: { ...searchers.crossref, getPaperByDoi: async () => ({ title: "Looked-up title" }) } };
      await downloadWithFallback(
        withCrossref,
        { source: "crossref", paperId: "10.1000/example", doi: "10.1000/example" },
        [{ id: "publisher_api", stage: "publisher_api", run: async (c) => { seenTitle = c.title; return { status: "skipped" as const, message: "" }; } }],
      );
      expect(seenTitle).toBe("Looked-up title");
    });

    it("accepts a PDF unchecked when the request names no DOI", async () => {
      const result = await downloadWithFallback(
        searchers,
        { source: "crossref", paperId: "PMC11466435" },
        [tier("primary", "/tmp/no-doi.pdf")],
      );
      expect(result.status).toBe("ok");
    });
  });

  it("uses Sci-Hub before entitled access by default", async () => {
    const paper = articlePdf("10.1000/example");
    const scihubDownload = jest.fn(async () => paper);
    const downloadLegalDoi = jest.fn();
    const searchers = {
      crossref: {
        getCapabilities: () => ({ download: false }),
        getPaperByDoi: async () => null,
      },
      scihub: {
        downloadPdf: scihubDownload,
      },
    } as any;

    const result = await downloadWithFallback(
      searchers,
      {
        source: "crossref",
        paperId: "10.1000/example",
        doi: "10.1000/example",
      },
      createDefaultDownloadTiers({ downloadLegalDoi } as any),
    );

    expect(result.status).toBe("ok");
    expect(result.path).toBe(paper);
    expect(scihubDownload).toHaveBeenCalledWith("10.1000/example", {
      savePath: "./downloads",
    });
    expect(result.attempts.map((attempt) => attempt.stage)).toEqual([
      "primary",
      "direct_pdf_url",
      "repositories",
      "unpaywall",
      "publisher_api",
      "scihub",
    ]);
    expect(downloadLegalDoi).not.toHaveBeenCalled();
    expect(result.attempts.map((attempt) => attempt.stage)).not.toContain(
      "institutional_access",
    );
    for (const attempt of result.attempts) {
      expect(Object.keys(attempt)).toEqual(["stage", "status", "message"]);
    }
  });

  it("allows callers to suppress the Sci-Hub fallback explicitly", async () => {
    const paper = articlePdf("10.1000/example");
    const scihubDownload = jest.fn(async () => paper);
    const searchers = {
      crossref: {
        getCapabilities: () => ({ download: false }),
        getPaperByDoi: async () => null,
      },
      scihub: {
        downloadPdf: scihubDownload,
      },
    } as any;

    const result = await downloadWithFallback(searchers, {
      source: "crossref",
      paperId: "10.1000/example",
      doi: "10.1000/example",
      useSciHub: false,
    });

    expect(result.status).toBe("error");
    expect(scihubDownload).not.toHaveBeenCalled();
    expect(result.attempts).toContainEqual({
      stage: "scihub",
      status: "skipped",
      message: "Sci-Hub fallback disabled by useSciHub=false.",
    });
    expect(result.attempts.map((attempt) => attempt.stage)).toEqual([
      "primary",
      "direct_pdf_url",
      "repositories",
      "unpaywall",
      "publisher_api",
      "scihub",
      "entitled_access",
    ]);
  });

  it("allows callers to inject custom tiers without changing the public result shape", async () => {
    const customTier: DownloadTier = {
      id: "custom",
      stage: "custom",
      run: async () => ({
        status: "ok",
        path: "/tmp/custom.pdf",
        message: "/tmp/custom.pdf",
      }),
    };

    const result = await downloadWithFallback(
      {} as any,
      {
        source: "crossref",
        paperId: "source-id",
      },
      [customTier],
    );

    expect(result).toEqual({
      status: "ok",
      path: "/tmp/custom.pdf",
      attempts: [{ stage: "custom", status: "ok", message: "/tmp/custom.pdf" }],
    });
  });

  it("inserts caller-owned tiers before a named stage without mutating the original list", () => {
    const original = createDefaultDownloadTiers();
    const customTier: DownloadTier = {
      id: "custom",
      stage: "custom",
      run: async () => ({ status: "skipped", message: "disabled" }),
    };

    const inserted = insertDownloadTierBefore(original, "scihub", customTier);

    expect(original.map((tier) => tier.stage)).toEqual([
      "primary",
      "direct_pdf_url",
      "repositories",
      "unpaywall",
      "publisher_api",
      "scihub",
      "entitled_access",
    ]);
    expect(inserted.map((tier) => tier.stage)).toEqual([
      "primary",
      "direct_pdf_url",
      "repositories",
      "unpaywall",
      "publisher_api",
      "custom",
      "scihub",
      "entitled_access",
    ]);
  });

  it("reaches entitled access after Sci-Hub fails even without an injected backend", async () => {
    const scihubDownload = jest.fn(async () => {
      throw new Error("Sci-Hub unavailable");
    });
    const result = await downloadWithFallback(
      unavailablePrimarySearchers(scihubDownload),
      {
        source: "crossref",
        paperId: "10.1000/example",
        doi: "10.1000/example",
      },
    );

    expect(result.status).toBe("error");
    expect(result.attempts).toContainEqual({
      stage: "scihub",
      status: "error",
      message: "Sci-Hub unavailable",
    });
    expect(result.attempts).toContainEqual({
      stage: "entitled_access",
      status: "skipped",
      message: "Entitled access backend unavailable.",
    });
    expect(scihubDownload).toHaveBeenCalledTimes(1);
  });

  it("does not call the injected backend when useEntitledAccess=false", async () => {
    const downloadLegalDoi = jest.fn();
    const result = await downloadWithFallback(
      unavailablePrimarySearchers(),
      {
        source: "crossref",
        paperId: "10.1000/example",
        doi: "10.1000/example",
        useEntitledAccess: false,
        useSciHub: false,
      },
      createDefaultDownloadTiers({ downloadLegalDoi } as any),
    );

    expect(downloadLegalDoi).not.toHaveBeenCalled();
    expect(result.attempts).toContainEqual({
      stage: "entitled_access",
      status: "skipped",
      message: "Entitled access disabled by useEntitledAccess=false.",
    });
  });

  it("accepts a valid entitled-access PDF after Sci-Hub fails", async () => {
    const tempDir = mkdtempSync(
      join(tmpdir(), "paper-search-entitled-success-"),
    );
    const pdfPath = join(tempDir, "paper.pdf");
    writeFileSync(
      pdfPath,
      textPdf([["Example article", "https://doi.org/10.1000/example"]]),
    );
    const downloadLegalDoi = jest.fn(async () => ({
      kind: "success" as const,
      identifier: "10.1000/example",
      path: pdfPath,
      source: "publisher",
    }));
    const scihubDownload = jest.fn(async () => {
      throw new Error("Sci-Hub unavailable");
    });

    try {
      const result = await downloadWithFallback(
        unavailablePrimarySearchers(scihubDownload),
        {
          source: "crossref",
          paperId: "source-id",
          doi: "10.1000/example",
          savePath: tempDir,
        },
        createDefaultDownloadTiers({ downloadLegalDoi } as any),
      );

      expect(downloadLegalDoi).toHaveBeenCalledWith({
        identifier: "10.1000/example",
        outputDir: tempDir,
      });
      expect(result).toEqual({
        status: "ok",
        path: pdfPath,
        attempts: expect.arrayContaining([
          {
            stage: "entitled_access",
            status: "ok",
            message: "Entitled access PDF downloaded.",
          },
        ]),
      });
      expect(result.attempts.map((attempt) => attempt.stage).slice(-2)).toEqual(
        ["scihub", "entitled_access"],
      );
      expect(scihubDownload).toHaveBeenCalledTimes(1);
      // The CARSI route label must not leak; the publisher_api stage name itself is public.
      expect(
        JSON.stringify(
          result.attempts.filter(
            (attempt) => attempt.stage === "entitled_access",
          ),
        ),
      ).not.toContain("publisher");
    } finally {
      rmSync(tempDir, { recursive: true, force: true });
    }
  });

  it.each([true, false])(
    "maps an entitled-access attempt error after Sci-Hub fails or is disabled, useSciHub=%s",
    async (useSciHub) => {
      const downloadLegalDoi = jest.fn(async () => ({
        kind: "attempt_error" as const,
        identifier: "10.1000/example",
        code: "download_failed",
        message: "secret upstream path and account detail",
      }));
      const scihubDownload = jest.fn(async () => {
        throw new Error("Sci-Hub unavailable");
      });
      const result = await downloadWithFallback(
        unavailablePrimarySearchers(scihubDownload),
        {
          source: "crossref",
          paperId: "10.1000/example",
          doi: "10.1000/example",
          useSciHub,
        },
        createDefaultDownloadTiers({ downloadLegalDoi } as any),
      );

      expect(result.attempts).toContainEqual({
        stage: "entitled_access",
        status: "error",
        code: "download_failed",
        message: "未取得可用 PDF；后端未提供可识别的失败分类。",
      });
      expect(JSON.stringify(result.attempts)).not.toContain("secret upstream");
      expect(scihubDownload).toHaveBeenCalledTimes(useSciHub ? 1 : 0);
      expect(result.status).toBe("error");
    },
  );

  it.each<[string, boolean]>([
    ["absent", true],
    ["absent", false],
    ["incompatible", true],
    ["incompatible", false],
  ])(
    "maps %s entitled-access readiness to skipped and respects useSciHub=%s",
    async (state, useSciHub) => {
      const downloadLegalDoi = jest.fn(async () => ({
        kind: "backend_unavailable" as const,
        readiness: {
          state,
          code: `sensitive_${state}`,
          message: "sensitive backend details",
          missing: ["/private/path"],
        },
      }));
      const scihubDownload = jest.fn(async () => {
        throw new Error("Sci-Hub unavailable");
      });
      const result = await downloadWithFallback(
        unavailablePrimarySearchers(scihubDownload),
        {
          source: "crossref",
          paperId: "10.1000/example",
          doi: "10.1000/example",
          useSciHub,
        },
        createDefaultDownloadTiers({ downloadLegalDoi } as any),
      );

      expect(result.attempts).toContainEqual({
        stage: "entitled_access",
        status: "skipped",
        message: "Entitled access backend unavailable.",
      });
      expect(JSON.stringify(result.attempts)).not.toMatch(/sensitive|private/);
      expect(scihubDownload).toHaveBeenCalledTimes(useSciHub ? 1 : 0);
      expect(result.status).toBe("error");
    },
  );

  it.each([true, false])(
    "rejects an invalid entitled-access PDF and respects useSciHub=%s",
    async (useSciHub) => {
      const tempDir = mkdtempSync(
        join(tmpdir(), "paper-search-entitled-invalid-"),
      );
      const invalidPath = join(tempDir, "not-a-pdf.txt");
      writeFileSync(invalidPath, "not a pdf");
      const downloadLegalDoi = jest.fn(async () => ({
        kind: "success" as const,
        identifier: "10.1000/example",
        path: invalidPath,
      }));
      const scihubDownload = jest.fn(async () => {
        throw new Error("Sci-Hub unavailable");
      });

      try {
        const result = await downloadWithFallback(
          unavailablePrimarySearchers(scihubDownload),
          {
            source: "crossref",
            paperId: "10.1000/example",
            doi: "10.1000/example",
            useSciHub,
          },
          createDefaultDownloadTiers({ downloadLegalDoi } as any),
        );

        expect(result.attempts).toContainEqual({
          stage: "entitled_access",
          status: "error",
          message: "Entitled access returned an invalid PDF.",
          code: "invalid_pdf",
        });
        expect(scihubDownload).toHaveBeenCalledTimes(useSciHub ? 1 : 0);
        expect(result.status).toBe("error");
      } finally {
        rmSync(tempDir, { recursive: true, force: true });
      }
    },
  );

  it("maps invalid_identifier to skipped and hides adapter details", async () => {
    const downloadLegalDoi = jest.fn(async () => ({
      kind: "attempt_error" as const,
      identifier: "not-a-doi",
      code: "invalid_identifier",
      message: "adapter rejected not-a-doi",
    }));
    const result = await downloadWithFallback(
      unavailablePrimarySearchers(),
      {
        source: "crossref",
        paperId: "not-a-doi",
        useSciHub: false,
      },
      createDefaultDownloadTiers({ downloadLegalDoi } as any),
    );

    expect(downloadLegalDoi).toHaveBeenCalledWith({
      identifier: "not-a-doi",
      outputDir: "./downloads",
    });
    expect(result.attempts).toContainEqual({
      stage: "entitled_access",
      status: "skipped",
      message: "Entitled access requires a valid DOI.",
    });
    expect(JSON.stringify(result.attempts)).not.toContain("adapter rejected");
  });

  it("redacts unexpected backend exceptions after Sci-Hub fails", async () => {
    const downloadLegalDoi = jest.fn(async () => {
      throw new Error("token and /private/path");
    });
    const scihubDownload = jest.fn(async () => {
      throw new Error("Sci-Hub unavailable");
    });
    const result = await downloadWithFallback(
      unavailablePrimarySearchers(scihubDownload),
      {
        source: "crossref",
        paperId: "10.1000/example",
        useSciHub: true,
      },
      createDefaultDownloadTiers({ downloadLegalDoi } as any),
    );

    expect(result.status).toBe("error");
    expect(scihubDownload).toHaveBeenCalledTimes(1);
    expect(result.attempts).toContainEqual({
      stage: "entitled_access",
      status: "error",
      message: "Entitled access download attempt failed.",
    });
    expect(JSON.stringify(result.attempts)).not.toMatch(/token|private/);
  });

  it("uses doi before source-native paperId for direct metadata lookup", async () => {
    const getPaperByDoi = jest.fn(async () => null);
    const searchers = {
      crossref: {
        getCapabilities: () => ({ download: false }),
        getPaperByDoi,
      },
      scihub: {
        downloadPdf: jest.fn(),
      },
    } as any;

    await downloadWithFallback(searchers, {
      source: "crossref",
      paperId: "crossref-source-id",
      doi: "10.1000/example",
      useSciHub: false,
    });

    expect(getPaperByDoi).toHaveBeenCalledWith("10.1000/example");
  });

  it("does not download a metadata PDF URL without explicit OA provenance", async () => {
    const get = jest
      .spyOn(axios, "get")
      .mockRejectedValue(new Error("network must not be called"));
    const searchers = {
      crossref: {
        getCapabilities: () => ({ download: false }),
        getPaperByDoi: async () => ({
          paperId: "10.1000/closed",
          pdfUrl: "https://publisher.example/closed.pdf",
          extra: { openAccess: false },
        }),
      },
    } as any;

    const result = await downloadWithFallback(searchers, {
      source: "crossref",
      paperId: "10.1000/closed",
      doi: "10.1000/closed",
      useSciHub: false,
    });

    expect(get).not.toHaveBeenCalledWith("https://publisher.example/closed.pdf", expect.anything());
    expect(result.attempts).toContainEqual(
      expect.objectContaining({
        stage: "direct_pdf_url",
        status: "skipped",
        message: expect.stringMatching(/open.?access|provenance/i),
      }),
    );
  });

  it("allows a metadata PDF URL only when the paper explicitly declares OA provenance", async () => {
    const pdf = textPdf([["Open article", "doi:10.1000/open"]]);
    jest.spyOn(axios, "get").mockResolvedValue({
      status: 200,
      headers: {
        "content-type": "application/pdf",
        "content-length": String(pdf.length),
      },
      data: pdf,
    } as any);
    const tempDir = mkdtempSync(join(tmpdir(), "paper-search-explicit-oa-"));
    const searchers = {
      crossref: {
        getCapabilities: () => ({ download: false }),
        getPaperByDoi: async () => ({
          paperId: "10.1000/open",
          pdfUrl: "https://repository.example/open.pdf",
          extra: { openAccess: true },
        }),
      },
    } as any;

    try {
      const result = await downloadWithFallback(searchers, {
        source: "crossref",
        paperId: "10.1000/open",
        doi: "10.1000/open",
        savePath: tempDir,
        useSciHub: false,
      });

      expect(result.status).toBe("ok");
      expect(result.attempts.map((attempt) => attempt.stage)).toEqual([
        "primary",
        "direct_pdf_url",
      ]);
    } finally {
      rmSync(tempDir, { recursive: true, force: true });
    }
  });

  it("skips Unpaywall cleanly when the searcher is unavailable", async () => {
    const searchers = {
      crossref: {
        getCapabilities: () => ({ download: false }),
        getPaperByDoi: async () => null,
      },
      scihub: {
        downloadPdf: jest.fn(),
      },
    } as any;

    const result = await downloadWithFallback(searchers, {
      source: "crossref",
      paperId: "source-id",
      doi: "10.1000/example",
      useSciHub: false,
    });

    expect(result.attempts).toContainEqual({
      stage: "unpaywall",
      status: "skipped",
      message: "Unpaywall searcher unavailable.",
    });
  });

  it("does not search repositories for a PDF; without a DOI PubMed Central is skipped", async () => {
    const calls: string[] = [];
    const repositorySearcher = (source: string) => ({
      search: jest.fn(async () => {
        calls.push(source);
        return [];
      }),
    });
    const searchers = {
      crossref: {
        getCapabilities: () => ({ download: false }),
        getPaperByDoi: async () => null,
      },
      pmc: repositorySearcher("pmc"),
      europepmc: repositorySearcher("europepmc"),
      core: repositorySearcher("core"),
      openaire: repositorySearcher("openaire"),
    } as any;

    const result = await downloadWithFallback(searchers, {
      source: "crossref",
      paperId: "source-id",
      title: "repository discovery title",
      useSciHub: false,
    });

    expect(calls).toEqual([]);
    expect(result.attempts).toContainEqual(
      expect.objectContaining({ stage: "repositories", status: "skipped", message: "Not in PubMed Central." }),
    );
  });
});
