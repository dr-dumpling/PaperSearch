import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "@jest/globals";
import { SchoolMcpClient } from "../../src/capabilities/pdf-discovery/school/SchoolMcpClient.js";

const liveDescribe =
  process.env.PAPER_SEARCH_SCHOOL_LIVE_CONTRACT === "1"
    ? describe
    : describe.skip;

liveDescribe("School backend MCP adapter live contract", () => {
  let profileDir: string;

  beforeAll(() => {
    profileDir = mkdtempSync(
      join(tmpdir(), "paper-search-school-adapter-live-"),
    );
  });

  afterAll(() => {
    rmSync(profileDir, { recursive: true, force: true });
  });

  it("validates initialize and tools/list against the explicitly selected executable", async () => {
    const executable = process.env.PAPER_SEARCH_SCHOOL_LIVE_EXECUTABLE;
    if (!executable) {
      throw new Error(
        "PAPER_SEARCH_SCHOOL_LIVE_EXECUTABLE is required for the gated live contract test.",
      );
    }

    const readiness = await new SchoolMcpClient({
      command: executable,
      args: ["run"],
      profileDir,
    }).probe();

    const reportPath = process.env.PAPER_SEARCH_SCHOOL_LIVE_REPORT;
    if (reportPath) {
      mkdirSync(dirname(reportPath), { recursive: true });
      writeFileSync(
        reportPath,
        `${JSON.stringify(
          {
            packageVersion:
              process.env.PAPER_SEARCH_SCHOOL_LIVE_PACKAGE_VERSION ??
              "unknown",
            boundary: "initialize + tools/list only",
            readiness,
          },
          null,
          2,
        )}\n`,
      );
    }

    expect(readiness).toEqual({
      state: "available",
      code: "ready",
      message: "School backend MCP contract is compatible.",
      missing: [],
    });
  });
});
