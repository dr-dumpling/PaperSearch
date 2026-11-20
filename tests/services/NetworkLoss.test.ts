import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "@jest/globals";
import { downloadBatch } from "../../src/capabilities/download/batch/batch.js";
import type { DownloadTier, DownloadTierContext, DownloadTierResult } from "../../src/capabilities/download/content/pdf/DownloadTier.js";
import { NETWORK_POLL_MS, networkSigns } from "../../src/capabilities/download/batch/networkLoss.js";
import type { SchoolBackend, SchoolBatchUpdate } from "../../src/infrastructure/school/index.js";

/**
 * A batch that loses the network waits for it and does the paper again (the Mac's Wi-Fi gone
 * for 100 s, 2026-11-17: 40 papers ended as "DOI 暂时查不到" in that time).
 */

const root = mkdtempSync(join(tmpdir(), "network-loss-"));
afterAll(() => rmSync(root, { recursive: true, force: true }));

const OK: DownloadTierResult = { status: "ok", verified: true, path: "/nonexistent/main.pdf", message: "ok" };
const LOST: DownloadTierResult = { status: "error", code: "network_unavailable", message: "连不上网络" };
const item = (context: DownloadTierContext) => context.doi!.split("/").pop()!;

function backendRecording(updates: SchoolBatchUpdate[]): SchoolBackend {
  return {
    probe: async () => ({ state: "available", code: "ready", message: "", missing: [] }),
    downloadLegalDoi: async () => {
      throw new Error("tiers are faked");
    },
    reportBatchProgress: async (update) => {
      updates.push(update);
      return true;
    },
  };
}

describe("a batch without network", () => {
  it("waits for the network, then does the papers it lost again, in both lanes", async () => {
    // The network is down from the start until the batch has looked at it once more.
    let down = true;
    const calls: string[] = [];
    const lines: string[] = [];
    const pauses: number[] = [];
    const updates: SchoolBatchUpdate[] = [];
    const tiers = (): DownloadTier[] => [
      { id: "oa", stage: "unpaywall", run: async (context) => {
        calls.push(`open:${item(context)}`);
        if (item(context) === "c") return { status: "skipped", message: "no oa" };
        return down ? { status: "error", message: "getaddrinfo ENOTFOUND api.unpaywall.org" } : OK;
      } },
      { id: "entitled_access", stage: "entitled_access", run: async (context) => {
        calls.push(`school:${item(context)}`);
        return down ? LOST : OK;
      } },
    ];
    const result = await downloadBatch({} as never,
      { items: ["a", "b", "c", "d", "e"].map((id) => ({ doi: `10.1000/${id}` })), savePath: root },
      backendRecording(updates), (line) => lines.push(line), tiers,
      async (ms) => {
        pauses.push(ms);
        if (ms === NETWORK_POLL_MS) down = false;
      },
      async () => !down);
    expect(result.items.map((paper) => paper.status)).toEqual(["ok", "ok", "ok", "ok", "ok"]);
    // The open lane did "a" again once the network was back, not sending it to the school.
    expect(calls.filter((call) => call === "open:a")).toHaveLength(2);
    expect(calls).not.toContain("school:a");
    expect(pauses).toContain(NETWORK_POLL_MS);
    expect(lines).toContain("[批量] 网络断了（doi.org 和 PubMed 都连不上）：等网络恢复后重下这一篇，后面的篇目也先等着");
    expect(lines.some((line) => /^\[批量\] 网络恢复了（断了约 \d+ 分钟），重下这一篇$/.test(line))).toBe(true);
    // The window said it while it waited.
    expect(updates.some((update) => update.phase === "网络断了，等网络恢复后接着下")).toBe(true);
  });

  it("does a paper the backend found without network again, though the network is back by then", async () => {
    let schoolCalls = 0;
    const lines: string[] = [];
    const tiers = (): DownloadTier[] => [
      { id: "entitled_access", stage: "entitled_access", run: async () => (schoolCalls += 1) === 1 ? LOST : OK },
    ];
    const result = await downloadBatch({} as never, { items: [{ doi: "10.1000/x" }], savePath: root, mode: "entitled_only" },
      undefined, (line) => lines.push(line), tiers, async () => {}, async () => true);
    expect(result.items[0].status).toBe("ok");
    expect(schoolCalls).toBe(2);
    expect(lines).toContain("[批量] 刚才网络断过（doi.org 和 PubMed 都没连上），重下这一篇");
  });

  it("leaves a site that cannot be reached while the network is up as it was", async () => {
    let openCalls = 0;
    let looked = 0;
    const tiers = (): DownloadTier[] => [
      { id: "oa", stage: "unpaywall", run: async () => {
        openCalls += 1;
        return { status: "error", message: "getaddrinfo ENOTFOUND export.arxiv.org" };
      } },
    ];
    const result = await downloadBatch({} as never, { items: [{ doi: "10.1000/y" }], savePath: root, mode: "per_item" },
      undefined, () => {}, tiers, async () => {}, async () => (looked += 1) > 0);
    expect(result.items[0].status).toBe("error");
    expect(openCalls).toBe(1);
    expect(looked).toBe(1);
  });

  it("gives a paper up after three goes when the network keeps failing it", async () => {
    let schoolCalls = 0;
    const tiers = (): DownloadTier[] => [
      { id: "entitled_access", stage: "entitled_access", run: async () => {
        schoolCalls += 1;
        return LOST;
      } },
    ];
    const result = await downloadBatch({} as never, { items: [{ doi: "10.1000/z" }], savePath: root, mode: "entitled_only" },
      undefined, () => {}, tiers, async () => {}, async () => true);
    expect(result.items[0].status).toBe("error");
    expect(result.items[0].attempts.at(-1)?.code).toBe("network_unavailable");
    expect(schoolCalls).toBe(4);
  });

  it("tells the backend's word and a stage's unreachable host apart", () => {
    expect(networkSigns({ status: "error", attempts: [{ stage: "entitled_access", status: "error", code: "network_unavailable", message: "" }] })).toBe("lost");
    expect(networkSigns({ status: "ok", attempts: [], supplements: [{ label: "", status: "failed", reason: "network_unavailable" }] })).toBe("lost");
    expect(networkSigns({ status: "error", attempts: [{ stage: "fulltext", status: "error", message: "PubMed Central did not answer: fetch failed" }] })).toBe("suspect");
    expect(networkSigns({ status: "error", attempts: [{ stage: "unpaywall", status: "error", message: "HTTP 403" }] })).toBeUndefined();
  });
});
