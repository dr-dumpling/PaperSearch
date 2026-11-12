import { describe, expect, it, jest } from "@jest/globals";
import type {
  SchoolBackend,
  SchoolInvocationOutcome,
  SchoolReadiness,
} from "../../src/capabilities/pdf-discovery/school/index.js";
import { resolveSchoolReadiness } from "../../src/management/capability-profile/schoolReadiness.js";

const unusedDownload: SchoolInvocationOutcome = {
  kind: "attempt_error",
  identifier: "",
  code: "not_called",
  message: "not called",
};

function backendWithReadiness(readiness: SchoolReadiness) {
  const probe = jest.fn(async () => readiness);
  const backend: SchoolBackend = {
    probe,
    downloadLegalDoi: jest.fn(async () => unusedDownload),
  };
  const createBackend = jest.fn(() => backend);
  return { backend, createBackend, probe };
}

describe("resolveSchoolReadiness", () => {
  it("returns a fixed disabled product state without creating or probing a backend", async () => {
    const { createBackend, probe } = backendWithReadiness({
      state: "available",
      code: "compatible",
      message: "School backend MCP contract is compatible.",
      missing: [],
    });

    await expect(
      resolveSchoolReadiness(false, createBackend),
    ).resolves.toEqual({
      state: "disabled",
      code: "integration_disabled",
      message: "School backend integration is disabled.",
      missing: [],
    });
    expect(createBackend).not.toHaveBeenCalled();
    expect(probe).not.toHaveBeenCalled();
  });

  it.each<SchoolReadiness>([
    {
      state: "available",
      code: "compatible",
      message: "School backend MCP contract is compatible.",
      missing: [],
    },
    {
      state: "absent",
      code: "executable_missing",
      message: "School backend executable was not found.",
      missing: ["school"],
    },
    {
      state: "incompatible",
      code: "contract_mismatch",
      message: "School backend MCP contract is incompatible.",
      missing: [],
    },
  ])(
    "creates and probes exactly once, passing through $state unchanged",
    async (readiness) => {
      const { createBackend, probe } = backendWithReadiness(readiness);
      const signal = new AbortController().signal;

      await expect(
        resolveSchoolReadiness(true, createBackend, signal),
      ).resolves.toBe(readiness);
      expect(createBackend).toHaveBeenCalledTimes(1);
      expect(probe).toHaveBeenCalledTimes(1);
      expect(probe).toHaveBeenCalledWith(signal);
    },
  );

  it("does not catch or reclassify a probe exception", async () => {
    const failure = new Error("probe failed");
    const probe = jest.fn(async () => {
      throw failure;
    });
    const backend: SchoolBackend = {
      probe,
      downloadLegalDoi: jest.fn(async () => unusedDownload),
    };
    const createBackend = jest.fn(() => backend);

    await expect(resolveSchoolReadiness(true, createBackend)).rejects.toBe(
      failure,
    );
    expect(createBackend).toHaveBeenCalledTimes(1);
    expect(probe).toHaveBeenCalledTimes(1);
  });
});
