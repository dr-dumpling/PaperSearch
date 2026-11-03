import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";
import { CONFIG_KEYS } from "../../src/config/ConfigService.js";
import { TOOLS } from "../../src/core/tools.js";
import { buildCapabilityProfile } from "../../src/management/capability-profile/index.js";

const LOCAL_AUTHORIZED_IMPLEMENTATION_PATHS = [
  "src/capabilities/pdf-discovery/institutional-access",
  "src/infrastructure/browser",
  "src/management/institutional-access",
  "sidecar/cloakbrowser",
];

const PUBLISHER_METADATA_KEYS = [
  "WOS_API_KEY",
  "ELSEVIER_API_KEY",
  "SPRINGER_API_KEY",
  "SPRINGER_OPENACCESS_API_KEY",
  "IEEE_API_KEY",
];

function listFilesRecursively(root: string): string[] {
  if (!existsSync(root)) return [];
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const filePath = join(root, entry.name);
    return entry.isDirectory() ? listFilesRecursively(filePath) : [filePath];
  });
}

describe("authorized PDF retrieval boundary", () => {
  const originalEnv = { ...process.env };
  let tempDir: string;

  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "paper-search-authorized-boundary-"));
    process.env = {
      ...originalEnv,
      PAPER_SEARCH_CONFIG_FILE: join(tempDir, "config.json"),
    };
    for (const key of [...PUBLISHER_METADATA_KEYS, "WILEY_TDM_TOKEN"]) {
      delete process.env[key];
    }
  });

  afterEach(() => {
    process.env = { ...originalEnv };
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("does not ship the removed native authorized-download implementation", () => {
    for (const relativePath of LOCAL_AUTHORIZED_IMPLEMENTATION_PATHS) {
      expect(listFilesRecursively(join(process.cwd(), relativePath))).toEqual(
        [],
      );
    }
  });

  it("does not expose a native publisher token or backend-selection knobs", () => {
    expect(CONFIG_KEYS).not.toContain("WILEY_TDM_TOKEN");
    expect(CONFIG_KEYS).toContain("ELSEVIER_API_KEY");
    expect(CONFIG_KEYS.filter((key) => key.includes("CARSI"))).toEqual([
      "PAPER_SEARCH_CARSI_ENABLED",
      "PAPER_SEARCH_CARSI_EXECUTABLE",
    ]);

    expect(TOOLS.map((tool) => tool.name)).not.toContain("search_wiley");
    const tool = TOOLS.find((item) => item.name === "download_with_fallback");
    expect(tool).toBeDefined();
    expect(Object.keys(tool!.inputSchema.properties || {})).toEqual([
      "source",
      "paperId",
      "doi",
      "title",
      "savePath",
      "useEntitledAccess",
      "useSciHub",
      "content",
      "batch",
    ]);
    for (const knob of [
      "institutional_access",
      "enableInstitutionalAccess",
      "institutionalProvider",
      "authorizedBackend",
      "carsi",
    ]) {
      expect(tool!.inputSchema.properties).not.toHaveProperty(knob);
    }
  });

  it("does not claim a CARSI readiness state without an injected snapshot", () => {
    const profile = buildCapabilityProfile();
    const entitled = profile.entries.find(
      (entry) => entry.id === "entitled_access",
    );

    expect(entitled).toEqual(
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
    expect(entitled?.reason).toMatch(/CARSI/i);
  });

  it("does not let publisher metadata keys masquerade as authorized PDF access", () => {
    for (const key of PUBLISHER_METADATA_KEYS) {
      process.env[key] = `test-${key.toLowerCase()}`;
    }

    const profile = buildCapabilityProfile();
    const metadata = profile.entries.find(
      (entry) => entry.id === "metadata_search",
    );
    const pdfDiscovery = profile.entries.find(
      (entry) => entry.id === "pdf_discovery",
    );
    const entitled = profile.entries.find(
      (entry) => entry.id === "entitled_access",
    );

    expect(metadata?.configured).toEqual(
      expect.arrayContaining([
        "webofscience",
        "sciencedirect",
        "springer",
        "scopus",
        "ieee",
      ]),
    );
    expect(pdfDiscovery?.sourceGroups?.entitled_access_sources).toEqual([]);
    expect(entitled).toEqual(
      expect.objectContaining({
        status: "unavailable",
        configured: [],
      }),
    );
  });

  it("keeps concrete CARSI MCP implementation imports behind the stable port", () => {
    const srcRoot = join(process.cwd(), "src");
    const adapterRoot = join(
      srcRoot,
      "capabilities",
      "pdf-discovery",
      "carsi",
    );
    const forbiddenImport =
      /from\s+["'][^"']*\/(?<!management\/)carsi\/(?!index\.js["'])[^"']+["']/;

    for (const filePath of listFilesRecursively(srcRoot)) {
      if (!filePath.endsWith(".ts") || filePath.startsWith(`${adapterRoot}/`))
        continue;
      expect(readFileSync(filePath, "utf8")).not.toMatch(forbiddenImport);
    }
  });
});
