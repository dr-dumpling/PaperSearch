import { mkdtempSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";
import { setUserConfigValue } from "../../src/config/ConfigService.js";
import { buildCapabilityProfile } from "../../src/management/capability-profile/index.js";
import type { EntitledAccessReadiness } from "../../src/management/capability-profile/carsiReadiness.js";

const CONFIG_ENV_KEYS = [
  "PAPER_SEARCH_CONFIG_FILE",
  "SEMANTIC_SCHOLAR_API_KEY",
  "EASYSCHOLAR_KEY",
  "ELSEVIER_API_KEY",
  "SPRINGER_API_KEY",
  "SPRINGER_OPENACCESS_API_KEY",
  "WOS_API_KEY",
  "IEEE_API_KEY",
  "PAPER_SEARCH_CARSI_ENABLED",
  "WILEY_TDM_TOKEN"
];

const FREE_METADATA_SOURCES = [
  "crossref",
  "openalex",
  "pubmed",
  "pmc",
  "europepmc",
  "biorxiv",
  "medrxiv",
  "semantic",
  "iacr",
  "core",
  "openaire",
  "googlescholar",
  "dblp",
  "acm",
  "usenix",
  "openreview"
];

const OPEN_ACCESS_SOURCES = [
  "biorxiv",
  "medrxiv",
  "pmc",
  "europepmc",
  "core",
  "openaire",
  "unpaywall",
  "openalex_oa_metadata",
  "semantic_open_access_pdf",
  "springer_open_access",
  "sciencedirect_open_access",
  "scopus_open_access_metadata",
  "iacr"
];

describe("capabilityProfile", () => {
  const originalEnv = { ...process.env };
  let tempDir: string;

  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "paper-search-profile-test-"));
    process.env = {
      ...originalEnv,
      PAPER_SEARCH_CONFIG_FILE: join(tempDir, "config.json"),
    };
    for (const key of CONFIG_ENV_KEYS) {
      if (key !== "PAPER_SEARCH_CONFIG_FILE") delete process.env[key];
    }
  });

  afterEach(() => {
    process.env = { ...originalEnv };
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("reports independent capabilities and marks an uninjected CARSI snapshot as not evaluated", () => {
    const profile = buildCapabilityProfile();
    const byId = Object.fromEntries(
      profile.entries.map((entry) => [entry.id, entry]),
    );

    expect(profile.ok).toBe(true);
    expect(profile.entries.map((entry) => entry.id)).toEqual([
      "metadata_search",
      "citation_expansion",
      "body_snippet_search",
      "journal_metrics",
      "pdf_discovery",
      "entitled_access"
    ]);

    expect(byId.metadata_search.status).toBe("available");
    expect(byId.metadata_search.configured).not.toContain("scihub");
    expect(byId.metadata_search.reason).toContain("Sci-Hub is excluded");
    expect(byId.metadata_search.sourceGroups?.free_sources).toEqual(
      FREE_METADATA_SOURCES,
    );
    expect(byId.metadata_search.sourceGroups?.missing_entitled_sources).toEqual(
      ["webofscience", "sciencedirect", "springer", "scopus", "ieee"],
    );
    expect(byId.metadata_search.optionalKeys).toEqual([
      "WOS_API_KEY",
      "ELSEVIER_API_KEY",
      "SPRINGER_API_KEY",
      "IEEE_API_KEY"
    ]);
    expect(byId.metadata_search.optionalKeys).not.toContain("WILEY_TDM_TOKEN");

    expect(byId.citation_expansion.status).toBe("available");
    expect(byId.citation_expansion.configured).toEqual([
      "semantic_scholar_graph"
    ]);
    expect(byId.citation_expansion.optionalKeys).toEqual([
      "SEMANTIC_SCHOLAR_API_KEY"
    ]);
    expect(byId.body_snippet_search.status).toBe("unavailable");
    expect(byId.body_snippet_search.reason).toContain(
      "SEMANTIC_SCHOLAR_API_KEY",
    );
    expect(byId.journal_metrics.status).toBe("unavailable");
    expect(byId.journal_metrics.requiredKeys).toEqual(["EASYSCHOLAR_KEY"]);

    expect(byId.pdf_discovery.status).toBe("available");
    expect(byId.pdf_discovery.sourceGroups?.open_access_sources).toEqual(
      OPEN_ACCESS_SOURCES,
    );
    expect(byId.pdf_discovery.sourceGroups?.entitled_access_sources).toEqual(
      [],
    );
    expect(
      byId.pdf_discovery.sourceGroups?.missing_entitled_access_sources,
    ).toEqual([]);
    expect(byId.pdf_discovery.sourceGroups?.scihub_sources).toEqual(["scihub"]);
    expect(byId.pdf_discovery.optionalKeys ?? []).toEqual([]);

    expect(byId.entitled_access).toEqual(
      expect.objectContaining({
        status: "unavailable",
        configured: [],
        missing: [],
        readiness: {
          state: "not_evaluated",
          code: "not_evaluated",
        },
      }),
    );
    expect(byId.entitled_access.reason).toMatch(/CARSI/i);
    expect(byId.entitled_access.requiredKeys ?? []).toEqual([]);

    for (const entry of profile.entries) {
      expect(entry.reason.length).toBeGreaterThan(0);
    }
  });

  it("uses publisher keys for metadata and OA only, never for entitled_access", () => {
    process.env.SEMANTIC_SCHOLAR_API_KEY = "semantic-key";
    process.env.EASYSCHOLAR_KEY = "easy-key";
    process.env.ELSEVIER_API_KEY = "elsevier-key";
    process.env.WOS_API_KEY = "wos-key";
    process.env.IEEE_API_KEY = "ieee-key";
    setUserConfigValue("SPRINGER_API_KEY", "springer-key");

    const profile = buildCapabilityProfile({
      carsiReadiness: {
        state: "disabled",
        code: "integration_disabled",
        message: "CARSI integration is disabled.",
        missing: [],
      },
    });
    const byId = Object.fromEntries(
      profile.entries.map((entry) => [entry.id, entry]),
    );

    expect(byId.body_snippet_search.status).toBe("available");
    expect(byId.journal_metrics.status).toBe("available");
    expect(byId.metadata_search.sourceGroups?.entitled_sources).toEqual([
      "webofscience",
      "sciencedirect",
      "springer",
      "scopus",
      "ieee"
    ]);
    expect(byId.pdf_discovery.sourceGroups?.open_access_sources).toEqual(
      expect.arrayContaining([
        "sciencedirect_open_access",
        "springer_open_access"
      ]),
    );
    expect(byId.pdf_discovery.sourceGroups?.entitled_access_sources).toEqual(
      [],
    );
    expect(
      byId.pdf_discovery.sourceGroups?.missing_entitled_access_sources,
    ).toEqual([]);
    expect(byId.entitled_access).toEqual(
      expect.objectContaining({
        status: "unavailable",
        configured: [],
        missing: [],
        readiness: {
          state: "disabled",
          code: "integration_disabled",
        },
      }),
    );
  });

  it.each<{
    readiness: EntitledAccessReadiness;
    status: "available" | "unavailable";
    configured: string[];
    missing: string[];
  }>([
    {
      readiness: {
        state: "disabled",
        code: "integration_disabled",
        message: "CARSI integration is disabled.",
        missing: [],
      },
      status: "unavailable",
      configured: [],
      missing: [],
    },
    {
      readiness: {
        state: "absent",
        code: "executable_missing",
        message: "CARSI executable was not found.",
        missing: ["carsi"],
      },
      status: "unavailable",
      configured: [],
      missing: ["carsi"],
    },
    {
      readiness: {
        state: "incompatible",
        code: "contract_mismatch",
        message: "CARSI MCP contract is incompatible.",
        missing: [],
      },
      status: "unavailable",
      configured: [],
      missing: [],
    },
    {
      readiness: {
        state: "available",
        code: "compatible",
        message: "CARSI MCP contract is compatible.",
        missing: [],
      },
      status: "available",
      configured: ["carsi"],
      missing: [],
    }
  ])(
    "maps CARSI $readiness.state readiness without changing PDF discovery availability",
    (scenario) => {
      const profile = buildCapabilityProfile({
        carsiReadiness: scenario.readiness,
      });
      const byId = Object.fromEntries(
        profile.entries.map((entry) => [entry.id, entry]),
      );

      expect(byId.pdf_discovery.status).toBe("available");
      expect(byId.pdf_discovery.sourceGroups?.entitled_access_sources).toEqual(
        scenario.configured,
      );
      expect(
        byId.pdf_discovery.sourceGroups?.missing_entitled_access_sources,
      ).toEqual(scenario.missing);
      expect(byId.entitled_access).toEqual(
        expect.objectContaining({
          status: scenario.status,
          configured: scenario.configured,
          missing: scenario.missing,
          readiness: {
            state: scenario.readiness.state,
            code: scenario.readiness.code,
          },
        }),
      );
    },
  );

  it("ignores a legacy Wiley token for every public capability", () => {
    process.env.WILEY_TDM_TOKEN = "legacy-token";

    const profile = buildCapabilityProfile();
    const serialized = JSON.stringify(profile);

    expect(serialized).not.toContain("wiley_tdm");
    expect(serialized).not.toContain("WILEY_TDM_TOKEN");
    expect(
      profile.entries.find((entry) => entry.id === "entitled_access")?.status,
    ).toBe("unavailable");
  });
});
