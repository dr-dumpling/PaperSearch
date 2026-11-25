import { tmpdir } from "node:os";
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { describe, expect, it } from "@jest/globals";
import { BLOCKED_IN_ROW, BLOCKED_PAUSE_MS, batchStopped, downloadBatch } from "../../src/capabilities/download/batch/batch.js";
import { latestPapers } from "../../src/capabilities/download/batch/resume.js";
import { renderFailuresText, selectFailures, summarizeFailures } from "../../src/management/failures/index.js";
import type {
  DownloadTier,
  DownloadTierContext,
} from "../../src/capabilities/download/content/pdf/DownloadTier.js";
import type {
  SchoolBackend,
  SchoolBatchRequests,
  SchoolBatchUpdate,
  SchoolDownloadRequest,
  SchoolTurn,
} from "../../src/infrastructure/school/types.js";
import {
  createSchoolDownloadArguments,
  selectSchoolBatchSupport,
} from "../../src/infrastructure/school/SchoolReadiness.js";

/** `paper-search failures` on a batch's own run record. */
const failuresOf = (runLog: string | undefined) => summarizeFailures(dirname(runLog!), { run: basename(runLog!) });

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
    schoolSwitch: async () => ({ schools: [], group: false, retry: true }),
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
      schoolSwitch: async () => ({ schools: [], group: false, retry: true }),
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

  it("holds a publisher's journals of other DOI prefixes with it (Elsevier's 10.1053/ beside 10.1016/, 2026-11-17)", async () => {
    const calls: string[] = [];
    const window = windowFor("resume");
    // 10.1016/a.1 comes through the school; 10.1053/b.2 stops at its sign-in page: the rest of both wait.
    const tiers = (): DownloadTier[] => [
      { id: "oa", stage: "unpaywall", run: async () => ({ status: "skipped", message: "none" }) },
      { id: "entitled_access", stage: "entitled_access", run: async (context) => {
        const doi = context.doi!;
        calls.push(doi);
        if (doi === "10.1053/b.2" && !window.pressed()) return { status: "error", code: "login_timeout",
          message: "stopped at the school's sign-in page", trace: { publisher: "Elsevier", loginWaitPage: "school_login" } };
        return { status: "ok", verified: true, path: `/tmp/${doi.split("/")[1]}.pdf`, message: "saved", trace: { publisher: "Elsevier" } };
      } },
    ];
    const elsevier = [{ doi: "10.1016/a.1" }, { doi: "10.1053/b.2" }, { doi: "10.1016/a.3" }, { doi: "10.1053/b.4" }];
    const result = await downloadBatch({} as never, { items: elsevier, savePath: "/tmp/out" }, window.backend,
      () => {}, tiers, async () => {});
    // Nothing of Elsevier's was tried while it waited: both prefixes went on after 登录并继续.
    expect(calls).toEqual(["10.1016/a.1", "10.1053/b.2", "10.1053/b.2", "10.1016/a.3", "10.1053/b.4"]);
    expect(window.updates.find((u) => u.phase === WAIT)?.held).toEqual([{ key: "Elsevier", name: "Elsevier", count: 3 }]);
    expect(result.failed).toBe(0);
  });

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
    expect(window.updates.find((u) => u.held?.length)?.held).toEqual([{ key: "Science", name: "Science", count: 1 }]);
    expect(window.updates.find((u) => u.phase === WAIT)?.held).toEqual([{ key: "Science", name: "Science", count: 4 }]);
    // The window's ring holds them too, as waiting for the user (user, 2026-11-23).
    // Each by its DOI, for the window's 重试 list (user, 2026-11-24).
    expect(window.updates.find((u) => u.phase === WAIT)?.later).toEqual({ noAccess: 0, unexplained: 0, blocked: 0, login: 4,
      papers: { noAccess: [], unexplained: [], blocked: [],
        login: ["10.1126/example.3", "10.1126/example.4", "10.1126/example.5", "10.1126/example.7"] } });
    // Only the held left: the window is told so (it says so collapsed too); going on ends it.
    expect(window.updates.find((u) => u.phase === WAIT)?.heldWait).toBe(true);
    expect(window.updates.filter((u) => u.held !== undefined).at(-1)?.heldWait).toBeUndefined();
    expect(window.updates.filter((u) => u.held !== undefined).at(-1)?.held).toEqual([]);
    expect(lines.some((line) => line.includes("已点“登录并继续”"))).toBe(true);
    expect(result.items.map((item) => item.status)).toEqual(["ok", "ok", "ok", "ok", "ok", "ok", "ok"]);
    expect(result.failed).toBe(0);
    expect(batchStopped(result)).toBe(false);
  });

  it("fails the paper that held them when it stops at the sign-in page again after 登录并继续, the others going on", async () => {
    // Nature Digest in Springer Nature's list (Windows, 2026-11-24): a page no login passes held the publisher again
    // after each 登录并继续.
    const calls: string[] = [];
    const lines: string[] = [];
    const window = windowFor("resume");
    const [open, school] = tiersFor(calls, window.pressed)();
    const tiers = (): DownloadTier[] => [open, { ...school, run: async (context) => context.doi === science(3)
      ? (calls.push(context.doi), { status: "error", code: "login_timeout", message: "stopped at the school's sign-in page",
        trace: { publisher: "Science", loginWaitPage: "school_login" } })
      : school.run(context) }];
    const result = await downloadBatch({} as never, { items, savePath: "/tmp/out" }, window.backend,
      (line) => { lines.push(line); }, tiers, async () => {});
    expect(calls).toEqual(["10.1126/example.1", "10.1126/example.2", "10.1126/example.3", "10.1002/other.6",
      "10.1126/example.3", "10.1126/example.4", "10.1126/example.5", "10.1126/example.7"]);
    expect(window.updates.filter((u) => u.phase === WAIT)).toHaveLength(1);
    expect(lines.filter((line) => line.includes("这家出版社的篇目先暂停"))).toHaveLength(1);
    expect(lines.some((line) => line.includes("10.1126/example.3 点“登录并继续”后仍停在学校登录页"))).toBe(true);
    expect(result.items.map((item) => item.status)).toEqual(["ok", "ok", "error", "ok", "ok", "ok", "ok"]);
    expect(result.items[2].attempts.at(-1)).toMatchObject({ stage: "entitled_access", code: "login_timeout" });
    expect(result.failed).toBe(1);
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
    expect(result.failureClasses).toEqual({ external: 4 });
    // The run record says so too: `paper-search failures` counts the four as the batch does.
    expect(failuresOf(result.runLog)).toMatchObject({ failed: 4, notAttempted: 0,
      classes: { no_access: 0, user_side: 0, external: 4, unsupported: 0, unexplained: 0 } });
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

  it("holds the publisher's open-access papers too: their files wait for 登录并继续, or end not reached", async () => {
    for (const press of ["resume", "stop"] as const) {
      const calls: string[] = [];
      const window = windowFor(press);
      const visits: string[] = [];
      window.backend.downloadLegalDoi = async (request) => {
        visits.push(`${request.identifier}${window.pressed() ? " after" : ""}`);
        return { kind: "attempt_error", identifier: request.identifier, code: "supplements_only", message: "",
          supplements: [{ status: "saved", file: `${request.outputDir}/s.pdf`, label: "S1" }] };
      };
      const tiers = (): DownloadTier[] => {
        const [, school] = tiersFor(calls, window.pressed)();
        return [{ id: "oa", stage: "unpaywall", run: async (context) => context.doi === science(8)
          ? { status: "ok", verified: true, path: "/tmp/oa8.pdf", message: "ok" } : { status: "skipped", message: "none" } }, school];
      };
      const result = await downloadBatch({} as never, { items: [...items, { doi: science(8) }], savePath: "/tmp/out", content: "both" },
        window.backend, () => {}, tiers, async () => {});
      expect(window.updates.find((u) => u.phase === WAIT)?.held).toEqual([{ key: "Science", name: "Science", count: 5 }]);
      if (press === "resume") {
        expect(visits).toEqual(["10.1126/example.8 after"]);
        expect(result.items[7].supplements?.[0]?.label).toBe("S1");
      } else {
        expect(visits).toEqual([]);
        expect(result.items[7]).toMatchObject({ status: "ok", supplements: [{ status: "skipped", reason: "batch_stopped" }] });
        expect(result.items.filter((item) => item.attempts.at(-1)?.code === "login_paused")).toHaveLength(4);
      }
      // 接着下 goes no further after 终止, whatever its papers show.
      expect(result.stopped).toBe(press === "stop" ? true : undefined);
    }
  });

  it("holds nothing for failures that never reached the school's own sign-in page", async () => {
    // Windows, 2026-11-15: Science stalled once on its sign-in redirect (login_not_reached) and
    // 152 papers waited 26 minutes for nothing. Only a wait that ran out on the school's sign-in
    // page counts, as the backend says; a backend that does not say holds nothing.
    const failures: Record<number, { code: string; page?: string }> = {
      2: { code: "login_not_reached", page: "publisher" }, 3: { code: "download_timeout" },
      4: { code: "login_timeout", page: "authentication_redirect" }, 5: { code: "publisher_unreachable" },
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
    // 2 and 3 (原因不明) once more at the end (user, 2026-11-22); 5, its site not answering, once more at once (2026-11-24).
    expect(calls).toEqual([1, 2, 3, 4, 5, 5, 6, 7, 8, 2, 3].map(science));
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

describe("a publisher whose site blocks the batch (被网站拦截)", () => {
  // JAMA in the publisher sweep (Windows, 2026-11-23): after about ten papers jamanetwork.com answered with its crawl
  // prevention ("Validate User", a reCAPTCHA puzzle) until each paper's verification wait ran out, then the end's retry of
  // 原因不明 and the next school ran into it again; 21 of 28 papers went so. The user (2026-11-23): its papers wait while
  // the others go on, are tried once more after a while, and go neither to the end's retry nor to another school.
  const jama = (n: number) => `10.1001/jama.2025.${n}`;
  const wiley = (n: number) => `10.1002/other.${n}`;
  const PAUSED = /^被网站拦截，\d{2}:\d{2} 再试暂停的 (\d+) 篇$/;
  /** A clock the batch's pauses move on (none of the waits is real). */
  const clockFor = () => {
    let at = Date.parse("2026-11-23T00:52:00");
    const pauses: number[] = [];
    return { now: () => at, pause: async (ms: number) => { pauses.push(ms); at += ms; }, pauses, at: () => at };
  };
  /** The window; ``stopWhen`` presses 终止 on the first report it matches. */
  const windowFor = (schools: SchoolTurn[] = [], stopWhen?: (update: SchoolBatchUpdate) => boolean) => {
    const updates: SchoolBatchUpdate[] = [];
    let asked: SchoolBatchRequests = { resume: [], stop: false };
    const backend: SchoolBackend = {
      probe: async () => ({ state: "available", code: "ready", message: "", missing: [] }),
      downloadLegalDoi: async () => { throw new Error("tiers are faked"); },
      reportBatchProgress: async (update) => {
        updates.push(structuredClone(update));
        if (stopWhen?.(update)) asked = { resume: [], stop: true };
        return true;
      },
      holdSupported: async () => true,
      takeBatchRequests: () => {
        const taken = asked;
        asked = { resume: [], stop: false };
        return taken;
      },
      schoolSwitch: async () => ({ schools, group: false, retry: true }),
    };
    return { backend, updates };
  };
  /** Each paper's answer at each visit; the backend names JAMA's papers JAMA, as its records do. */
  const tiersFor = (calls: string[], answer: (doi: string, school?: string) => string) => (): DownloadTier[] => [
    { id: "oa", stage: "unpaywall", run: async () => ({ status: "skipped", message: "none" }) },
    { id: "entitled_access", stage: "entitled_access", run: async (context) => {
      const doi = context.doi!;
      calls.push(context.school ? `${doi}@${context.school}` : doi);
      const code = answer(doi, context.school);
      const trace = { publisher: doi.startsWith("10.1001/") ? "JAMA" : "Wiley",
        ...(code === "captcha_required" ? { state: "challenge_or_viewer_timeout" } : {}) };
      return code === "ok" ? { status: "ok", verified: true, path: `/tmp/${doi.split("/")[1]}.pdf`, message: "saved", trace }
        : { status: "error", code, message: code, trace };
    } },
  ];
  const codeOf = (item: { attempts: Array<{ stage: string; code?: string }> }) =>
    [...item.attempts].reverse().find((attempt) => attempt.stage === "entitled_access")?.code;

  // 失败后自动重试 off, the default (user, 2026-11-24): no pause, no retry; a blocked paper fails on its own, its publisher
  // given up after BLOCKED_IN_ROW in a row (Wiley's one verification not passed gave 40 papers up untried); 原因不明 failed
  // at once.
  for (const mode of ["entitled_only", "two_phase"] as const) {
    it(`without 失败后自动重试 fails a blocked paper alone and 原因不明 without a retry (${mode})`, async () => {
      const calls: string[] = [];
      const clock = clockFor();
      const window = windowFor();
      const backend = { ...window.backend, schoolSwitch: async () => ({ schools: [], group: false, retry: false }) };
      const lines: string[] = [];
      const items = [jama(1), jama(2), wiley(3), jama(4), wiley(5)].map((doi) => ({ doi }));
      const result = await downloadBatch({} as never, { items, savePath: "/tmp/out", mode }, backend,
        (line) => { lines.push(line); },
        tiersFor(calls, (doi) => doi === jama(2) ? "captcha_required" : doi === wiley(5) ? "download_failed" : "ok"),
        clock.pause, async () => true, clock.now);
      // JAMA's 4 tried after 2 was blocked; Wiley's 5 not tried again at the end; no pause.
      expect(calls).toEqual([jama(1), jama(2), wiley(3), jama(4), wiley(5)]);
      expect(clock.pauses.reduce((sum, ms) => sum + ms, 0)).toBeLessThan(5_000);
      expect(lines.some((line) => line.includes("已暂停"))).toBe(false);
      expect(result.items.map((item) => item.status)).toEqual(["ok", "error", "ok", "ok", "error"]);
      expect(result.items.map(codeOf)).toEqual([undefined, "captcha_required", undefined, undefined, "download_failed"]);
      expect(window.updates.some((u) => u.later && (u.later.blocked || u.later.unexplained))).toBe(false);
    });

    it(`without 失败后自动重试 gives a publisher up after ${BLOCKED_IN_ROW} papers blocked in a row (${mode})`, async () => {
      const calls: string[] = [];
      const clock = clockFor();
      const window = windowFor();
      const backend = { ...window.backend, schoolSwitch: async () => ({ schools: [], group: false, retry: false }) };
      // JAMA 2 blocked, 3 saved (the count starts again), then 4, 5 and 6 blocked: 7 and 8 not tried.
      const items = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => ({ doi: jama(n) }));
      const blockedOnes = new Set([jama(2), jama(4), jama(5), jama(6)]);
      const result = await downloadBatch({} as never, { items, savePath: "/tmp/out", mode }, backend, () => {},
        tiersFor(calls, (doi) => blockedOnes.has(doi) ? "captcha_required" : "ok"), clock.pause, async () => true, clock.now);
      expect(calls).toEqual([1, 2, 3, 4, 5, 6].map(jama));
      expect(result.items.map(codeOf)).toEqual([undefined, "captcha_required", undefined, "captcha_required", "captcha_required",
        "captcha_required", "blocked_paused", "blocked_paused"]);
    });
  }

  for (const mode of ["entitled_only", "two_phase"] as const) {
    it(`pauses the publisher's papers while the others go on, then tries them once more (${mode})`, async () => {
      const calls: string[] = [];
      const clock = clockFor();
      const window = windowFor();
      const lines: string[] = [];
      // The site lets papers through again within the pause.
      const clears = clock.at() + 5 * 60_000;
      const items = [jama(1), jama(2), wiley(3), jama(4), jama(5)].map((doi) => ({ doi }));
      const result = await downloadBatch({} as never, { items, savePath: "/tmp/out", mode }, window.backend,
        (line) => { lines.push(line); },
        tiersFor(calls, (doi) => doi === jama(2) && clock.now() < clears ? "captcha_required" : "ok"),
        clock.pause, async () => true, clock.now);
      // 4 and 5 not tried while JAMA waited; the other publisher went on; then 2, 4 and 5 once more.
      expect(calls).toEqual([jama(1), jama(2), wiley(3), jama(2), jama(4), jama(5)]);
      // The batch waited the pause, no more, with the window saying when they go on and how many wait.
      const waited = clock.pauses.reduce((sum, ms) => sum + ms, 0);
      expect(waited).toBeGreaterThanOrEqual(BLOCKED_PAUSE_MS);
      expect(waited).toBeLessThan(BLOCKED_PAUSE_MS + 5_000);
      expect(window.updates.filter((u) => PAUSED.test(u.phase ?? "")).at(-1)?.phase?.match(PAUSED)?.[1]).toBe("3");
      // The window's ring holds them with the time they go on, then lets them go before they are tried again.
      const paused = window.updates.map((u) => PAUSED.test(u.phase ?? "")).lastIndexOf(true);
      const until = window.updates[paused].later!;
      expect(until).toMatchObject({ blocked: 3, noAccess: 0, unexplained: 0, login: 0 });
      expect(new Date(until.blockedAt!).toTimeString().slice(0, 5)).toBe(window.updates[paused].phase!.match(/\d{2}:\d{2}/)![0]);
      expect(window.updates.slice(paused).some((u) => u.later?.blocked === 0 && u.later.blockedAt === undefined)).toBe(true);
      // No 登录并继续: nothing for the user to do.
      expect(window.updates.some((u) => u.held?.length || u.heldWait)).toBe(false);
      expect(lines.some((line) => line.startsWith("[批量] JAMA 的网站拦截了访问（10.1001/jama.2025.2"))).toBe(true);
      expect(lines).toContain("[批量] JAMA 已暂停 10 分钟：暂停的 3 篇再试一次");
      expect(result.items.map((item) => item.status)).toEqual(["ok", "ok", "ok", "ok", "ok"]);
      expect(result.failed).toBe(0);
      expect(batchStopped(result)).toBe(false);
    });
  }

  it("gives the publisher up when it blocks again after the pause: its other papers untried, none retried or sent to another school", async () => {
    const other = { name: "乙大学", entityId: "https://idp.b.example/idp" };
    const calls: string[] = [];
    const clock = clockFor();
    const window = windowFor([{ name: "甲大学", entityId: "https://idp.a.example/idp" }, other]);
    const lines: string[] = [];
    let blocking = false;
    const answer = (doi: string, school?: string) => {
      if (doi === wiley(6)) return "ok";
      if (blocking || doi === jama(3)) {
        blocking = true;
        return "captcha_required";
      }
      if (doi === jama(1)) return "download_failed";
      return school ? "ok" : "institution_not_registered";
    };
    const items = [jama(1), jama(2), jama(3), jama(4), jama(5), wiley(6)].map((doi) => ({ doi }));
    const result = await downloadBatch({} as never, { items, savePath: "/tmp/out", mode: "entitled_only" }, window.backend,
      (line) => { lines.push(line); }, tiersFor(calls, answer), clock.pause, async () => true, clock.now);
    // 3 blocked: JAMA waits, Wiley goes on; 3 once more, blocked again: 4 and 5 are not tried, 1 (原因不明) not retried,
    // 2 (没权限) not tried with the other school.
    expect(calls).toEqual([jama(1), jama(2), jama(3), wiley(6), jama(3)]);
    expect(result.items.map(codeOf)).toEqual(["download_failed", "institution_not_registered", "captcha_required",
      "blocked_paused", "blocked_paused", undefined]);
    expect(result.failureClasses).toEqual({ unexplained: 1, no_access: 1, external: 3 });
    expect(lines.some((line) => line.startsWith("[批量] JAMA 的网站暂停后仍拦截了访问（10.1001/jama.2025.3）"))).toBe(true);
    expect(lines.some((line) => line.includes("原因不明的") && line.includes("再试一次"))).toBe(false);
    expect(lines.some((line) => line.includes("换乙大学再试"))).toBe(false);
    // The finished card says 被网站拦截 for the three.
    const failures = window.updates.at(-1)?.results?.failures ?? [];
    expect(failures.filter((failure) => failure.reason === "被网站拦截")).toHaveLength(3);
    expect(failures.every((failure) => failure.cls !== "external" || failure.reason === "被网站拦截")).toBe(true);
  });

  it("records the papers it left untried in the run record, so `paper-search failures` counts them as the batch does (BMJ, 2026-11-23)", async () => {
    // The BMJ retest (run 20261123-105924-5a8d05): gut.bmj.com blocked the third paper (access_blocked), BMJ waited out
    // the pause, the paper came through once more, then heart.bmj.com's verification ran out (captcha_required) and BMJ
    // was given up. The batch's last line said 被网站拦截 48; `paper-search failures` 1, "另有 47 篇没有走到机构下载":
    // the 47 untried had "stages": [] in items.jsonl.
    const calls: string[] = [];
    const clock = clockFor();
    const lines: string[] = [];
    const [open, gut, blocked, heart, ...untried] = ["10.1136/bmjopen-2025-105429", "10.1136/gutjnl-2025-336719",
      "10.1136/gutjnl-2025-335449", "10.1136/heartjnl-2025-326402", "10.1136/thorax-2025-223539",
      "10.1136/jnnp-2025-336935", "10.1136/bjsports-2025-110889"];
    const tiers = (): DownloadTier[] => [
      { id: "entitled_access", stage: "entitled_access", run: async (context) => {
        const doi = context.doi!;
        calls.push(doi);
        const trace = { publisher: "BMJ" };
        if (doi === blocked && calls.length === 3) {
          return { status: "error", code: "access_blocked", message: "", trace: { ...trace, state: "publisher_access_blocked" } };
        }
        if (doi === heart) {
          return { status: "error", code: "captcha_required", message: "", trace: { ...trace, state: "challenge_or_viewer_timeout" } };
        }
        return { status: "ok", verified: true, path: `/tmp/${doi.split("/")[1]}.pdf`, message: "saved", trace };
      } },
    ];
    const result = await downloadBatch({} as never, { items: [open, gut, blocked, heart, ...untried].map((doi) => ({ doi })),
      savePath: "/tmp/out", mode: "entitled_only" }, windowFor().backend, (line) => { lines.push(line); }, tiers,
      clock.pause, async () => true, clock.now);
    expect(calls).toEqual([open, gut, blocked, blocked, heart]);
    expect(result.failureClasses).toEqual({ external: 4 });
    expect(lines.some((line) => line.includes("失败分类：外部原因 4（被网站拦截 4）"))).toBe(true);

    // The run record: each untried paper's school stage, as the batch gave it.
    const ledger = readFileSync(join(result.runLog!, "items.jsonl"), "utf8").trim().split("\n")
      .map((line) => JSON.parse(line) as { doi: string; stages: Array<Record<string, unknown>> });
    for (const doi of untried) {
      expect(ledger.find((item) => item.doi === doi)?.stages).toEqual([expect.objectContaining({
        stage: "entitled_access", status: "error", code: "blocked_paused", failureClass: "external", trace: { publisher: "BMJ" } })]);
    }
    expect(readFileSync(join(result.runLog!, "timeline.log"), "utf8"))
      .toContain(`${untried[0]} entitled_access error blocked_paused class=external`);
    // The batch folder's list (article_index.csv) takes its reason from there: 被网站拦截, no longer blank.
    expect(latestPapers([result.runLog!]).get(untried[0])?.reason).toBe("blocked_paused");

    // `paper-search failures`: the same four, all 被网站拦截, none "没有走到机构下载".
    const summary = failuresOf(result.runLog);
    expect(summary.failed).toBe(4);
    expect(summary.notAttempted).toBe(0);
    expect(summary.classes).toEqual({ no_access: 0, user_side: 0, external: 4, unsupported: 0, unexplained: 0 });
    expect(summary.groups.map((g) => [g.failureClass, g.publisher, g.code, g.count])).toEqual([
      ["external", "BMJ", "blocked_paused", 3],
      ["external", "BMJ", "captcha_required", 1],
    ]);
    const text = renderFailuresText(summary);
    expect(text).toContain("机构下载失败 4 篇");
    expect(text).not.toContain("没有走到机构下载");
    // The export keeps to the papers visited: the untried have nothing of their own to send.
    expect(selectFailures(dirname(result.runLog!), { run: basename(result.runLog!) }, { forExport: true }).papers
      .map((paper) => paper.doi)).toEqual([heart]);
  });

  it("pauses the publisher when a saved paper's files answer 429, too many requests (BMJ Open, 2026-11-23)", async () => {
    // bmjopen.bmj.com refused the eighth paper's files with HTTP 429; the next paper, on gut.bmj.com, met Cloudflare's
    // check that never cleared. Now BMJ's papers wait after the 429; the saved paper stands, its files 被网站拦截.
    const calls: string[] = [];
    const clock = clockFor();
    const lines: string[] = [];
    const bmj = ["10.1136/bmjopen-2025-105429", "10.1136/gutjnl-2025-336719", "10.1136/heartjnl-2025-326402"];
    const tiers = (): DownloadTier[] => [
      { id: "entitled_access", stage: "entitled_access", run: async (context) => {
        const doi = context.doi!;
        calls.push(doi);
        const publisher = doi.startsWith("10.1136/") ? "BMJ" : "Wiley";
        return { status: "ok", verified: true, path: `/tmp/${doi.split("/")[1]}.pdf`, message: "saved", trace: { publisher },
          ...(doi === bmj[0] && calls.length === 1
            ? { supplements: [{ status: "failed" as const, label: "Supplemental material[bmjopen-2025-105429supp001.pdf]", reason: "http_429" }] }
            : {}) };
      } },
    ];
    const result = await downloadBatch({} as never, { items: [...bmj, wiley(4)].map((doi) => ({ doi })), savePath: "/tmp/out",
      mode: "entitled_only", content: "both" }, windowFor().backend, (line) => { lines.push(line); }, tiers,
      clock.pause, async () => true, clock.now);
    // Wiley went on while BMJ's other two waited out the pause; then they came, once.
    expect(calls).toEqual([bmj[0], wiley(4), bmj[1], bmj[2]]);
    expect(clock.pauses.reduce((sum, ms) => sum + ms, 0)).toBeGreaterThanOrEqual(BLOCKED_PAUSE_MS);
    expect(lines.some((line) => line.startsWith("[批量] BMJ 的网站拦截了访问（10.1136/bmjopen-2025-105429 的附录：请求太多）"))).toBe(true);
    expect(result.items.map((item) => item.status)).toEqual(["ok", "ok", "ok", "ok"]);
  });

  it("gives the publisher up when the end's retry runs into its block: its other papers keep their result", async () => {
    const calls: string[] = [];
    const clock = clockFor();
    let visits = 0;
    const result = await downloadBatch({} as never, { items: [jama(1), jama(2)].map((doi) => ({ doi })), savePath: "/tmp/out",
      mode: "entitled_only" }, windowFor().backend, () => {},
      tiersFor(calls, () => (++visits > 2 ? "captcha_required" : "download_failed")), clock.pause, async () => true, clock.now);
    expect(calls).toEqual([jama(1), jama(2), jama(1)]);
    expect(result.items.map(codeOf)).toEqual(["captcha_required", "download_failed"]);
    expect(clock.pauses).toEqual([]);
  });

  it("ends the waiting papers paused, 被网站拦截, when the user presses 终止 during the pause", async () => {
    const calls: string[] = [];
    const clock = clockFor();
    // Pressed while the batch waits out the pause, both papers held.
    const window = windowFor([], (update) => PAUSED.exec(update.phase ?? "")?.[1] === "2");
    const result = await downloadBatch({} as never, { items: [jama(1), jama(2), jama(3)].map((doi) => ({ doi })),
      savePath: "/tmp/out", mode: "entitled_only" }, window.backend, () => {},
      tiersFor(calls, (doi) => (doi === jama(1) ? "ok" : "captcha_required")), clock.pause, async () => true, clock.now);
    expect(calls).toEqual([jama(1), jama(2)]);
    expect(result.items.map(codeOf)).toEqual([undefined, "blocked_paused", "blocked_paused"]);
    expect(result.stopped).toBe(true);
    expect(result.failureClasses).toEqual({ external: 2 });
    expect(failuresOf(result.runLog)).toMatchObject({ failed: 2, notAttempted: 0, classes: expect.objectContaining({ external: 2 }) });
    // The export keeps to the visits: 2's, blocked; 3 had none.
    expect(selectFailures(dirname(result.runLog!), { run: basename(result.runLog!) }, { forExport: true }).papers
      .map((paper) => [paper.doi, paper.code])).toEqual([[jama(2), "captcha_required"]]);
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
    // itself; item 3, 原因不明, is held for its try at the end, which the window
    // is told before it; then, last, the batch end is reported with final totals;
    // then the whole batch's outcome for the finished window.
    expect(updates).toEqual([
      expect.objectContaining({ done: 1, succeeded: 1, failed: 0, finished: false, current: "10.1000/oa" }),
      expect.objectContaining({ done: 2, succeeded: 2, failed: 0, finished: false,
        later: expect.objectContaining({ noAccess: 0, unexplained: 1, blocked: 0, login: 0 }) }),
      expect.objectContaining({ done: 3, succeeded: 2, failed: 1, finished: true }),
      expect.objectContaining({
        total: 3, done: 3, succeeded: 2, failed: 1, finished: true,
        results: expect.objectContaining({
          content: "main", main: 2, stopped: false,
          sources: [["开放下载", 1], ["机构下载", 1]],
          failures: [{ cls: "unexplained", reason: "没进入学校登录页", doi: "10.1000/fail" }],
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
      "[批量] 完成：成功 2，失败 1，共 3 篇。失败分类：原因不明 1（没进入学校登录页 1）；详情：paper-search failures --format text");
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
    // The failure (login_required, 原因不明) once more at the end, still the batch's second paper to finish.
    expect(order).toEqual(["entitled:10.1000/ok:1/2", "entitled:10.1000/fail:2/2", "entitled:10.1000/fail:2/2"]);
    expect(result).toEqual(expect.objectContaining({ mode: "entitled_only", total: 2, succeeded: 1, failed: 1, entitledAccessItems: 2 }));
    expect(result.items.map((item) => item.attempts.map((a) => a.stage))).toEqual([["entitled_access"], ["entitled_access", "entitled_access"]]);
    expect(lines).toContain("[批量] 跳过开放来源，2 篇直接进入机构下载");
    expect(lines).toContain("[批量] 原因不明的 1 篇再试一次");
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
    expect(order.filter((step) => step.startsWith("entitled:"))).toEqual(["entitled:10.1000/ok", "entitled:10.1000/fail",
      "entitled:10.1000/fail"]);  // 原因不明 once more at the end
    // The window counts the whole batch: what has settled when each paper starts.
    expect(entitled.map((c) => [c.batch?.index, c.batch?.total, c.batch?.done, c.batch?.succeeded])).toEqual([
      [1, 3, 0, 0],
      [3, 3, 2, 2],
      [3, 3, 2, 2],
    ]);
    expect(dirname(entitled[0].savePath!)).toBe(resolve("/tmp/own"));
    // Under five items the open-access lane is not shown; the window is told of the item held for its try at the end,
    // which then ends the count.
    expect(updates).toEqual([
      expect.objectContaining({ total: 3, done: 2, succeeded: 2, failed: 0, finished: false,
        later: { noAccess: 0, unexplained: 1, blocked: 0, login: 0,
          papers: { noAccess: [], unexplained: ["10.1000/fail"], blocked: [], login: [] } } }),
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
      schoolSwitch: async () => ({ schools: [], group: false, retry: true }),
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
    // Between the school's papers the lanes line goes on; the one held for its try at the end is told of; the last one
    // ends the count.
    expect(updates.slice(6)).toEqual([
      expect.objectContaining({ total: 6, done: 5, succeeded: 5, failed: 0, finished: false, lanes: "开放下载 4 篇 · 机构下载 1 篇" }),
      expect.objectContaining({ total: 6, done: 5, succeeded: 5, failed: 0, finished: false,
        later: expect.objectContaining({ noAccess: 0, unexplained: 1, blocked: 0, login: 0 }) }),
      expect.objectContaining({ total: 6, done: 6, succeeded: 5, failed: 1, finished: true }),
      expect.objectContaining({ total: 6, done: 6, succeeded: 5, failed: 1, finished: true, results: expect.any(Object) }),
    ]);
    expect(entitled.map((c) => [c.batch?.index, c.batch?.total, c.batch?.done, c.batch?.succeeded])).toEqual([
      [2, 6, 1, 1],
      [6, 6, 5, 5],
      [6, 6, 5, 5],  // 原因不明 once more at the end
    ]);
  });

  it("two_phase with supplementary files: each open-access item settles after its own files, in its turn", async () => {
    const updates: SchoolBatchUpdate[] = [];
    const visits: Array<SchoolDownloadRequest["batch"]> = [];
    const backend: SchoolBackend = {
      schoolSwitch: async () => ({ schools: [], group: false, retry: true }),
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
    // Each visit for its files comes when the open lane found it, not after the lane: the
    // count before each one is the papers finished so far (user, 2026-11-15).
    expect(visits).toEqual([0, 1, 2, 3, 4].map((done) =>
      expect.objectContaining({ id: result.batchId, index: done + 1, total: 5, done })));
    // A paper counts once its files are done: never more than the visits so far, never going back.
    const dones = updates.filter((u) => !u.finished).map((u) => u.done);
    expect(dones).toEqual([...dones].sort((x, y) => x - y));
    expect(Math.max(...dones)).toBeLessThanOrEqual(visits.length);
    expect(updates.find((u) => u.phase === "开放下载：已查 1/5 篇，找到 1 篇")?.done).toBe(0);
    expect(result.items.every((item) => item.status === "ok")).toBe(true);
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
    expect(seen).toHaveLength(4);  // each once more at the end (原因不明)
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

  it("goes on at once when the user raises the hourly limit during the wait (2026-11-19)", async () => {
    // Windows: JAMA reached 180 at 07:37 and the batch slept until 07:58, though the user set 500 at 07:51.
    const events: string[] = [];
    const lines: string[] = [];
    let limited = true;
    let checks = 0;
    const tiers = (): DownloadTier[] => [{
      id: "entitled_access",
      stage: "entitled_access",
      run: async (context) => {
        events.push(`run ${context.doi}`);
        if (limited) {
          limited = false;
          return { status: "error", message: "limit", code: "rate_limited", retryAfterSec: 1260, hourlyPublisher: "JAMA" };
        }
        return { status: "ok", verified: true, path: `/tmp/${context.doi}.pdf`, message: "ok" };
      },
    }];
    const backend: SchoolBackend = {
      schoolSwitch: async () => ({ schools: [], group: false, retry: true }),
      ...fakeBackend([]),
      keepSession: async () => {
        events.push("keep");
        return true;
      },
      hourlyWait: async (publisher) => {
        events.push(`check ${publisher}`);
        checks += 1;
        return checks < 3 ? { waitSec: 1260 - 10 * checks, limit: 180 } : { waitSec: 0, limit: 500 };
      },
    };
    const result = await downloadBatch({} as never, { items: [{ doi: "10.1001/a" }], mode: "entitled_only" },
      backend, (line) => lines.push(line), tiers, async (ms) => {
        events.push(`pause ${ms / 1000}`);
      });
    expect(events).toEqual(["run 10.1001/a", "pause 10", "check JAMA", "pause 10", "check JAMA", "pause 10", "check JAMA",
      "run 10.1001/a"]);
    expect(lines.some((line) => line.includes("按现在的每小时上限（500 篇）可以接着下这一篇"))).toBe(true);
    expect(result).toEqual(expect.objectContaining({ status: "ok", succeeded: 1 }));
  });

  it("asks every ten seconds and keeps the session every ten minutes while the limit still holds", async () => {
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
          return { status: "error", message: "limit", code: "rate_limited", retryAfterSec: 700, hourlyPublisher: "Wiley" };
        }
        return { status: "ok", verified: true, path: `/tmp/${context.doi}.pdf`, message: "ok" };
      },
    }];
    let left = 700;
    const backend: SchoolBackend = {
      schoolSwitch: async () => ({ schools: [], group: false, retry: true }),
      ...fakeBackend([]),
      keepSession: async () => {
        events.push("keep");
        return true;
      },
      // The setting unchanged: the backend's own count of what is left; an older backend cannot say.
      hourlyWait: async () => (left === 700 ? undefined : { waitSec: left, limit: 100 }),
    };
    await downloadBatch({} as never, { items: [{ doi: "10.1002/a" }], mode: "entitled_only" },
      backend, () => {}, tiers, async (ms) => {
        pauses.push(ms);
        left = Math.max(0, left - ms / 1000);
        if (left > 0 && left % 600 === 100) events.push("ten minutes");
      });
    expect(pauses.reduce((sum, ms) => sum + ms, 0)).toBe(700_000);
    expect(pauses.every((ms) => ms <= 10_000)).toBe(true);
    expect(events.filter((event) => event === "keep")).toHaveLength(1);
    expect(events.indexOf("keep")).toBeGreaterThan(events.indexOf("ten minutes"));
    expect(events.at(-1)).toBe("run 10.1002/a");
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
      schoolSwitch: async () => ({ schools: [], group: false, retry: true }),
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

  it("goes on after a journal's site blocks the current network (per_item; the other modes pause its publisher)", async () => {
    for (const mode of ["per_item"] as const) {
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

  it("tells of the papers held for a later try and the next school only a backend that declares them", () => {
    const download = { name: "school_download", inputSchema: { type: "object", properties: base } };
    const withLater = (extra: Record<string, unknown>) => ({ ...progress, inputSchema: { ...progress.inputSchema,
      properties: { ...progress.inputSchema.properties, ...extra } } });
    expect(selectSchoolBatchSupport([download, progress], "legal_only").progressLater).toBeUndefined();
    expect(selectSchoolBatchSupport([download, withLater({ later: { type: "object" } })], "legal_only").progressLater).toBeUndefined();
    expect(selectSchoolBatchSupport([download, withLater({ later: { type: "object" }, switch_to: { type: "string" } })], "legal_only")
      .progressLater).toBe(true);
  });

  it("adds the batch fields to the download arguments", () => {
    expect(createSchoolDownloadArguments("10.1000/x", "/tmp", "legal_only", batch)).toEqual(
      expect.objectContaining({ batch_id: "b", batch_index: 1, batch_total: 2, batch_done: 0 }),
    );
    expect(Object.keys(createSchoolDownloadArguments("10.1000/x", "/tmp"))).not.toContain("batch_id");
  });
});
