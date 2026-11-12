import { describe, expect, it, jest } from "@jest/globals";
import {
  runLiveSmoke,
  summarizeLiveSmoke,
  type SmokeCase,
} from "../../src/core/liveSmoke.js";
import type { CapabilityProfile } from "../../src/management/capability-profile/index.js";
import type { EntitledAccessReadiness } from "../../src/management/capability-profile/schoolReadiness.js";

const capabilityProfile: CapabilityProfile = {
  ok: true,
  entries: [],
  summary: {} as CapabilityProfile["summary"],
};

describe("live smoke severity", () => {
  it("treats degraded checks as configured/enabled capability warnings, not command failure", () => {
    const cases: SmokeCase[] = [
      {
        name: "free metadata search (Crossref)",
        ok: true,
        severity: "critical",
        status: "passed",
        message: "Free metadata search returned a live response.",
      },
      {
        name: "Semantic Scholar snippet capability",
        ok: false,
        severity: "degraded",
        status: "failed",
        configured: true,
        message:
          "SEMANTIC_SCHOLAR_API_KEY is configured, but snippet search could not be verified: 401",
        remediation:
          "Run `paper-search config get SEMANTIC_SCHOLAR_API_KEY --pretty`.",
      },
    ];

    const result = summarizeLiveSmoke(cases, capabilityProfile);

    expect(result.ok).toBe(true);
    expect(result.exitCode).toBe(0);
    expect(result.failedCases).toEqual([]);
    expect(result.degradedCases).toHaveLength(1);
    expect(result.degradedCases[0]).toEqual(
      expect.objectContaining({
        configured: true,
        remediation: expect.stringContaining(
          "paper-search config get SEMANTIC_SCHOLAR_API_KEY",
        ),
      }),
    );
    expect(result.severityCounts.degraded).toBe(1);
  });

  it("fails the command only when a critical check fails", () => {
    const cases: SmokeCase[] = [
      {
        name: "free metadata search (Crossref)",
        ok: false,
        severity: "critical",
        status: "failed",
        message: "Free metadata search failed",
        remediation: "Check network/proxy settings.",
      },
    ];

    const result = summarizeLiveSmoke(cases, capabilityProfile);

    expect(result.ok).toBe(false);
    expect(result.exitCode).toBe(1);
    expect(result.failedCases).toHaveLength(1);
  });

  it("keeps Elsevier metadata smoke checks and removes the Wiley TDM downloader check", async () => {
    const callTool = jest.fn(async (tool: string) => ({
      ok: true,
      data: tool === "check_scihub_mirrors" ? [{ status: "Working" }] : [{}],
    }));

    const result = await runLiveSmoke({
      capabilityProfile,
      schoolReadiness: disabledReadiness(),
      hasConfig: (key) => key === "ELSEVIER_API_KEY",
      callTool,
    });
    const names = result.cases.map((item) => item.name);

    expect(names).toEqual(
      expect.arrayContaining(["ScienceDirect metadata", "Scopus metadata"]),
    );
    expect(names).not.toContain("Wiley TDM token");
    expect(callTool).toHaveBeenCalledWith(
      "search_sciencedirect",
      expect.any(Object),
    );
    expect(callTool).toHaveBeenCalledWith("search_scopus", expect.any(Object));
    expect(callTool.mock.calls.map((call) => call[0])).not.toContain(
      "download_paper",
    );
  });

  it.each<{
    readiness: EntitledAccessReadiness;
    status: "passed" | "failed" | "skipped";
    ok: boolean;
    severity: "degraded" | "skipped";
  }>([
    {
      readiness: disabledReadiness(),
      status: "skipped",
      ok: true,
      severity: "skipped",
    },
    {
      readiness: {
        state: "absent",
        code: "executable_missing",
        message: "School backend executable was not found.",
        missing: ["school"],
      },
      status: "failed",
      ok: false,
      severity: "degraded",
    },
    {
      readiness: {
        state: "incompatible",
        code: "missing_tool",
        message: "School backend contract is incompatible.",
        missing: [],
      },
      status: "failed",
      ok: false,
      severity: "degraded",
    },
    {
      readiness: {
        state: "available",
        code: "ready",
        message: "School backend is ready.",
        missing: [],
      },
      status: "passed",
      ok: true,
      severity: "degraded",
    },
  ])(
    "reports the school backend readiness state $readiness.state without invoking a download tool",
    async ({ readiness, status, ok, severity }) => {
      const callTool = jest.fn(async (tool: string) => ({
        ok: true,
        data: tool === "check_scihub_mirrors" ? [{ status: "Working" }] : [{}],
      }));

      const result = await runLiveSmoke({
        capabilityProfile,
        schoolReadiness: readiness,
        hasConfig: () => false,
        callTool,
      });
      const schoolCase = result.cases.find(
        (item) => item.name === "School backend entitled access readiness",
      );

      expect(schoolCase).toEqual(
        expect.objectContaining({
          ok,
          status,
          severity,
          data: { state: readiness.state, code: readiness.code },
        }),
      );
      expect(result.exitCode).toBe(0);
      const calledTools = callTool.mock.calls.map((call) => call[0]);
      for (const forbiddenTool of [
        "download_paper",
        "download_with_fallback",
        "school_download",
        "school_cache_clear",
      ]) {
        expect(calledTools).not.toContain(forbiddenTool);
      }
    },
  );
});

function disabledReadiness(): EntitledAccessReadiness {
  return {
    state: "disabled",
    code: "integration_disabled",
    message: "School backend integration is disabled.",
    missing: [],
  };
}
