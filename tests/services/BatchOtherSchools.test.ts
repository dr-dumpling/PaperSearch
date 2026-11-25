import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "@jest/globals";
import { downloadBatch } from "../../src/capabilities/download/batch/batch.js";
import type { DownloadTier } from "../../src/capabilities/download/content/pdf/DownloadTier.js";
import type { SchoolBackend, SchoolBatchUpdate } from "../../src/infrastructure/school/types.js";

/**
 * 没权限时换下一所学校 in a batch (PaperSearch Pro; user, 2026-11-22): every paper with the default school first; the
 * papers failed under 没权限 (refused, the school's sign-in not enabled, no route, the user's mark) go to the other saved
 * schools at the end, all of them with one school before the next, not one switch per paper.
 */
const A = { name: "甲大学", entityId: "https://idp.a.example/idp" };
const B = { name: "乙大学", entityId: "https://idp.b.example/idp" };
const C = { name: "丙大学", entityId: "https://idp.c.example/idp" };

/** Who has access to what, by school ("default": 甲); a list is one answer per visit. */
const ACCESS: Record<string, Record<string, string | string[]>> = {
  "10.1000/a": { default: "entitlement_missing", [B.entityId]: "ok" },
  "10.1000/b": { default: "institution_not_registered", [B.entityId]: "institution_federation_unavailable", [C.entityId]: "ok" },
  "10.1000/c": { default: "ok" },
  "10.1000/d": { default: "no_entitlement", [B.entityId]: "entitlement_missing", [C.entityId]: "entitlement_missing" },
  "10.1000/e": { default: "login_required", [B.entityId]: "ok" },
};

/** 原因不明 once more at the end, with the default school (user, 2026-11-22). */
const AGAIN: Record<string, Record<string, string | string[]>> = {
  "10.1000/f": { default: ["download_timeout", "ok"] },
  "10.1000/g": { default: ["download_failed", "download_failed"] },
  "10.1000/h": { default: ["download_failed", "entitlement_missing"], [B.entityId]: "ok" },
};

function run(mode: "entitled_only" | "per_item" | "two_phase", schools = [A, B, C], group = false, access = ACCESS, retry = true) {
  const visits: string[] = [];
  const updates: SchoolBatchUpdate[] = [];
  const lines: string[] = [];
  const backend: SchoolBackend = {
    probe: async () => ({ state: "available", code: "ready", message: "", missing: [] }),
    downloadLegalDoi: async () => { throw new Error("tiers are faked"); },
    reportBatchProgress: async (update) => { updates.push(update); return true; },
    schoolSwitch: async () => ({ schools, group, retry }),
  };
  const tiers = (): DownloadTier[] => [
    { id: "oa", stage: "unpaywall", run: async () => ({ status: "skipped", message: "no oa" }) },
    {
      id: "entitled_access",
      stage: "entitled_access",
      run: async (context) => {
        const school = context.school ?? "default";
        visits.push(`${context.doi}@${schools.find((s) => s.entityId === context.school)?.name ?? "默认"}`);
        const given = access[context.doi!]?.[school] ?? "entitlement_missing";
        const answer = Array.isArray(given) ? given.shift()! : given;
        return answer === "ok"
          ? { status: "ok", verified: true, path: `/tmp/${context.doi!.slice(8)}.pdf`, message: "ok",
              ...(context.school ? { school: schools.find((s) => s.entityId === context.school)!.name } : {}) }
          : { status: "error", message: answer, code: answer };
      },
    },
  ];
  const root = mkdtempSync(join(tmpdir(), "batch-schools-"));
  return downloadBatch({} as never, {
    mode,
    items: Object.keys(access).map((doi) => ({ doi })),
    savePath: root,
  }, backend, (line) => lines.push(line), tiers).then((result) => {
    rmSync(root, { recursive: true, force: true });
    return { result, visits, updates, lines };
  });
}

