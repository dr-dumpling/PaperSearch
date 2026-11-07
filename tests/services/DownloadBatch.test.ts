import { tmpdir } from "node:os";
import { readFileSync, mkdirSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
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
  CarsiDownloadRequest,
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
  it("freezes the configured directory per batch and reads GUI edits for the next batch", async () => {
    const root = mkdtempSync(join(tmpdir(), "capsule-download-path-"));
    const oldFile = process.env.PAPER_SEARCH_CONFIG_FILE;
    const oldPath = process.env.DEFAULT_DOWNLOAD_PATH;
    const config = join(root, "config.json");
    const first = join(root, "first");
    const second = join(root, "second");
    const seen: string[] = [];
    try {
      process.env.PAPER_SEARCH_CONFIG_FILE = config;
      delete process.env.DEFAULT_DOWNLOAD_PATH;
      writeFileSync(config, JSON.stringify({ DEFAULT_DOWNLOAD_PATH: first }));
      const tiers = (): DownloadTier[] => [{ id: "fixture", stage: "unpaywall", run: async (context) => {
        seen.push(context.savePath);
        writeFileSync(config, JSON.stringify({ DEFAULT_DOWNLOAD_PATH: second }));
        return { status: "skipped", message: "fixture" };
      }}];
      await downloadBatch({} as any, { mode: "per_item", items: [{ doi: "10.1000/a" }, { doi: "10.1000/b" }] },
        undefined, () => {}, tiers);
      expect(seen).toHaveLength(2);
      expect(seen.every(path => path.startsWith(join(first, "papers")))).toBe(true);
      await downloadBatch({} as any, { mode: "per_item", items: [{ doi: "10.1000/c" }] },
        undefined, () => {}, tiers);
      expect(seen[2]).toContain(join(second, "papers"));
    } finally {
      if (oldFile === undefined) delete process.env.PAPER_SEARCH_CONFIG_FILE;
      else process.env.PAPER_SEARCH_CONFIG_FILE = oldFile;
      if (oldPath === undefined) delete process.env.DEFAULT_DOWNLOAD_PATH;
      else process.env.DEFAULT_DOWNLOAD_PATH = oldPath;
      rmSync(root, { recursive: true, force: true });
    }
  });

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
    // itself; item 3 is last, so the batch end is reported with final totals;
    // then the whole batch's outcome for the finished window.
    expect(updates).toEqual([
      expect.objectContaining({ done: 1, succeeded: 1, failed: 0, finished: false, current: "10.1000/oa" }),
      expect.objectContaining({ done: 3, succeeded: 2, failed: 1, finished: true }),
      expect.objectContaining({
        total: 3, done: 3, succeeded: 2, failed: 1, finished: true,
        results: expect.objectContaining({
          content: "main", main: 2, stopped: false,
          sources: [["开放获取", 1], ["机构订阅", 1]],
          failures: [{ cls: "unexplained", reason: "需要学校登录", doi: "10.1000/fail" }],
        }),
      }),
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
    // the window counts the whole batch: the open-access item has settled first
    expect(entitled.map((c) => [c.batch?.index, c.batch?.total, c.batch?.done, c.batch?.succeeded])).toEqual([
      [2, 3, 1, 1],
      [3, 3, 2, 2],
    ]);
    expect(entitled[0].savePath).toContain("/tmp/own/papers/");
    // Under five items the open-access stretch is not shown; the last entitled item ends the count.
    expect(updates).toEqual([
      expect.objectContaining({ total: 3, done: 3, succeeded: 2, failed: 1, finished: true }),
      expect.objectContaining({
        total: 3, done: 3, succeeded: 2, failed: 1, finished: true,
        results: expect.objectContaining({ main: 2, failures: [expect.objectContaining({ doi: "10.1000/fail" })] }),
      }),
    ]);
    expect(result).toEqual(
      expect.objectContaining({ mode: "two_phase", status: "partial", total: 3, succeeded: 2, failed: 1, entitledAccessItems: 2 }),
    );
    expect(result.items[0].attempts.map((a) => a.stage)).toEqual(["unpaywall", "entitled_access"]);
    expect(result.items[1].attempts.map((a) => a.stage)).toEqual(["unpaywall"]);
    expect(lines).toContain("[批量] 开放来源获取 1/3 篇；剩余 2 篇进入机构下载");
  });

  it("two_phase: five or more items show the window from the open-access stretch on", async () => {
    const entitled: DownloadTierContext[] = [];
    const updates: CarsiBatchUpdate[] = [];
    const tiers = (): DownloadTier[] => [
      {
        id: "oa",
        stage: "unpaywall",
        run: async (context) => context.doi?.includes("/oa")
          ? { status: "ok", verified: true, path: "/tmp/oa.pdf", message: "ok" }
          : { status: "skipped", message: "no oa" },
      },
      {
        id: "entitled_access",
        stage: "entitled_access",
        run: async (context) => {
          entitled.push(context);
          return context.doi === "10.1000/ok"
            ? { status: "ok", verified: true, path: "/tmp/ok.pdf", message: "ok" }
            : { status: "error", message: "failed", code: "login_required" };
        },
      },
    ];
    await downloadBatch(
      {} as never,
      { items: ["oa1", "ok", "oa2", "oa3", "fail", "oa4"].map((id) => ({ doi: `10.1000/${id}` })), savePath: "/tmp/out" },
      fakeBackend(updates),
      () => {},
      tiers,
    );
    expect(updates.slice(0, 6).map((u) => [u.done, u.total, u.succeeded, u.failed, u.finished, u.phase, u.channel])).toEqual([
      [1, 6, 1, 0, false, "开放获取：已查 1/6 篇，找到 1 篇", "开放获取"],
      [1, 6, 1, 0, false, "开放获取：已查 2/6 篇，找到 1 篇", "开放获取"],
      [2, 6, 2, 0, false, "开放获取：已查 3/6 篇，找到 2 篇", "开放获取"],
      [3, 6, 3, 0, false, "开放获取：已查 4/6 篇，找到 3 篇", "开放获取"],
      [3, 6, 3, 0, false, "开放获取：已查 5/6 篇，找到 3 篇", "开放获取"],
      [4, 6, 4, 0, false, "开放获取：已查 6/6 篇，找到 4 篇", "开放获取"],
    ]);
    // The school's stretch carries on from the four settled items.
    expect(entitled.map((c) => [c.batch?.index, c.batch?.total, c.batch?.done, c.batch?.succeeded])).toEqual([
      [5, 6, 4, 4],
      [6, 6, 5, 5],
    ]);
    expect(updates.slice(6)).toEqual([
      expect.objectContaining({ total: 6, done: 6, succeeded: 5, failed: 1, finished: true }),
      expect.objectContaining({ total: 6, done: 6, succeeded: 5, failed: 1, finished: true, results: expect.any(Object) }),
    ]);
  });

  it("two_phase with supplementary files: open-access items settle only after their files", async () => {
    const updates: CarsiBatchUpdate[] = [];
    const visits: Array<CarsiDownloadRequest["batch"]> = [];
    const backend: CarsiBackend = {
      ...fakeBackend(updates),
      downloadLegalDoi: async (request) => {
        visits.push(request.batch);
        return { kind: "attempt_error", identifier: request.identifier, code: "supplements_only", message: "", supplements: [] };
      },
    };
    const tiers = (): DownloadTier[] => [{ id: "oa", stage: "unpaywall",
      run: async () => ({ status: "ok", verified: true, path: "/tmp/oa.pdf", message: "ok" }) }];
    const result = await downloadBatch(
      {} as never,
      { content: "both", items: ["a", "b", "c", "d", "e"].map((id) => ({ doi: `10.1000/${id}` })), savePath: "/tmp/out" },
      backend,
      () => {},
      tiers,
    );
    expect(updates.slice(0, 5).map((u) => [u.done, u.total, u.phase])).toEqual([1, 2, 3, 4, 5].map((k) =>
      [0, 5, `开放获取：已查 ${k}/5 篇，找到 ${k} 篇`]));
    expect(visits).toEqual([0, 1, 2, 3, 4].map((done) =>
      expect.objectContaining({ id: result.batchId, index: done + 1, total: 5, done })));
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

  it("continues after a page budget timeout without treating the user as absent", async () => {
    const seen: DownloadTierContext[] = [];
    const tiers = (): DownloadTier[] => [{ id: "entitled_access", stage: "entitled_access", run: async (c) => {
      seen.push(c);
      return { status: "error", code: "browser_operation_timeout", message: "page budget" };
    } }];
    await downloadBatch({} as never, { items: [{ doi: "10.1000/a" }, { doi: "10.1000/b" }], mode: "entitled_only" },
      fakeBackend([]), () => {}, tiers);
    expect(seen).toHaveLength(2);
    expect(seen.every((c) => !c.shortUserWait)).toBe(true);
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

  it("stops the batch when the user presses 终止任务 in the progress window", async () => {
    for (const mode of ["entitled_only", "per_item"] as const) {
      const seen: string[] = [];
      const lines: string[] = [];
      const tiers = (): DownloadTier[] => [
        {
          id: "entitled_access",
          stage: "entitled_access",
          run: async (context) => {
            seen.push(context.doi ?? "");
            return context.doi === "10.1016/stop"
              ? { status: "error", message: "stopped", code: "batch_stopped" }
              : { status: "ok", verified: true, path: `/tmp/${context.doi}.pdf`, message: "ok" };
          },
        },
      ];
      const result = await downloadBatch(
        {} as never,
        { items: [{ doi: "10.1016/a" }, { doi: "10.1016/stop" }, { doi: "10.1016/c" }, { doi: "10.1016/d" }], mode },
        fakeBackend([]),
        (line) => lines.push(line),
        tiers,
      );
      expect(seen).toEqual(["10.1016/a", "10.1016/stop"]);
      expect(result).toEqual(expect.objectContaining({ total: 4, succeeded: 1, failed: 3 }));
      const codes = result.items.map((item) => item.attempts[item.attempts.length - 1]?.code);
      expect(codes).toEqual([undefined, "batch_stopped", "batch_stopped", "batch_stopped"]);
      expect(lines).toContain("[批量] 已在进度窗口终止任务，剩下的篇目不再下载");
    }
  });

  it("tells the finished window each failure's class and reason, the sources and the start", async () => {
    const updates: CarsiBatchUpdate[] = [];
    const before = Math.floor(Date.now() / 1000);
    const root = mkdtempSync(join(tmpdir(), "batch-summary-"));
    mkdirSync(join(root, "papers"));
    const tiers = (): DownloadTier[] => [
      {
        id: "api",
        stage: "publisher_api",
        run: async (context) => context.doi === "10.1000/api"
          ? { status: "ok", verified: true, path: "/tmp/api.pdf", message: "ok" }
          : { status: "skipped", message: "no key" },
      },
      {
        id: "entitled_access",
        stage: "entitled_access",
        run: async (context) => context.doi === "10.1000/denied"
          ? { status: "error", message: "denied", code: "entitlement_missing",
              supplements: [{ status: "saved", label: "", file: "/tmp/s1.docx" }] }
          : { status: "skipped", message: "Entitled access requires a valid DOI." },
      },
    ];
    await downloadBatch(
      {} as never,
      {
        mode: "per_item",
        items: [{ doi: "10.1000/denied", title: "A Denied Paper" }, { doi: "10.1000/api" }, { paperId: "pmid:123" }],
        savePath: root,
      },
      fakeBackend(updates),
      () => undefined,
      tiers,
    );
    rmSync(root, { recursive: true, force: true });
    const results = updates.at(-1)?.results;
    // The folder button opens every paper of the batch.
    expect(results).toEqual({
      content: "main", folder: join(root, "papers"), started: expect.any(Number), stopped: false,
      main: 1, supplements: 1, no_supplements: 0,
      sources: [["出版社 API", 1]],
      failures: [
        { cls: "no_access", reason: "学校没有订阅", title: "A Denied Paper", doi: "10.1000/denied", note: "附录 1 个已保存" },
        { cls: "unsupported", reason: "没有有效 DOI" },
      ],
      supplement_failures: [],  // main text only: no supplementary files to list
    });
    expect(results!.started).toBeGreaterThanOrEqual(before);
  });

  it("a batch stopped in the window says so in its finished card", async () => {
    const updates: CarsiBatchUpdate[] = [];
    const tiers = (): DownloadTier[] => [{
      id: "entitled_access",
      stage: "entitled_access",
      run: async () => ({ status: "error", message: "stopped", code: "batch_stopped" }),
    }];
    await downloadBatch(
      {} as never,
      { mode: "per_item", items: [{ doi: "10.1000/a" }, { doi: "10.1000/b" }] },
      fakeBackend(updates),
      () => undefined,
      tiers,
    );
    expect(updates.at(-1)?.results).toEqual(expect.objectContaining({
      stopped: true,
      failures: [
        { cls: "user_or_external", reason: "任务已终止", doi: "10.1000/a" },
        { cls: "user_or_external", reason: "任务已终止", doi: "10.1000/b" },
      ],
    }));
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
    expect(declared).toEqual({ downloadFields: true, progressTool: true, supplementsField: false, userWaitField: false, diagnosticsDirField: false });
    const plain = selectCarsiBatchSupport(
      [{ name: "carsi_download", inputSchema: { type: "object", properties: base } }],
      "legal_only",
    );
    expect(plain).toEqual({ downloadFields: false, progressTool: false, supplementsField: false, userWaitField: false, diagnosticsDirField: false });
    const waiting = selectCarsiBatchSupport(
      [{ name: "carsi_download", inputSchema: { type: "object", properties: { ...base, user_wait: { type: "string" } } } }],
      "legal_only",
    );
    expect(waiting.userWaitField).toBe(true);
    expect(createCarsiDownloadArguments("10.1000/x", "/tmp", "legal_only", undefined, undefined, "short")).toEqual(
      expect.objectContaining({ user_wait: "short" }),
    );
  });

  it("sends the finished window's summary only to a backend that declares it", () => {
    const download = { name: "carsi_download", inputSchema: { type: "object", properties: base } };
    expect(selectCarsiBatchSupport([download, progress], "legal_only").progressResults).toBeUndefined();
    const withResults = {
      ...progress,
      inputSchema: { ...progress.inputSchema, properties: { ...progress.inputSchema.properties, results: { type: "object" } } },
    };
    expect(selectCarsiBatchSupport([download, withResults], "legal_only").progressResults).toBe(true);
  });

  it("sends the open-access phase and channel only to a backend that declares them", () => {
    const download = { name: "carsi_download", inputSchema: { type: "object", properties: base } };
    expect(selectCarsiBatchSupport([download, progress], "legal_only").progressPhase).toBeUndefined();
    const withPhase = {
      ...progress,
      inputSchema: { ...progress.inputSchema, properties: { ...progress.inputSchema.properties,
        phase: { type: "string" }, channel: { type: "string" } } },
    };
    expect(selectCarsiBatchSupport([download, withPhase], "legal_only").progressPhase).toBe(true);
  });

  it("adds the batch fields to the download arguments", () => {
    expect(createCarsiDownloadArguments("10.1000/x", "/tmp", "legal_only", batch)).toEqual(
      expect.objectContaining({ batch_id: "b", batch_index: 1, batch_total: 2, batch_done: 0 }),
    );
    expect(Object.keys(createCarsiDownloadArguments("10.1000/x", "/tmp"))).not.toContain("batch_id");
  });
});
