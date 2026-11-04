import axios from "axios";
import { createHash } from "node:crypto";
import { mkdtempSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, jest } from "@jest/globals";
import { textPdf } from "../fixtures/textPdf.js";
import { createRepositoryTier } from "../../src/capabilities/pdf-discovery/tiers/repositories.js";
import { createUnpaywallTier } from "../../src/capabilities/pdf-discovery/tiers/unpaywall.js";
import { oaHostPolicy } from "../../src/capabilities/pdf-discovery/oaHosts.js";

const pdf = textPdf([["Example article", "doi:10.1000/example"]]);
const pdfResponse = { status: 200, headers: { "content-type": "application/pdf", "content-length": String(pdf.length) }, data: pdf };
const context = (extra: Record<string, unknown> = {}) => ({
  searchers: {} as never,
  source: "crossref",
  paperId: "10.1000/example",
  doi: "10.1000/example",
  savePath: mkdtempSync(join(tmpdir(), "paper-search-oa-")),
  useEntitledAccess: true,
  useSciHub: false,
  ...extra,
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe("PubMed Central through the PMC Article Datasets bucket", () => {
  it("maps the DOI to a PMCID and downloads the bucket PDF after its MD5 check", async () => {
    const md5 = createHash("md5").update(pdf).digest("hex");
    const urls: string[] = [];
    jest.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ records: [{ doi: "10.1000/example", pmcid: "PMC123" }] }), { status: 200 }),
    );
    jest.spyOn(axios, "get").mockImplementation(async (url: string) => {
      urls.push(url);
      if (url.endsWith(".amazonaws.com/")) return { status: 200, data: "<ListBucketResult><CommonPrefixes><Prefix>PMC123.1/</Prefix></CommonPrefixes><CommonPrefixes><Prefix>PMC123.2/</Prefix></CommonPrefixes></ListBucketResult>" };
      if (url.endsWith("metadata/PMC123.2.json")) return { status: 200, data: { pdf_url: `s3://pmc-oa-opendata/PMC123.2/PMC123.2.pdf?md5=${md5}` } };
      if (url.endsWith("PMC123.2/PMC123.2.pdf")) return pdfResponse;
      throw new Error(`unexpected ${url}`);
    }) as never;
    const result = await createRepositoryTier().run(context());
    expect(result.status).toBe("ok");
    expect(existsSync(result.path!)).toBe(true);
    expect(result.trace).toEqual({ pmcid: "PMC123", via: "pmc_cloud" });
    expect(urls.some((url) => url.includes("pmc.ncbi.nlm.nih.gov/articles"))).toBe(false);
  });

  it("is skipped when the DOI has no PMCID", async () => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ records: [{ doi: "10.1000/example" }] }), { status: 200 }),
    );
    const result = await createRepositoryTier().run(context());
    expect(result).toEqual({ status: "skipped", message: "Not in PubMed Central." });
  });
});

describe("Unpaywall OA locations", () => {
  const unpaywall = (urls: string[]) => ({
    resolvePdfCandidates: async () => urls.map((url) => ({ url, hostType: "repository", version: "publishedVersion" })),
  });

  it("leaves bot-protected publisher copies to the browser and defers arXiv", () => {
    expect(oaHostPolicy("https://onlinelibrary.wiley.com/doi/pdfdirect/10.1/x")).toBe("browser");
    expect(oaHostPolicy("https://www.sciencedirect.com/science/article/pii/S1/pdfft")).toBe("browser");
    expect(oaHostPolicy("https://arxiv.org/pdf/2401.00001")).toBe("preprint");
    expect(oaHostPolicy("https://www.nature.com/articles/s41586-024-1.pdf")).toBe("http");
  });

  it("downloads the first plain-HTTP copy and does not touch browser-only hosts", async () => {
    const get = jest.spyOn(axios, "get").mockResolvedValue(pdfResponse as never);
    const result = await createUnpaywallTier().run(context({
      searchers: { unpaywall: unpaywall(["https://onlinelibrary.wiley.com/doi/pdfdirect/10.1000/example", "https://repo.example.edu/example.pdf"]) },
    }) as never);
    expect(result.status).toBe("ok");
    expect(get.mock.calls.map((call) => call[0])).toEqual(["https://repo.example.edu/example.pdf"]);
  });

  it("does not settle for a submitted manuscript while a published copy exists", async () => {
    const get = jest.spyOn(axios, "get").mockResolvedValue(pdfResponse as never);
    const result = await createUnpaywallTier().run(context({
      searchers: {
        unpaywall: {
          resolvePdfCandidates: async () => [
            { url: "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1000/example", hostType: "publisher", version: "publishedVersion" },
            { url: "https://repo.example.edu/preprint.pdf", hostType: "repository", version: "submittedVersion" },
          ],
        },
      },
    }) as never);
    expect(result).toEqual(expect.objectContaining({ status: "skipped", code: "browser_only" }));
    expect(get).not.toHaveBeenCalled();
  });

  it("reports browser_only when every copy needs a browser", async () => {
    const get = jest.spyOn(axios, "get");
    const result = await createUnpaywallTier().run(context({
      searchers: { unpaywall: unpaywall(["https://onlinelibrary.wiley.com/doi/pdfdirect/10.1000/example", "https://arxiv.org/pdf/1"]) },
    }) as never);
    expect(result).toEqual(expect.objectContaining({ status: "skipped", code: "browser_only" }));
    expect(get).not.toHaveBeenCalled();
  });
});