describe("a batch's papers without access", () => {
  for (const mode of ["entitled_only", "per_item", "two_phase"] as const) {
    it(`go to the other schools at the end, one school at a time (${mode})`, async () => {
      const { result, visits, updates, lines } = await run(mode);
      // Every paper with the default school first; e (原因不明) once more with it; then 乙 for the three without
      // access; then 丙 for the two left.
      expect(visits).toEqual([
        "10.1000/a@默认", "10.1000/b@默认", "10.1000/c@默认", "10.1000/d@默认", "10.1000/e@默认",
        "10.1000/e@默认",
        "10.1000/a@乙大学", "10.1000/b@乙大学", "10.1000/d@乙大学",
        "10.1000/b@丙大学", "10.1000/d@丙大学",
      ]);
      expect(lines).toContain("[批量] 原因不明的 1 篇再试一次");
      if (mode === "entitled_only") {
        // The papers waiting for the end counted in the log's step (Windows 2026-11-22: every line said 1/7).
        expect(lines.filter((line) => line.startsWith("[批量] 机构下载 "))).toEqual(
          ["a", "b", "c", "d", "e"].map((x, at) => `[批量] 机构下载 ${at + 1}/5：10.1000/${x}`));
      }
      expect(lines).toContain("[批量] 没权限的 3 篇换乙大学再试");
      expect(lines).toContain("[批量] 没权限的 2 篇换丙大学再试");
      const byDoi = Object.fromEntries(result.items.map((item) => [item.doi, item]));
      expect(byDoi["10.1000/a"].status).toBe("ok");
      expect(byDoi["10.1000/b"].status).toBe("ok");
      // A sign-in that failed is not 没权限: not tried with another school.
      expect(byDoi["10.1000/e"].status).toBe("error");
      // None of the three had it: the last school stage says how many were tried.
      const last = [...byDoi["10.1000/d"].attempts].reverse().find((attempt) => attempt.stage === "entitled_access");
      expect(last).toMatchObject({ code: "entitlement_missing", schools: 3 });
      expect(result.succeeded).toBe(3);
      // The window's ring holds them as they wait and lets them go as they end (user, 2026-11-23): a, b and d without
      // access, e 原因不明 too; then 乙 named a moment, for the three; then 丙, for the two left.
      const later = (noAccess: number, unexplained = 0) => ({ noAccess, unexplained, blocked: 0, login: 0 });
      // The counts (each kind's papers by DOI ride along for the window's 重试 list, 2026-11-24).
      const counts = (update: SchoolBatchUpdate) => update.later && { noAccess: update.later.noAccess, unexplained: update.later.unexplained,
        blocked: update.later.blocked, login: update.later.login };
      expect(updates.some((update) => JSON.stringify(counts(update)) === JSON.stringify(later(3, 1)))).toBe(true);
      expect(updates.filter((update) => update.switchTo).map((update) => [update.switchTo, counts(update)]))
        .toEqual([["乙大学", later(3)], ["丙大学", later(2)]]);
      expect(updates.find((update) => update.switchTo === "丙大学")?.later?.papers?.noAccess).toHaveLength(2);
      expect(updates.some((update) => update.later?.noAccess === 1)).toBe(true);
      // Never more than the papers not done; no line besides the school's name.
      const held = (update: SchoolBatchUpdate) => update.later
        ? update.later.noAccess + update.later.unexplained + update.later.blocked + update.later.login : 0;
      expect(updates.filter((update) => update.later && update.done + held(update) > update.total)).toEqual([]);
      expect(updates.some((update) => update.phase?.startsWith("没权限"))).toBe(false);
      if (mode !== "per_item") {
        const failures = updates.at(-1)?.results?.failures ?? [];
        expect(failures).toEqual(expect.arrayContaining([expect.objectContaining({ doi: "10.1000/d", reason: "3 所学校都没有权限" })]));
      }
    });
  }

  it("stay as they are with one school", async () => {
    const { visits } = await run("entitled_only", [A]);
    expect(visits).toHaveLength(6);  // e (原因不明) once more
  });
});

describe("a batch's papers failed for a reason not known", () => {
  for (const mode of ["entitled_only", "per_item"] as const) {
    it(`are tried once more at the end, before the other schools (${mode})`, async () => {
      const access = JSON.parse(JSON.stringify(AGAIN)) as typeof AGAIN;
      const { result, visits, lines } = await run(mode, [A, B], false, access);
      expect(visits).toEqual([
        "10.1000/f@默认", "10.1000/g@默认", "10.1000/h@默认",
        "10.1000/f@默认", "10.1000/g@默认", "10.1000/h@默认",  // once more, the default school still signed in
        "10.1000/h@乙大学",                                      // without access now: the next school
      ]);
      expect(lines).toContain("[批量] 原因不明的 3 篇再试一次");
      const status = Object.fromEntries(result.items.map((item) => [item.doi, item.status]));
      expect(status).toEqual({ "10.1000/f": "ok", "10.1000/g": "error", "10.1000/h": "ok" });
      expect(result.succeeded).toBe(2);
    });
    // 失败后自动重试 off, the default (user, 2026-11-24): failed at once; without access, the next school all the same.
    it(`fail at once without 失败后自动重试 (${mode})`, async () => {
      const access = JSON.parse(JSON.stringify(AGAIN)) as typeof AGAIN;
      const { result, visits, lines } = await run(mode, [A, B], false, access, false);
      expect(visits).toEqual(["10.1000/f@默认", "10.1000/g@默认", "10.1000/h@默认"]);
      expect(lines.some((line) => line.includes("再试一次"))).toBe(false);
      expect(result.items.map((item) => item.status)).toEqual(["error", "error", "error"]);
    });
  }
});

describe("a batch with more than one school", () => {
  it("still takes one journal's papers one after another", async () => {
    const visits: string[] = [];
    const backend: SchoolBackend = {
      probe: async () => ({ state: "available", code: "ready", message: "", missing: [] }),
      downloadLegalDoi: async () => { throw new Error("tiers are faked"); },
      schoolSwitch: async () => ({ schools: [A, B], group: true, retry: true }),
    };
    const tiers = (): DownloadTier[] => [{
      id: "entitled_access",
      stage: "entitled_access",
      run: async (context) => {
        visits.push(context.doi!);
        return { status: "ok", verified: true, path: "/tmp/x.pdf", message: "ok" };
      },
    }];
    const root = mkdtempSync(join(tmpdir(), "batch-group-"));
    await downloadBatch({} as never, {
      mode: "entitled_only",
      items: ["10.1016/j.metabol.2024.1", "10.1007/s00125-024-1", "10.1016/j.metabol.2024.2", "10.1007/s00125-024-2"].map((doi) => ({ doi })),
      savePath: root,
    }, backend, () => undefined, tiers);
    rmSync(root, { recursive: true, force: true });
    // Asked once the backend has run a paper: the first goes as it comes, then its journal's.
    expect(visits).toEqual(["10.1016/j.metabol.2024.1", "10.1016/j.metabol.2024.2", "10.1007/s00125-024-1", "10.1007/s00125-024-2"]);
  });
});
