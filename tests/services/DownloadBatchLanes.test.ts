import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "@jest/globals";
import { downloadBatch, type DownloadBatchResult } from "../../src/capabilities/pdf-discovery/batch.js";
import type { DownloadTier, DownloadTierContext, DownloadTierResult } from "../../src/capabilities/pdf-discovery/DownloadTier.js";
import type { CarsiBackend, CarsiBatchPaper, CarsiBatchPapers, CarsiBatchUpdate } from "../../src/capabilities/pdf-discovery/carsi/types.js";

/**
 * two_phase runs two lanes at once: open access checks every item in turn and
 * each item it misses goes to the school's lane, one browser download at a time.
 * These tests hold the lanes to the rules they share (2026-11-09).
 */

const root = mkdtempSync(join(tmpdir(), "batch-lanes-"));
afterAll(() => rmSync(root, { recursive: true, force: true }));

const OK: DownloadTierResult = { status: "ok", verified: true, path: "/nonexistent/main.pdf", message: "ok" };
const STOP_NOTICE = "[批量] 已在进度窗口终止任务，剩下的篇目不再下载";

/** A seeded generator (mulberry32): a failing round is replayed from its seed. */
function seeded(seed: number): () => number {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function backendRecording(updates: CarsiBatchUpdate[]): CarsiBackend {
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

const itemNumber = (context: DownloadTierContext) => Number(context.doi!.split("/").pop());
const ledgerOf = (result: DownloadBatchResult) =>
  readFileSync(join(result.runLog!, "items.jsonl"), "utf8").trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));

type OpenPlan = "found" | "missed" | "throws";
type SchoolPlan = "ok" | "fails" | "throws" | "stops" | "limited";

