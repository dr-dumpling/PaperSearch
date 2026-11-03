import { describe, expect, it, jest } from "@jest/globals";
import type {
  CarsiBackend,
  CarsiInvocationOutcome,
  CarsiReadiness,
} from "../../src/capabilities/pdf-discovery/carsi/index.js";
import { resolveCarsiReadiness } from "../../src/management/capability-profile/carsiReadiness.js";

const unusedDownload: CarsiInvocationOutcome = {
  kind: "attempt_error",
  identifier: "",
  code: "not_called",
  message: "not called",
};

function backendWithReadiness(readiness: CarsiReadiness) {
  const probe = jest.fn(async () => readiness);
  const backend: CarsiBackend = {
    probe,
    downloadLegalDoi: jest.fn(async () => unusedDownload),
  };
  const createBackend = jest.fn(() => backend);
  return { backend, createBackend, probe };
}

describe("resolveCarsiReadiness", () => {
  it("returns a fixed disabled product state without creating or probing a backend", async () => {
    const { createBackend, probe } = backendWithReadiness({
      state: "available",
      code: "compatible",
      message: "CARSI MCP contract is compatible.",
      missing: [],
    });

    await expect(
      resolveCarsiReadiness(false, createBackend),
    ).resolves.toEqual({
      state: "disabled",
      code: "integration_disabled",
      message: "CARSI integration is disabled.",
      missing: [],
    });
    expect(createBackend).not.toHaveBeenCalled();
    expect(probe).not.toHaveBeenCalled();
  });

  it.each<CarsiReadiness>([
    {
      state: "available",
      code: "compatible",
      message: "CARSI MCP contract is compatible.",
      missing: [],
    },
    {
      state: "absent",
      code: "executable_missing",
      message: "CARSI executable was not found.",
      missing: ["carsi"],
    },
    {
      state: "incompatible",
      code: "contract_mismatch",
      message: "CARSI MCP contract is incompatible.",
      missing: [],
    },
  ])(
    "creates and probes exactly once, passing through $state unchanged",
    async (readiness) => {
      const { createBackend, probe } = backendWithReadiness(readiness);
      const signal = new AbortController().signal;

      await expect(
        resolveCarsiReadiness(true, createBackend, signal),
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
    const backend: CarsiBackend = {
      probe,
      downloadLegalDoi: jest.fn(async () => unusedDownload),
    };
    const createBackend = jest.fn(() => backend);

    await expect(resolveCarsiReadiness(true, createBackend)).rejects.toBe(
      failure,
    );
    expect(createBackend).toHaveBeenCalledTimes(1);
    expect(probe).toHaveBeenCalledTimes(1);
  });
});
