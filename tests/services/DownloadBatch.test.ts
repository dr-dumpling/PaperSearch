import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "@jest/globals";
import { downloadBatch } from "../../src/capabilities/pdf-discovery/batch.js";
import type {
  DownloadTier,
  DownloadTierContext,
} from "../../src/capabilities/pdf-discovery/DownloadTier.js";
import type {
  CarsiBackend,
  CarsiBatchUpdate,
} from "../../src/capabilities/pdf-discovery/carsi/types.js";
import {
  createCarsiDownloadArguments,
  selectCarsiBatchSupport,
} from "../../src/capabilities/pdf-discovery/carsi/CarsiReadiness.js";

/** Item 1 finishes through open access; items 2 and 3 reach entitled access. */
function fakeTiers(contexts: DownloadTierContext[]): DownloadTier[] {
  return [
    {
      id: "oa",
      stage: "unpaywall",
      run: async (context) => {
        contexts.push(context);
        return context.doi === "10.1000/oa"
          ? { status: "ok", verified: true, path: "/tmp/oa.pdf", message: "ok" }
          : { status: "skipped", message: "no oa" };
      },
    },
    {
      id: "entitled_access",
      stage: "entitled_access",
      run: async (context) =>
        context.doi === "10.1000/ok"
          ? { status: "ok", verified: true, path: "/tmp/ok.pdf", message: "ok" }
          : { status: "error", message: "failed", code: "login_required" },
    },
  ];
}