describe("two lanes at once", () => {
  it("under random timings and outcomes: one result per item, one browser at a time, counts that never go back", async () => {
    for (let round = 1; round <= 300; round += 1) {
      const random = seeded(round);
      const pick = <T,>(choices: Array<[number, T]>): T => {
        const r = random();
        let sum = 0;
        for (const [weight, value] of choices) if (r < (sum += weight)) return value;
        return choices[choices.length - 1][1];
      };
      const total = 1 + Math.floor(random() * 14);
      const plan = Array.from({ length: total }, () => ({
        open: pick<OpenPlan>([[0.35, "found"], [0.55, "missed"], [0.1, "throws"]]),
        school: pick<SchoolPlan>([[0.45, "ok"], [0.33, "fails"], [0.08, "throws"], [0.08, "limited"], [0.06, "stops"]]),
      }));
      const jitter = async () => {
        for (let hop = Math.floor(random() * 4); hop > 0; hop -= 1) await Promise.resolve();
        if (random() < 0.25) await new Promise((resolve) => setTimeout(resolve, Math.floor(random() * 3)));
      };
      let active = 0;
      let mostAtOnce = 0;
      const schoolCalls: Array<{ item: number; batch: DownloadTierContext["batch"] }> = [];
      const limited = new Set<number>();
      const updates: CarsiBatchUpdate[] = [];
      const pauses: number[] = [];
      const lines: string[] = [];
      // The window's lists: a report may not get through while a download opens its backend.
      const listed: Array<CarsiBatchPapers & { delivered: boolean }> = [];
      const backend: CarsiBackend = {
        ...backendRecording(updates),
        reportBatchPapers: async (update) => {
          const delivered = active === 0 || random() < 0.5;
          listed.push({ ...structuredClone(update), delivered });
          return delivered;
        },
      };
      const tiers = (): DownloadTier[] => [
        {
          id: "oa",
          stage: "unpaywall",
          run: async (context) => {
            const item = itemNumber(context);
            await jitter();
            if (plan[item - 1].open === "throws") throw new Error("open tier broke");
            return plan[item - 1].open === "found" ? OK : { status: "skipped", message: "no oa" };
          },
        },
        {
          id: "entitled_access",
          stage: "entitled_access",
          run: async (context) => {
            const item = itemNumber(context);
            active += 1;
            mostAtOnce = Math.max(mostAtOnce, active);
            schoolCalls.push({ item, batch: context.batch });
            try {
              await jitter();
              const school = plan[item - 1].school;
              if (school === "throws") throw new Error("school tier broke");
              if (school === "stops") return { status: "error", code: "batch_stopped", message: "stopped" };
              if (school === "limited" && !limited.has(item)) {
                limited.add(item);
                return { status: "error", code: "rate_limited", retryAfterSec: 30, message: "hourly limit" };
              }
              return school === "ok" || school === "limited" ? OK : { status: "error", code: "login_required", message: "failed" };
            } finally {
              active -= 1;
            }
          },
        },
      ];
      const result = await downloadBatch(
        {} as never,
        { items: plan.map((_, offset) => ({ doi: `10.1000/${offset + 1}` })), savePath: root },
        backend,
        (line) => lines.push(line),
        tiers,
        async (ms) => {
          pauses.push(ms);
          await jitter();
        },
      );
      const context = `round ${round}: ${JSON.stringify(plan)}`;
      try {
        // Every item has one result, in its place, and one line in the run record.
        expect(result.items.map((item) => item.index)).toEqual(plan.map((_, offset) => offset + 1));
        expect(ledgerOf(result).map((line) => line.index).sort((a, b) => a - b)).toEqual(plan.map((_, offset) => offset + 1));
        expect(result.succeeded + result.failed).toBe(total);
        expect(result.succeeded).toBe(result.items.filter((item) => item.status === "ok").length);
        // One browser download at a time, for the missed items in the order missed, up to a stop.
        expect(mostAtOnce).toBeLessThanOrEqual(1);
        const school = schoolCalls.map((call) => call.item).filter((item, at, all) => item !== all[at - 1]);
        const missed = plan.flatMap((p, offset) => (p.open === "found" ? [] : [offset + 1]));
        const stopAt = school.findIndex((item) => plan[item - 1].school === "stops");
        expect(school).toEqual(missed.slice(0, stopAt < 0 ? missed.length : stopAt + 1));
        // The window's position for each download, and counts that never go back.
        for (const call of schoolCalls) {
          expect(call.batch!.index).toBe(call.batch!.done! + 1);
          expect(call.batch!.done!).toBeLessThan(total);
        }
        const dones = [...schoolCalls.map((call) => call.batch!.done!)];
        expect(dones).toEqual([...dones].sort((a, b) => a - b));
        const shown = updates.filter((update) => !update.finished).map((update) => update.done);
        expect(shown).toEqual([...shown].sort((a, b) => a - b));
        // What the two lanes got adds up to the window's 成功.
        for (const update of updates.filter((u) => u.lanes)) {
          const lanes = /^开放下载 (\d+) 篇 · 机构下载 (\d+) 篇$/.exec(update.lanes!);
          expect(lanes).not.toBeNull();
          expect(Number(lanes![1]) + Number(lanes![2])).toBe(update.succeeded);
        }
        expect(updates.every((update) => update.done <= update.total)).toBe(true);
        // The hourly limit paused the school's lane only, once per limited item reached.
        expect(pauses).toEqual(school.filter((item) => plan[item - 1].school === "limited").map(() => 30_000));
        // The lists: every paper once, then the ones that changed (again if not through);
        // a paper never goes back, and each ends as its result.
        expect(listed[0].papers.map((paper) => paper.index)).toEqual(plan.map((_, offset) => offset + 1));
        const rank = { open: 0, school: 1, ok: 2, failed: 2 };
        const merged = new Map<number, CarsiBatchPaper>();
        for (const report of listed.filter((sent) => sent.delivered)) {
          expect(report.folder).toBe(root);
          for (const paper of report.papers) {
            expect(rank[paper.state]).toBeGreaterThanOrEqual(rank[merged.get(paper.index)?.state ?? "open"]);
            merged.set(paper.index, paper);
          }
        }
        expect([...merged.values()].sort((a, b) => a.index - b.index).map((paper) => [paper.index, paper.state]))
          .toEqual(result.items.map((item) => [item.index, item.status === "ok" ? "ok" : "failed"]));
        for (const item of result.items.filter((it) => it.status === "ok")) {
          expect(merged.get(item.index)).toMatchObject({ via: item.attempts.some((a) => a.stage === "entitled_access" && a.status === "ok")
            ? "机构下载" : "开放下载", path: item.path });
        }
        // Each item ends as planned; after a stop, what neither lane reached says so.
        const stopped = stopAt >= 0;
        expect(lines.includes(STOP_NOTICE)).toBe(stopped);
        for (const [offset, item] of result.items.entries()) {
          const p = plan[offset];
          const reached = school.includes(offset + 1);
          if (p.open === "found" && item.attempts[0]?.stage === "unpaywall") expect(item.status).toBe("ok");
          else if (reached) expect(item.status).toBe(p.school === "ok" || p.school === "limited" ? "ok" : "error");
          else {
            expect(stopped).toBe(true);
            expect(item.attempts.at(-1)?.code).toBe("batch_stopped");
          }
        }
      } catch (error) {
        throw new Error(`${context}\n${(error as Error).message}`);
      }
    }
  });

  it("entitled_only and per_item send the window's lists too: waiting, then each paper as it ends", async () => {
    for (const mode of ["entitled_only", "per_item"] as const) {
      const listed: CarsiBatchPapers[] = [];
      const backend: CarsiBackend = {
        ...backendRecording([]),
        reportBatchPapers: async (update) => {
          listed.push(structuredClone(update));
          return true;
        },
      };
      const tiers = (): DownloadTier[] => [
        { id: "oa", stage: "unpaywall", run: async () => ({ status: "skipped", message: "no oa" }) },
        {
          id: "entitled_access",
          stage: "entitled_access",
          run: async (context) => itemNumber(context) === 2 ? { status: "error", code: "login_required", message: "failed" } : OK,
        },
      ];
      await downloadBatch({} as never, { items: [1, 2].map((n) => ({ doi: `10.1000/${n}` })), savePath: root, mode },
        backend, () => undefined, tiers);
      expect(listed[0].papers.map((paper) => [paper.index, paper.state])).toEqual(
        [[1, mode === "per_item" ? "open" : "school"], [2, mode === "per_item" ? "open" : "school"]]);
      const last = new Map(listed.flatMap((update) => update.papers).map((paper) => [paper.index, paper]));
      expect([...last.values()].map((paper) => [paper.index, paper.state, paper.via])).toEqual(
        [[1, "ok", "机构下载"], [2, "failed", undefined]]);
      expect(last.get(2)?.reason).toBeTruthy();
    }
  });

  it("a stop pressed during a school download ends both lanes", async () => {
    let stopped!: () => void;
    const afterStop = new Promise<void>((resolve) => { stopped = resolve; });
    const checked: number[] = [];
    const school: number[] = [];
    const lines: string[] = [];
    const tiers = (): DownloadTier[] => [
      {
        id: "oa",
        stage: "unpaywall",
        run: async (context) => {
          const item = itemNumber(context);
          checked.push(item);
          if (item === 2) await afterStop; // still checking when the user stops
          return item === 2 ? OK : { status: "skipped", message: "no oa" };
        },
      },
      {
        id: "entitled_access",
        stage: "entitled_access",
        run: async (context) => {
          school.push(itemNumber(context));
          stopped();
          return { status: "error", code: "batch_stopped", message: "stopped" };
        },
      },
    ];
    const result = await downloadBatch(
      {} as never,
      { items: [1, 2, 3, 4].map((n) => ({ doi: `10.1000/${n}` })), savePath: root },
      backendRecording([]),
      (line) => lines.push(line),
      tiers,
    );
    expect(school).toEqual([1]);
    expect(checked).toEqual([1, 2]); // no new check starts after the stop
    expect(result.items.map((item) => [item.status, item.attempts.at(-1)?.code])).toEqual([
      ["error", "batch_stopped"],
      ["ok", undefined],
      ["error", "batch_stopped"],
      ["error", "batch_stopped"],
    ]);
    expect(ledgerOf(result).map((line) => line.index).sort()).toEqual([1, 2, 3, 4]);
    expect(lines.filter((line) => line === STOP_NOTICE)).toHaveLength(1);
  });

  it("an error in one lane fails its item only; the other lane and the rest go on", async () => {
    const lines: string[] = [];
    const tiers = (): DownloadTier[] => [
      {
        id: "oa",
        stage: "unpaywall",
        run: async (context) => {
          if (itemNumber(context) === 1) throw new Error("open tier broke");
          return itemNumber(context) === 3 ? OK : { status: "skipped", message: "no oa" };
        },
      },
      {
        id: "entitled_access",
        stage: "entitled_access",
        run: async (context) => {
          if (itemNumber(context) === 2) throw new Error("school tier broke");
          return OK;
        },
      },
    ];
    const result = await downloadBatch(
      {} as never,
      { items: [1, 2, 3, 4].map((n) => ({ doi: `10.1000/${n}` })), savePath: root },
      backendRecording([]),
      (line) => lines.push(line),
      tiers,
    );
    // The open tier's error sends item 1 to the school, where it is saved.
    expect(result.items.map((item) => item.status)).toEqual(["ok", "error", "ok", "ok"]);
    expect(result.items[0].attempts.map((a) => [a.stage, a.code])).toEqual([["open_access", "stage_exception"], ["entitled_access", undefined]]);
    expect(result.items[1].attempts.at(-1)).toEqual(expect.objectContaining({
      stage: "entitled_access", code: "stage_exception", message: "Error: school tier broke" }));
    expect(lines).toContain("[批量] 开放来源出错（10.1000/1）：Error: open tier broke；这一篇转机构下载");
    expect(lines).toContain("[批量] 机构下载出错（10.1000/2）：Error: school tier broke");
    expect(ledgerOf(result)).toHaveLength(4);
  });
});
