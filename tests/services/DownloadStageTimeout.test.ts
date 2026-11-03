import axios from "axios";
import { describe, expect, it, jest } from "@jest/globals";
import { downloadWithFallback } from "../../src/capabilities/pdf-discovery/OpenAccessFallbackService.js";
import { createRepositoryTier } from "../../src/capabilities/pdf-discovery/tiers/repositories.js";
import type { DownloadTier } from "../../src/capabilities/pdf-discovery/DownloadTier.js";

const never = () => new Promise<never>(() => undefined);

describe("download stage deadlines", () => {
  it("skips a stage that never answers and continues the funnel", async () => {
    const tiers: DownloadTier[] = [
      { id: "repositories", stage: "repositories", run: never },
      { id: "unpaywall", stage: "unpaywall", run: async () => ({ status: "ok", verified: true, path: "/tmp/x.pdf", message: "ok" }) },
    ];
    const result = await downloadWithFallback(
      {} as never,
      { source: "crossref", paperId: "10.1000/x", doi: "10.1000/x" },
      tiers,
      { stageTimeoutMs: 50 },
    );
    expect(result.status).toBe("ok");
    expect(result.attempts[0]).toEqual(
      expect.objectContaining({ stage: "repositories", status: "error", code: "stage_timeout" }),
    );
  });

  it("never applies the stage deadline to entitled access", async () => {
    const tiers: DownloadTier[] = [
      {
        id: "entitled_access",
        stage: "entitled_access",
        run: () => new Promise((resolve) => setTimeout(() => resolve({ status: "ok", verified: true, path: "/tmp/e.pdf", message: "ok" }), 120)),
      },
    ];
    const result = await downloadWithFallback(
      {} as never,
      { source: "crossref", paperId: "10.1000/x", doi: "10.1000/x" },
      tiers,
      { stageTimeoutMs: 20 },
    );
    expect(result.status).toBe("ok");
  });

  it("gives up on a hanging PubMed Central lookup within the request deadline", async () => {
    const get = jest.spyOn(globalThis, "fetch").mockImplementation(() => never());
    const started = Date.now();
    const result = await createRepositoryTier(30).run({
      searchers: {} as never,
      source: "crossref",
      paperId: "10.1000/x",
      doi: "10.1000/x",
      savePath: "/tmp",
      useEntitledAccess: false,
      useSciHub: false,
    });
    expect(result.status).toBe("error");
    expect(result.message).toContain("timed out");
    expect(Date.now() - started).toBeLessThan(2_000);
    get.mockRestore();
  });
});