function fakeBackend(updates: CarsiBatchUpdate[]): CarsiBackend {
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

describe("serial download batch", () => {
  it("per_item: passes each item its batch position and keeps the window's totals right", async () => {
    const contexts: DownloadTierContext[] = [];
    const updates: CarsiBatchUpdate[] = [];
    const lines: string[] = [];
    const result = await downloadBatch(
      {} as never,
      {
        items: [{ doi: "10.1000/oa" }, { doi: "10.1000/ok" }, { doi: "10.1000/fail" }],
        savePath: "/tmp/out",
        mode: "per_item",
      },
      fakeBackend(updates),
      (line) => lines.push(line),
      () => fakeTiers(contexts),
    );

    expect(contexts.map((c) => c.batch)).toEqual([
      expect.objectContaining({ index: 1, total: 3, done: 0, succeeded: 0, failed: 0 }),
      expect.objectContaining({ index: 2, total: 3, done: 1, succeeded: 1, failed: 0 }),
      expect.objectContaining({ index: 3, total: 3, done: 2, succeeded: 2, failed: 0 }),
    ]);
    expect(new Set(contexts.map((c) => c.batch?.id)).size).toBe(1);
    // item 1 never reached the backend; item 2 was recorded by the backend
    // itself; item 3 is last, so the batch end is reported with final totals.
    expect(updates).toEqual([
      expect.objectContaining({ done: 1, succeeded: 1, failed: 0, finished: false, current: "10.1000/oa" }),
      expect.objectContaining({ done: 3, succeeded: 2, failed: 1, finished: true }),
    ]);
    expect(result).toEqual(
      expect.objectContaining({ status: "partial", total: 3, succeeded: 2, failed: 1 }),
    );
    expect(result.items.map((item) => [item.index, item.status])).toEqual([
      [1, "ok"],
      [2, "ok"],
      [3, "error"],
    ]);
    expect(lines[0]).toMatch(/^\[批量\] 运行记录：/);
    expect(lines[1]).toBe("[批量] 第 1/3 篇：10.1000/oa");
    const ledger = readFileSync(join(result.runLog!, "items.jsonl"), "utf8").trim().split("\n").map((line) => JSON.parse(line));
    expect(ledger.map((item) => [item.index, item.status])).toEqual([[1, "ok"], [2, "ok"], [3, "error"]]);
    expect(ledger[2].stages.length).toBeGreaterThan(0);
    expect(lines.at(-1)).toBe(
      "[批量] 完成：成功 2，失败 1，共 3 篇。失败分类：原因不明 1；详情：paper-search failures --format text");
  });

  it("entitled_only: every item goes straight to entitled access, open stages never run", async () => {
    const order: string[] = [];
    const updates: CarsiBatchUpdate[] = [];
    const lines: string[] = [];
    const tiers = (): DownloadTier[] => [
      { id: "oa", stage: "unpaywall", run: async (context) => { order.push(`oa:${context.doi}`); return { status: "ok", verified: true, path: "/tmp/oa.pdf", message: "ok" }; } },
      {
        id: "entitled_access",
        stage: "entitled_access",
        run: async (context) => {
          order.push(`entitled:${context.doi}:${context.batch?.index}/${context.batch?.total}`);
          return context.doi === "10.1000/ok"
            ? { status: "ok", verified: true, path: "/tmp/ok.pdf", message: "ok" }
            : { status: "error", message: "failed", code: "login_required" };
        },
      },
    ];
    const result = await downloadBatch(
      {} as never,
      { items: [{ doi: "10.1000/ok" }, { doi: "10.1000/fail" }], mode: "entitled_only" },
      fakeBackend(updates),
      (line) => lines.push(line),
      tiers,
    );
    expect(order).toEqual(["entitled:10.1000/ok:1/2", "entitled:10.1000/fail:2/2"]);
    expect(result).toEqual(expect.objectContaining({ mode: "entitled_only", total: 2, succeeded: 1, failed: 1, entitledAccessItems: 2 }));
    expect(result.items.map((item) => item.attempts.map((a) => a.stage))).toEqual([["entitled_access"], ["entitled_access"]]);
    expect(lines).toContain("[批量] 跳过开放来源，2 篇直接进入机构下载");
  });

  it("two_phase: open stages for every item first, then entitled access for the rest", async () => {
    const order: string[] = [];
    const entitled: DownloadTierContext[] = [];
    const updates: CarsiBatchUpdate[] = [];
    const lines: string[] = [];
    const tiers = (): DownloadTier[] => [
      {
        id: "oa",
        stage: "unpaywall",
        run: async (context) => {
          order.push(`oa:${context.doi}`);
          expect(context.batch).toBeUndefined();
          return context.doi === "10.1000/oa"
            ? { status: "ok", verified: true, path: "/tmp/oa.pdf", message: "ok" }
            : { status: "skipped", message: "no oa" };
        },
      },
      {
        id: "entitled_access",
        stage: "entitled_access",
        run: async (context) => {
          order.push(`entitled:${context.doi}`);
          entitled.push(context);
          return context.doi === "10.1000/ok"
            ? { status: "ok", verified: true, path: "/tmp/ok.pdf", message: "ok" }
            : { status: "error", message: "failed", code: "login_required" };
        },
      },
    ];
    const result = await downloadBatch(
      {} as never,
      {
        items: [
          { doi: "10.1000/ok", savePath: "/tmp/own" },
          { doi: "10.1000/oa" },
          { doi: "10.1000/fail" },
        ],
        savePath: "/tmp/out",
      },
      fakeBackend(updates),
      (line) => lines.push(line),
      tiers,
    );
    expect(order).toEqual([
      "oa:10.1000/ok",
      "oa:10.1000/oa",
      "oa:10.1000/fail",
      "entitled:10.1000/ok",
      "entitled:10.1000/fail",
    ]);
    // the window counts the entitled stretch: 2 items
    expect(entitled.map((c) => [c.batch?.index, c.batch?.total, c.batch?.done, c.batch?.succeeded])).toEqual([
      [1, 2, 0, 0],
      [2, 2, 1, 1],
    ]);
    expect(entitled[0].savePath).toBe("/tmp/own");
    expect(updates).toEqual([
      expect.objectContaining({ total: 2, done: 2, succeeded: 1, failed: 1, finished: true }),
    ]);
    expect(result).toEqual(
      expect.objectContaining({ mode: "two_phase", status: "partial", total: 3, succeeded: 2, failed: 1, entitledAccessItems: 2 }),
    );
    expect(result.items[0].attempts.map((a) => a.stage)).toEqual(["unpaywall", "entitled_access"]);
    expect(result.items[1].attempts.map((a) => a.stage)).toEqual(["unpaywall"]);
    expect(lines).toContain("[批量] 开放来源获取 1/3 篇；剩余 2 篇进入机构下载");
  });

  it("after one article waited out on the user, later ones wait on them briefly", async () => {
    const seen: string[] = [];
    const lines: string[] = [];
    const tiers = (): DownloadTier[] => [
      {
        id: "entitled_access",
        stage: "entitled_access",
        run: async (context) => {
          seen.push(`${context.doi}${context.shortUserWait ? ":short" : ""}`);
          return context.doi === "10.1016/login"
            ? { status: "error", message: "waited", code: "login_timeout" }
            : { status: "ok", verified: true, path: `/tmp/${context.doi}.pdf`, message: "ok" };
        },
      },
    ];
    for (const mode of ["entitled_only", "per_item"] as const) {
      seen.length = 0;
      await downloadBatch(
        {} as never,
        { items: [{ doi: "10.1000/a" }, { doi: "10.1016/login" }, { doi: "10.1000/b" }, { doi: "10.1000/c" }], mode },
        fakeBackend([]),
        (line) => lines.push(line),
        tiers,
      );
      // in order, one after another; only the articles after the timeout wait briefly
      expect(seen).toEqual(["10.1000/a", "10.1016/login", "10.1000/b:short", "10.1000/c:short"]);
    }
    expect(lines.filter((line) => line.startsWith("[批量] 这一篇等你登录或验证已到时限")).length).toBe(2);
  });

  it("waits out the publisher's hourly limit and tries the same article again", async () => {
    const seen: string[] = [];
    const lines: string[] = [];
    const pauses: number[] = [];
    let limited = true;
    const tiers = (): DownloadTier[] => [
      {
        id: "entitled_access",
        stage: "entitled_access",
        run: async (context) => {
          seen.push(context.doi ?? "");
          if (context.doi === "10.1016/b" && limited) {
            limited = false;
            return { status: "error", message: "limit", code: "rate_limited", retryAfterSec: 120 };
          }
          return { status: "ok", verified: true, path: `/tmp/${context.doi}.pdf`, message: "ok" };
        },
      },
    ];
    const result = await downloadBatch(
      {} as never,
      { items: [{ doi: "10.1016/a" }, { doi: "10.1016/b" }, { doi: "10.1016/c" }], mode: "entitled_only" },
      fakeBackend([]),
      (line) => lines.push(line),
      tiers,
      async (ms) => {
        pauses.push(ms);
      },
    );
    expect(seen).toEqual(["10.1016/a", "10.1016/b", "10.1016/b", "10.1016/c"]);
    expect(pauses).toEqual([120_000]);
    expect(result).toEqual(expect.objectContaining({ status: "ok", succeeded: 3, failed: 0 }));
    expect(lines.some((line) => line.includes("继续这一篇"))).toBe(true);
  });

  it("goes on after a journal's site blocks the current network", async () => {
    for (const mode of ["entitled_only", "per_item"] as const) {
      const seen: string[] = [];
      const lines: string[] = [];
      const updates: CarsiBatchUpdate[] = [];
      const tiers = (): DownloadTier[] => [
        {
          id: "entitled_access",
          stage: "entitled_access",
          run: async (context) => {
            seen.push(context.doi ?? "");
            return context.doi === "10.1016/blocked"
              ? { status: "error", message: "blocked", code: "access_blocked" }
              : { status: "ok", verified: true, path: `/tmp/${context.doi}.pdf`, message: "ok" };
          },
        },
      ];
      const result = await downloadBatch(
        {} as never,
        { items: [{ doi: "10.1016/a" }, { doi: "10.1016/blocked" }, { doi: "10.1016/c" }, { doi: "10.1016/d" }], mode },
        fakeBackend(updates),
        (line) => lines.push(line),
        tiers,
      );
      // The batch goes on: the backend answers the blocked journal's later items itself.
      expect(seen).toEqual(["10.1016/a", "10.1016/blocked", "10.1016/c", "10.1016/d"]);
      expect(result).toEqual(expect.objectContaining({ total: 4, succeeded: 3, failed: 1 }));
      expect(lines.some((line) => line.startsWith("[批量] 出版社网站拦截了当前网络（10.1016/blocked）"))).toBe(true);
      expect(lines.some((line) => line.includes("整批停下"))).toBe(false);
    }
  });

  it("works without a backend progress method", async () => {
    const backend = fakeBackend([]);
    delete backend.reportBatchProgress;
    const result = await downloadBatch(
      {} as never,
      { items: [{ doi: "10.1000/oa" }] },
      backend,
      () => undefined,
      () => fakeTiers([]),
    );
    expect(result.status).toBe("ok");
  });
});

describe("backend batch support", () => {
  const batch = { id: "b", index: 1, total: 2, done: 0, succeeded: 0, failed: 0 };
  const base = {
    identifier: { type: "string" },
    output_dir: { type: "string" },
    scihub_enabled: { type: "boolean" },
    use_tor: { type: "boolean" },
    use_vpnsci: { type: "boolean" },
    bibtex: { type: "boolean" },
    strategy: { type: "string" },
  };
  const batchFields = {
    batch_id: { type: "string" },
    batch_index: { type: "integer" },
    batch_total: { type: "integer" },
    batch_done: { type: "integer" },
    batch_succeeded: { type: "integer" },
    batch_failed: { type: "integer" },
  };
  const progress = {
    name: "carsi_batch_progress",
    inputSchema: {
      type: "object",
      properties: {
        batch_id: { type: "string" },
        total: { type: "integer" },
        done: { type: "integer" },
        succeeded: { type: "integer" },
        failed: { type: "integer" },
        current: { type: "string" },
        finished: { type: "boolean" },
      },
    },
  };

  it("sends batch fields only to a backend that declares them", () => {
    const declared = selectCarsiBatchSupport(
      [
        { name: "carsi_download", inputSchema: { type: "object", properties: { ...base, ...batchFields } } },
        progress,
      ],
      "legal_only",
    );
    expect(declared).toEqual({ downloadFields: true, progressTool: true, supplementsField: false, userWaitField: false });
    const plain = selectCarsiBatchSupport(
      [{ name: "carsi_download", inputSchema: { type: "object", properties: base } }],
      "legal_only",
    );
    expect(plain).toEqual({ downloadFields: false, progressTool: false, supplementsField: false, userWaitField: false });
    const waiting = selectCarsiBatchSupport(
      [{ name: "carsi_download", inputSchema: { type: "object", properties: { ...base, user_wait: { type: "string" } } } }],
      "legal_only",
    );
    expect(waiting.userWaitField).toBe(true);
    expect(createCarsiDownloadArguments("10.1000/x", "/tmp", "legal_only", undefined, undefined, "short")).toEqual(
      expect.objectContaining({ user_wait: "short" }),
    );
  });

  it("adds the batch fields to the download arguments", () => {
    expect(createCarsiDownloadArguments("10.1000/x", "/tmp", "legal_only", batch)).toEqual(
      expect.objectContaining({ batch_id: "b", batch_index: 1, batch_total: 2, batch_done: 0 }),
    );
    expect(Object.keys(createCarsiDownloadArguments("10.1000/x", "/tmp"))).not.toContain("batch_id");
  });
});
