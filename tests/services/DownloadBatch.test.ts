import { tmpdir } from "node:os";
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, expect, it } from "@jest/globals";
import { batchStopped, downloadBatch } from "../../src/capabilities/pdf-discovery/batch.js";
import type {
  DownloadTier,
  DownloadTierContext,
} from "../../src/capabilities/pdf-discovery/DownloadTier.js";
import type {
  SchoolBackend,
  SchoolBatchRequests,
  SchoolBatchUpdate,
  SchoolDownloadRequest,
} from "../../src/capabilities/pdf-discovery/school/types.js";
import {
  createSchoolDownloadArguments,
  selectSchoolBatchSupport,
} from "../../src/capabilities/pdf-discovery/school/SchoolReadiness.js";

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

function fakeBackend(updates: SchoolBatchUpdate[]): SchoolBackend {
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

describe("a publisher whose school login stops working mid-batch", () => {
  // Science, 2026-11-15: its session lapsed after 84 articles and every later one failed.
  const science = (n: number) => `10.1126/example.${n}`;
  const WAIT = "其他篇目已完成，等你回来点“登录并继续”";
  /** The window: it shows what is held; the user presses 登录并继续 (or 终止) once the batch waits. */
  const windowFor = (press: "resume" | "stop" | "none" | "early", supported = true) => {
    const updates: SchoolBatchUpdate[] = [];
    let asked: SchoolBatchRequests = { resume: [], stop: false };
    let pressed = false;
    const backend: SchoolBackend = {
      probe: async () => ({ state: "available", code: "ready", message: "", missing: [] }),
      downloadLegalDoi: async () => { throw new Error("tiers are faked"); },
      reportBatchProgress: async (update) => {
        updates.push(structuredClone(update));
        // "early": 登录并继续 as soon as the publisher is held, its other papers still downloading.
        if ((press === "early" ? !!update.held?.length : update.phase === WAIT) && !pressed && press !== "none") {
          pressed = true;
          asked = press === "stop" ? { resume: [], stop: true } : { resume: (update.held ?? []).map((h) => h.key), stop: false };
        }
        return true;
      },
      holdSupported: async () => supported,
      takeBatchRequests: () => {
        const taken = asked;
        asked = { resume: [], stop: false };
        return taken;
      },
    };
    return { backend, updates, pressed: () => pressed };
  };
  const tiersFor = (calls: string[], loginBack: () => boolean) => (): DownloadTier[] => [
    { id: "oa", stage: "unpaywall", run: async () => ({ status: "skipped", message: "none" }) },
    { id: "entitled_access", stage: "entitled_access", run: async (context) => {
      const doi = context.doi!;
      calls.push(doi);
      const lapsed = doi.startsWith("10.1126/") && Number(doi.split(".").pop()) >= 3 && !loginBack();
      if (lapsed) return { status: "error", code: "login_timeout", message: "stopped at the school's sign-in page",
        trace: { publisher: "Science", loginWaitPage: "school_login" } };
      return { status: "ok", verified: true, path: `/tmp/${doi.split("/")[1]}.pdf`, message: "saved",
        trace: { publisher: doi.startsWith("10.1126/") ? "Science" : "Wiley" } };
    } },
  ];
  const items = [1, 2, 3, 4, 5].map((n) => ({ doi: science(n) })).concat([{ doi: "10.1002/other.6" }, { doi: science(7) }]);

  it("holds its papers while the others go on, waits for 登录并继续, then gets them", async () => {
    const calls: string[] = [];
    const window = windowFor("resume");
    const lines: string[] = [];
    const result = await downloadBatch({} as never, { items, savePath: "/tmp/out" }, window.backend,
      (line) => { lines.push(line); }, tiersFor(calls, window.pressed), async () => {});
    // 3 stops at the school's sign-in page after 1 and 2 came through it: 4, 5 and 7 wait untried, the other publisher goes on.
    expect(calls).toEqual(["10.1126/example.1", "10.1126/example.2", "10.1126/example.3", "10.1002/other.6",
      "10.1126/example.3", "10.1126/example.4", "10.1126/example.5", "10.1126/example.7"]);
    // The window was told what waits, under the publisher's own name, then that nothing does.
    expect(window.updates.find((u) => u.held?.length)?.held).toEqual([{ key: "10.1126/", name: "Science", count: 1 }]);
    expect(window.updates.find((u) => u.phase === WAIT)?.held).toEqual([{ key: "10.1126/", name: "Science", count: 4 }]);
    // Only the held left: the window is told so (it says so collapsed too); going on ends it.
    expect(window.updates.find((u) => u.phase === WAIT)?.heldWait).toBe(true);
    expect(window.updates.filter((u) => u.held !== undefined).at(-1)?.heldWait).toBeUndefined();
    expect(window.updates.filter((u) => u.held !== undefined).at(-1)?.held).toEqual([]);
    expect(lines.some((line) => line.includes("已点“登录并继续”"))).toBe(true);
    expect(result.items.map((item) => item.status)).toEqual(["ok", "ok", "ok", "ok", "ok", "ok", "ok"]);
    expect(result.failed).toBe(0);
    expect(batchStopped(result)).toBe(false);
  });

  it("goes on with them as soon as the user presses 登录并继续, the other papers still downloading", async () => {
    const calls: string[] = [];
    const window = windowFor("early");
    const result = await downloadBatch({} as never, { items, savePath: "/tmp/out" }, window.backend,
      () => {}, tiersFor(calls, window.pressed), async () => {});
    // 3 is held; pressed then, it goes on right after the paper that was downloading: no wait at the end.
    expect(calls).toEqual(["10.1126/example.1", "10.1126/example.2", "10.1126/example.3", "10.1126/example.3",
      "10.1126/example.4", "10.1126/example.5", "10.1002/other.6", "10.1126/example.7"]);
    expect(window.updates.some((u) => u.phase === WAIT)).toBe(false);
    expect(result.items.map((item) => item.status)).toEqual(["ok", "ok", "ok", "ok", "ok", "ok", "ok"]);
  });

  it("ends them not tried, paused, when the user presses 终止 while it waits, not as papers without access", async () => {
    const calls: string[] = [];
    const window = windowFor("stop");
    const result = await downloadBatch({} as never, { items, savePath: "/tmp/out" }, window.backend,
      () => {}, tiersFor(calls, () => false), async () => {});
    expect(calls.filter((doi) => doi === "10.1126/example.7")).toEqual([]);
    expect(result.items.map((item) => item.status)).toEqual(["ok", "ok", "error", "error", "error", "ok", "error"]);
    for (const index of [2, 3, 4, 6]) {
      expect(result.items[index].attempts.at(-1)).toMatchObject({ stage: "entitled_access", code: "login_paused" });
    }
    expect(result.failureClasses).toEqual({ user_or_external: 4 });
    // 接着下 goes no further after it.
    expect(batchStopped(result)).toBe(true);
  });

  it("ends a batch stopped while a publisher is held once: its papers paused, the rest not reached", async () => {
    const calls: string[] = [];
    const lines: string[] = [];
    const tiers = (): DownloadTier[] => {
      const [open, school] = tiersFor(calls, () => false)();
      return [open, { ...school, run: async (context) => context.doi === "10.1002/other.6"
        ? { status: "error", code: "batch_stopped", message: "stopped in the window" } : school.run(context) }];
    };
    const result = await downloadBatch({} as never, { items, savePath: "/tmp/out" }, windowFor("none").backend,
      (line) => { lines.push(line); }, tiers, async () => {});
    expect(lines.filter((line) => line.includes("已在进度窗口终止任务"))).toHaveLength(1);
    for (const index of [2, 3, 4]) {
      expect(result.items[index].attempts.filter((attempt) => attempt.code === "login_paused")).toHaveLength(1);
    }
    expect(calls).not.toContain("10.1126/example.7");
    expect(result.items[6].attempts.at(-1)?.code).toBe("batch_stopped");
    expect(batchStopped(result)).toBe(true);
  });

  it("holds nothing for failures that never reached the school's own sign-in page", async () => {
    // Windows, 2026-11-15: Science stalled once on its sign-in redirect (login_not_reached) and
    // 152 papers waited 26 minutes for nothing. Only a wait that ran out on the school's sign-in
    // page counts, as the backend says; a backend that does not say holds nothing.
    const failures: Record<number, { code: string; page?: string }> = {
      2: { code: "login_not_reached", page: "publisher" }, 3: { code: "download_timeout" },
      4: { code: "login_timeout", page: "authentication_redirect" }, 5: { code: "captcha_required" },
      6: { code: "login_timeout" }, 7: { code: "login_timeout", page: "institution_chooser" },
    };
    const calls: string[] = [];
    const window = windowFor("none");
    const tiers = (): DownloadTier[] => [
      { id: "oa", stage: "unpaywall", run: async () => ({ status: "skipped", message: "none" }) },
      { id: "entitled_access", stage: "entitled_access", run: async (context) => {
        calls.push(context.doi!);
        const failure = failures[Number(context.doi!.split(".").pop())];
        return failure ? { status: "error", code: failure.code, message: failure.code,
          trace: { publisher: "Science", ...(failure.page ? { loginWaitPage: failure.page } : {}) } }
          : { status: "ok", verified: true, path: `/tmp/${context.doi!.split("/")[1]}.pdf`, message: "saved" };
      } },
    ];
    const result = await downloadBatch({} as never, { items: [1, 2, 3, 4, 5, 6, 7, 8].map((n) => ({ doi: science(n) })),
      savePath: "/tmp/out" }, window.backend, () => {}, tiers, async () => {});
    expect(calls).toHaveLength(8);
    expect(window.updates.some((u) => u.held?.length)).toBe(false);
    expect(result.items.map((item) => item.status)).toEqual(["ok", "error", "error", "error", "error", "error", "error", "ok"]);
  });

  it("holds nothing where the window cannot show it, nor a publisher whose papers never came through", async () => {
    const calls: string[] = [];
    const old = windowFor("none", false);
    const result = await downloadBatch({} as never, { items, savePath: "/tmp/out" }, old.backend,
      () => {}, tiersFor(calls, () => false), async () => {});
    expect(calls).toHaveLength(7);
    expect(result.items[6].attempts.at(-1)?.code).toBe("login_timeout");
    const never: string[] = [];
    const tiers = (): DownloadTier[] => [
      { id: "oa", stage: "unpaywall", run: async () => ({ status: "skipped", message: "none" }) },
      { id: "entitled_access", stage: "entitled_access", run: async (context) => {
        never.push(context.doi!);
        return { status: "error", code: "institution_federation_unavailable", message: "no route" };
      } },
    ];
    await downloadBatch({} as never, { items: [1, 2, 3, 4, 5].map((n) => ({ doi: science(n) })), savePath: "/tmp/out" },
      windowFor("none").backend, () => {}, tiers, async () => {});
    expect(never).toHaveLength(5);
  });
});

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
      expect(seen.every(path => dirname(path) === first)).toBe(true);
      await downloadBatch({} as any, { mode: "per_item", items: [{ doi: "10.1000/c" }] },
        undefined, () => {}, tiers);
      expect(dirname(seen[2])).toBe(second);
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
    const updates: SchoolBatchUpdate[] = [];
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
          sources: [["开放下载", 1], ["机构下载", 1]],
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
    expect(lines.at(-2)).toBe(
      "[批量] 完成：成功 2，失败 1，共 3 篇。失败分类：原因不明 1；详情：paper-search failures --format text");
    // What is left goes on with one word.
    expect(lines.at(-1)).toContain("“接着下”");
  });

  it("entitled_only: every item goes straight to entitled access, open stages never run", async () => {
    const order: string[] = [];
    const updates: SchoolBatchUpdate[] = [];
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

  it("two_phase: entitled access starts on the first item open access misses, while open access goes on", async () => {
    const order: string[] = [];
    const entitled: DownloadTierContext[] = [];
    const updates: SchoolBatchUpdate[] = [];
    const lines: string[] = [];
    let browserStarted!: () => void;
    const started = new Promise<void>((resolve) => { browserStarted = resolve; });
    const tiers = (): DownloadTier[] => [
      {
        id: "oa",
        stage: "unpaywall",
        run: async (context) => {
          order.push(`oa:${context.doi}`);
          expect(context.batch).toBeUndefined();
          // The second item's check waits for the browser: one lane after the other, it never would.
          if (context.doi === "10.1000/oa") await started;
          order.push(`oa-done:${context.doi}`);
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
          browserStarted();
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
    expect(order.indexOf("entitled:10.1000/ok")).toBeLessThan(order.indexOf("oa-done:10.1000/oa"));
    expect(order.filter((step) => step.startsWith("entitled:"))).toEqual(["entitled:10.1000/ok", "entitled:10.1000/fail"]);
    // The window counts the whole batch: what has settled when each paper starts.
    expect(entitled.map((c) => [c.batch?.index, c.batch?.total, c.batch?.done, c.batch?.succeeded])).toEqual([
      [1, 3, 0, 0],
      [3, 3, 2, 2],
    ]);
    expect(dirname(entitled[0].savePath!)).toBe("/tmp/own");
    // Under five items the open-access lane is not shown; the last entitled item ends the count.
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
    expect(lines).toContain("[批量] 开放来源没有找到 10.1000/ok，机构下载同时开始");
    expect(lines).toContain("[批量] 开放来源查完：获取 1/3 篇；2 篇转机构下载");
    const ledger = readFileSync(join(result.runLog!, "items.jsonl"), "utf8").trim().split("\n").map((line) => JSON.parse(line));
    expect(ledger.map((item) => item.index).sort()).toEqual([1, 2, 3]);
  });

  it("two_phase: five or more items show both lanes, the counts never going back", async () => {
    const entitled: DownloadTierContext[] = [];
    const updates: SchoolBatchUpdate[] = [];
    let openChecked!: () => void;
    const checkedAll = new Promise<void>((resolve) => { openChecked = resolve; });
    const backend: SchoolBackend = {
      ...fakeBackend(updates),
      reportBatchProgress: async (update) => {
        updates.push(update);
        if (update.phase?.includes("已查 6/6")) openChecked();
        return true;
      },
    };
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
          // The first school download lasts while open access checks every item.
          if (context.doi === "10.1000/ok") await checkedAll;
          return context.doi === "10.1000/ok"
            ? { status: "ok", verified: true, path: "/tmp/ok.pdf", message: "ok" }
            : { status: "error", message: "failed", code: "login_required" };
        },
      },
    ];
    await downloadBatch(
      {} as never,
      { items: ["oa1", "ok", "oa2", "oa3", "fail", "oa4"].map((id) => ({ doi: `10.1000/${id}` })), savePath: "/tmp/out" },
      backend,
      () => {},
      tiers,
    );
    expect(updates.slice(0, 6).map((u) => [u.done, u.total, u.succeeded, u.failed, u.finished, u.phase, u.channel, u.lanes])).toEqual([
      [1, 6, 1, 0, false, "开放下载：已查 1/6 篇，找到 1 篇", "开放下载", undefined],
      [1, 6, 1, 0, false, "开放下载：已查 2/6 篇，找到 1 篇", "开放下载", "开放下载 1 篇 · 机构下载 0 篇"],
      [2, 6, 2, 0, false, "开放下载：已查 3/6 篇，找到 2 篇", "开放下载", "开放下载 2 篇 · 机构下载 0 篇"],
      [3, 6, 3, 0, false, "开放下载：已查 4/6 篇，找到 3 篇", "开放下载", "开放下载 3 篇 · 机构下载 0 篇"],
      [3, 6, 3, 0, false, "开放下载：已查 5/6 篇，找到 3 篇", "开放下载", "开放下载 3 篇 · 机构下载 0 篇"],
      [4, 6, 4, 0, false, "开放下载：已查 6/6 篇，找到 4 篇", "开放下载", "开放下载 4 篇 · 机构下载 0 篇"],
    ]);
    // Between the school's papers the lanes line goes on; the last one ends the count.
    expect(updates.slice(6)).toEqual([
      expect.objectContaining({ total: 6, done: 5, succeeded: 5, failed: 0, finished: false, lanes: "开放下载 4 篇 · 机构下载 1 篇" }),
      expect.objectContaining({ total: 6, done: 6, succeeded: 5, failed: 1, finished: true }),
      expect.objectContaining({ total: 6, done: 6, succeeded: 5, failed: 1, finished: true, results: expect.any(Object) }),
    ]);
    expect(entitled.map((c) => [c.batch?.index, c.batch?.total, c.batch?.done, c.batch?.succeeded])).toEqual([
      [2, 6, 1, 1],
      [6, 6, 5, 5],
    ]);
  });

  it("two_phase with supplementary files: open-access items settle only after their files", async () => {
    const updates: SchoolBatchUpdate[] = [];
    const visits: Array<SchoolDownloadRequest["batch"]> = [];
    const backend: SchoolBackend = {
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
      [0, 5, `开放下载：已查 ${k}/5 篇，找到 ${k} 篇`]));
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

  it("keeps the publisher's session alive every ten minutes of a long hourly wait", async () => {
    // Wiley's institutional session lapsed after about half an hour without a request,
    // and the school's login had expired by then (Windows, 2026-11-12).
    const pauses: number[] = [];
    const events: string[] = [];
    let limited = true;
    const tiers = (): DownloadTier[] => [{
      id: "entitled_access",
      stage: "entitled_access",
      run: async (context) => {
        events.push(`run ${context.doi}`);
        if (limited) {
          limited = false;
          return { status: "error", message: "limit", code: "rate_limited", retryAfterSec: 1500 };
        }
        return { status: "ok", verified: true, path: `/tmp/${context.doi}.pdf`, message: "ok" };
      },
    }];
    const backend: SchoolBackend = {
      ...fakeBackend([]),
      keepSession: async () => {
        events.push("keep");
        return true;
      },
    };
    const result = await downloadBatch({} as never, { items: [{ doi: "10.1016/a" }], mode: "entitled_only" },
      backend, () => {}, tiers, async (ms) => {
        pauses.push(ms);
        events.push(`pause ${ms / 60_000}`);
      });
    expect(pauses).toEqual([600_000, 600_000, 300_000]);
    expect(events).toEqual(["run 10.1016/a", "pause 10", "keep", "pause 10", "keep", "pause 5", "run 10.1016/a"]);
    expect(result).toEqual(expect.objectContaining({ status: "ok", succeeded: 1 }));
  });

  it("goes on after a journal's site blocks the current network", async () => {
    for (const mode of ["entitled_only", "per_item"] as const) {
      const seen: string[] = [];
      const lines: string[] = [];
      const updates: SchoolBatchUpdate[] = [];
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
    const updates: SchoolBatchUpdate[] = [];
    const before = Math.floor(Date.now() / 1000);
    const root = mkdtempSync(join(tmpdir(), "batch-summary-"));
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
      content: "main", folder: root, started: expect.any(Number), stopped: false,
      main: 1, supplements: 1, no_supplements: 0,
      sources: [["开放下载", 1]],
      source_details: [["开放下载", "出版社 API 1"]],
      failures: [
        { cls: "no_access", reason: "学校没有订阅", title: "A Denied Paper", doi: "10.1000/denied", note: "附录 1 个已保存" },
        { cls: "unsupported", reason: "没有有效 DOI" },
      ],
      supplement_failures: [],  // main text only: no supplementary files to list
    });
    expect(results!.started).toBeGreaterThanOrEqual(before);
  });

  it("a batch stopped in the window says so in its finished card", async () => {
    const updates: SchoolBatchUpdate[] = [];
    const tiers = (): DownloadTier[] => [{
      id: "entitled_access",
      stage: "entitled_access",
      run: async () => ({ status: "error", message: "stopped", code: "batch_stopped" }),
    }];
    const lines: string[] = [];
    const result = await downloadBatch(
      {} as never,
      { mode: "per_item", items: [{ doi: "10.1000/a" }, { doi: "10.1000/b" }] },
      fakeBackend(updates),
      (line) => lines.push(line),
      tiers,
    );
    expect(result).toMatchObject({ failed: 2, stoppedItems: 2 });
    expect(lines.some((line) => line.startsWith("[批量] 完成：成功 0，失败 0，已终止 2，共 2 篇"))).toBe(true);
    // Left undone by the stop: counted apart, not listed as failed (user, 2026-11-16).
    expect(updates.at(-1)?.results).toEqual(expect.objectContaining({
      stopped: true,
      stopped_count: 2,
      failures: [],
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
    name: "school_batch_progress",
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
    const declared = selectSchoolBatchSupport(
      [
        { name: "school_download", inputSchema: { type: "object", properties: { ...base, ...batchFields } } },
        progress,
      ],
      "legal_only",
    );
    expect(declared).toEqual({ downloadFields: true, progressTool: true, supplementsField: false, userWaitField: false, diagnosticsDirField: false });
    const plain = selectSchoolBatchSupport(
      [{ name: "school_download", inputSchema: { type: "object", properties: base } }],
      "legal_only",
    );
    expect(plain).toEqual({ downloadFields: false, progressTool: false, supplementsField: false, userWaitField: false, diagnosticsDirField: false });
    const waiting = selectSchoolBatchSupport(
      [{ name: "school_download", inputSchema: { type: "object", properties: { ...base, user_wait: { type: "string" } } } }],
      "legal_only",
    );
    expect(waiting.userWaitField).toBe(true);
    expect(createSchoolDownloadArguments("10.1000/x", "/tmp", "legal_only", undefined, undefined, "short")).toEqual(
      expect.objectContaining({ user_wait: "short" }),
    );
  });

  it("sends the finished window's summary only to a backend that declares it", () => {
    const download = { name: "school_download", inputSchema: { type: "object", properties: base } };
    expect(selectSchoolBatchSupport([download, progress], "legal_only").progressResults).toBeUndefined();
    const withResults = {
      ...progress,
      inputSchema: { ...progress.inputSchema, properties: { ...progress.inputSchema.properties, results: { type: "object" } } },
    };
    expect(selectSchoolBatchSupport([download, withResults], "legal_only").progressResults).toBe(true);
  });

  it("sends the open-access phase and channel only to a backend that declares them", () => {
    const download = { name: "school_download", inputSchema: { type: "object", properties: base } };
    expect(selectSchoolBatchSupport([download, progress], "legal_only").progressPhase).toBeUndefined();
    const withPhase = {
      ...progress,
      inputSchema: { ...progress.inputSchema, properties: { ...progress.inputSchema.properties,
        phase: { type: "string" }, channel: { type: "string" } } },
    };
    expect(selectSchoolBatchSupport([download, withPhase], "legal_only").progressPhase).toBe(true);
  });

  it("sends the lanes line only to a backend that declares it", () => {
    const download = { name: "school_download", inputSchema: { type: "object", properties: base } };
    expect(selectSchoolBatchSupport([download, progress], "legal_only").progressLanes).toBeUndefined();
    const withLanes = {
      ...progress,
      inputSchema: { ...progress.inputSchema, properties: { ...progress.inputSchema.properties, lanes: { type: "string" } } },
    };
    expect(selectSchoolBatchSupport([download, withLanes], "legal_only").progressLanes).toBe(true);
  });

  it("says only the held publishers are left only to a backend that declares it", () => {
    const download = { name: "school_download", inputSchema: { type: "object", properties: base } };
    const withHeld = (extra: Record<string, unknown>) => ({ ...progress, inputSchema: { ...progress.inputSchema,
      properties: { ...progress.inputSchema.properties, held: { type: "array" }, ...extra } } });
    expect(selectSchoolBatchSupport([download, withHeld({})], "legal_only")).toMatchObject({ progressHeld: true });
    expect(selectSchoolBatchSupport([download, withHeld({})], "legal_only").progressHeldWait).toBeUndefined();
    expect(selectSchoolBatchSupport([download, withHeld({ held_wait: { type: "boolean" } })], "legal_only").progressHeldWait)
      .toBe(true);
  });

  it("adds the batch fields to the download arguments", () => {
    expect(createSchoolDownloadArguments("10.1000/x", "/tmp", "legal_only", batch)).toEqual(
      expect.objectContaining({ batch_id: "b", batch_index: 1, batch_total: 2, batch_done: 0 }),
    );
    expect(Object.keys(createSchoolDownloadArguments("10.1000/x", "/tmp"))).not.toContain("batch_id");
  });
});
