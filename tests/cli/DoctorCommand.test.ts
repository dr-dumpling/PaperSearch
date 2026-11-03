import { spawnSync } from "child_process";
import { mkdtempSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";

/** A temporary home: the CLI never writes the user's data or config directories
 * (doctor created ~/.local/share/paper-search-cli/carsi, 2026-11-02). */
function isolatedHome(dir: string): NodeJS.ProcessEnv {
  return { HOME: dir, XDG_DATA_HOME: join(dir, "data"), XDG_CONFIG_HOME: join(dir, "config") };
}

describe("doctor command", () => {
  let tempDir: string;

  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "paper-search-doctor-test-"));
  });

  afterEach(() => {
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("returns masked config, capability profile, and platform status", () => {
    const result = spawnSync(
      process.execPath,
      [
        join(process.cwd(), "node_modules/.bin/tsx"),
        "src/cli.ts",
        "doctor",
        "--pretty",
      ],
      {
        cwd: process.cwd(),
        env: {
          ...process.env,
          ...isolatedHome(tempDir),
          PAPER_SEARCH_CONFIG_FILE: join(tempDir, "config.json"),
          PAPER_SEARCH_HIDE_SETUP_HINT: "1",
          EASYSCHOLAR_KEY: "easy-secret",
          ELSEVIER_API_KEY: "elsevier-secret",
          PAPER_SEARCH_CARSI_ENABLED: "false",
          WILEY_TDM_TOKEN: "legacy-token-must-be-ignored",
        },
        encoding: "utf8",
      },
    );

    expect(result.status).toBe(0);
    const output = JSON.parse(result.stdout);
    expect(output.ok).toBe(true);
    expect(
      output.config.entries.find(
        (entry: any) => entry.key === "EASYSCHOLAR_KEY",
      ),
    ).toEqual(
      expect.objectContaining({ configured: true, value: "easy...cret" }),
    );
    expect(
      output.capabilityProfile.entries.find(
        (entry: any) => entry.id === "journal_metrics",
      ),
    ).toEqual(
      expect.objectContaining({
        status: "available",
        requiredKeys: ["EASYSCHOLAR_KEY"],
      }),
    );
    expect(
      output.config.entries.find(
        (entry: any) => entry.key === "WILEY_TDM_TOKEN",
      ),
    ).toBeUndefined();
    expect(
      output.capabilityProfile.entries.find(
        (entry: any) => entry.id === "metadata_search",
      ),
    ).toEqual(
      expect.objectContaining({
        configured: expect.arrayContaining(["sciencedirect", "scopus"]),
      }),
    );
    expect(
      output.capabilityProfile.entries.find(
        (entry: any) => entry.id === "entitled_access",
      ),
    ).toEqual(
      expect.objectContaining({
        status: "unavailable",
        configured: [],
        missing: [],
        readiness: {
          state: "disabled",
          code: "integration_disabled",
        },
        reason: expect.stringMatching(/CARSI/i),
      }),
    );
    expect(output.platformStatus.ok).toBe(true);
    expect(output.platformStatus.tool).toBe("get_platform_status");
  });

  it("renders text report without exposing raw secrets", () => {
    const result = spawnSync(
      process.execPath,
      [
        join(process.cwd(), "node_modules/.bin/tsx"),
        "src/cli.ts",
        "doctor",
        "--format",
        "text",
      ],
      {
        cwd: process.cwd(),
        env: {
          ...process.env,
          ...isolatedHome(tempDir),
          PAPER_SEARCH_CONFIG_FILE: join(tempDir, "config.json"),
          PAPER_SEARCH_HIDE_SETUP_HINT: "1",
          EASYSCHOLAR_KEY: "easy-secret",
          ELSEVIER_API_KEY: "elsevier-secret",
          PAPER_SEARCH_CARSI_ENABLED: "false",
        },
        encoding: "utf8",
      },
    );

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("PaperSearch Doctor");
    expect(result.stdout).toContain("EASYSCHOLAR_KEY: easy...cret");
    expect(result.stdout).toContain("journal_metrics: available");
    expect(result.stdout).toContain("entitled_access: unavailable");
    expect(result.stdout).toContain(
      "Readiness: disabled (integration_disabled)",
    );
    expect(result.stdout).toMatch(/CARSI/i);
    expect(result.stdout).not.toContain("easy-secret");
    expect(result.stdout).not.toContain("elsevier-secret");
  });

  it("reports enabled CARSI as absent without failing doctor when the executable is missing", () => {
    const emptyPath = join(tempDir, "empty-path");
    const result = spawnSync(
      process.execPath,
      [
        join(process.cwd(), "node_modules/.bin/tsx"),
        "src/cli.ts",
        "doctor",
        "--pretty",
      ],
      {
        cwd: process.cwd(),
        env: {
          ...process.env,
          ...isolatedHome(tempDir),
          PATH: emptyPath,
          PAPER_SEARCH_CONFIG_FILE: join(tempDir, "config.json"),
          PAPER_SEARCH_HIDE_SETUP_HINT: "1",
          PAPER_SEARCH_CARSI_ENABLED: "true",
        },
        encoding: "utf8",
      },
    );

    expect(result.status).toBe(0);
    const output = JSON.parse(result.stdout);
    expect(output.ok).toBe(true);
    expect(
      output.capabilityProfile.entries.find(
        (entry: any) => entry.id === "entitled_access",
      ),
    ).toEqual(
      expect.objectContaining({
        status: "unavailable",
        missing: ["carsi"],
        readiness: {
          state: "absent",
          code: "executable_missing",
        },
      }),
    );
  });
});
