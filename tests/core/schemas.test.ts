import { afterEach, describe, expect, it } from "@jest/globals";
import { parseToolArgs } from "../../src/core/schemas.js";

describe("schemas", () => {
  const originalCoreCap = process.env.CORE_MAX_RESULTS_CAP;

  afterEach(() => {
    if (originalCoreCap === undefined) delete process.env.CORE_MAX_RESULTS_CAP;
    else process.env.CORE_MAX_RESULTS_CAP = originalCoreCap;
  });

  it("keeps CORE maxResults capped at 100 by default", () => {
    delete process.env.CORE_MAX_RESULTS_CAP;

    expect(() =>
      parseToolArgs("search_core", {
        query: "machine learning",
        maxResults: 101,
      }),
    ).toThrow("CORE maxResults must be less than or equal to 100");
  });

  it("allows users to raise the CORE maxResults cap up to the hard limit", () => {
    process.env.CORE_MAX_RESULTS_CAP = "300";

    expect(
      parseToolArgs("search_core", {
        query: "machine learning",
        maxResults: 300,
      }),
    ).toEqual({
      query: "machine learning",
      maxResults: 300,
    });
    expect(() =>
      parseToolArgs("search_core", {
        query: "machine learning",
        maxResults: 301,
      }),
    ).toThrow("CORE maxResults must be less than or equal to 300");
  });

  it("applies the CORE cap to the generic search command when platform is core", () => {
    process.env.CORE_MAX_RESULTS_CAP = "300";

    expect(
      parseToolArgs("search_papers", {
        query: "machine learning",
        platform: "core",
        maxResults: 300,
      }),
    ).toEqual(
      expect.objectContaining({
        query: "machine learning",
        platform: "core",
        maxResults: 300,
      }),
    );
    expect(() =>
      parseToolArgs("search_papers", {
        query: "machine learning",
        platform: "crossref",
        maxResults: 300,
      }),
    ).toThrow("Number must be less than or equal to 100");
  });

  it("clamps CORE_MAX_RESULTS_CAP to the hard maximum", () => {
    process.env.CORE_MAX_RESULTS_CAP = "9999";

    expect(
      parseToolArgs("search_core", {
        query: "machine learning",
        maxResults: 500,
      }),
    ).toEqual({
      query: "machine learning",
      maxResults: 500,
    });
    expect(() =>
      parseToolArgs("search_core", {
        query: "machine learning",
        maxResults: 501,
      }),
    ).toThrow("CORE maxResults must be less than or equal to 500");
  });

  it("requires one citation target identifier", () => {
    expect(() => parseToolArgs("get_paper_citations", {})).toThrow(
      "Provide paperId, doi, or arxivId",
    );
    expect(() => parseToolArgs("get_paper_references", { limit: 5 })).toThrow(
      "Provide paperId, doi, or arxivId",
    );
  });

  it("takes no limit for citations or references: both return everything", () => {
    for (const tool of ["get_paper_citations", "get_paper_references"]) {
      expect(parseToolArgs(tool, { doi: "10.1000/example", limit: 5 })).toEqual({ doi: "10.1000/example" });
    }
  });

  it("preserves citation identifiers for handleToolCall priority resolution", () => {
    expect(
      parseToolArgs("get_paper_references", {
        paperId: "paper-1",
        doi: "10.1000/example",
        arxivId: "2401.00001",
      }),
    ).toEqual({
      paperId: "paper-1",
      doi: "10.1000/example",
      arxivId: "2401.00001",
    });
  });

  it("rejects the removed Wiley native downloader as a download platform", () => {
    expect(() =>
      parseToolArgs("download_paper", {
        paperId: "10.1002/example",
        platform: "wiley",
      }),
    ).toThrow("Unsupported download platform");
  });

  it("strips authorized-backend selection knobs from download_with_fallback", () => {
    expect(
      parseToolArgs("download_with_fallback", {
        source: "crossref",
        paperId: "10.1000/example",
        institutional_access: true,
        authorizedBackend: "native",
        carsi: true,
      }),
    ).toEqual({
      source: "crossref",
      paperId: "10.1000/example",
      doi: "",
      title: "",
      useEntitledAccess: true,
      useSciHub: true,
      content: "main",
    });
  });

  it("defaults useEntitledAccess=true for both public download entry points", () => {
    expect(
      parseToolArgs("download_paper", {
        paperId: "10.1000/example",
        platform: "crossref",
      }),
    ).toEqual({
      paperId: "10.1000/example",
      platform: "crossref",
      useEntitledAccess: true,
    });
    expect(
      parseToolArgs("download_with_fallback", {
        source: "crossref",
        paperId: "10.1000/example",
      }),
    ).toEqual({
      source: "crossref",
      paperId: "10.1000/example",
      doi: "",
      title: "",
      useEntitledAccess: true,
      useSciHub: true,
      content: "main",
    });
  });

  it("allows either public download entry point to disable entitled access per request", () => {
    expect(
      parseToolArgs("download_paper", {
        paperId: "10.1000/example",
        platform: "crossref",
        useEntitledAccess: false,
      }),
    ).toEqual({
      paperId: "10.1000/example",
      platform: "crossref",
      useEntitledAccess: false,
    });
    expect(
      parseToolArgs("download_with_fallback", {
        source: "crossref",
        paperId: "10.1000/example",
        useEntitledAccess: false,
      }),
    ).toEqual({
      source: "crossref",
      paperId: "10.1000/example",
      doi: "",
      title: "",
      useEntitledAccess: false,
      useSciHub: true,
      content: "main",
    });
  });
});
