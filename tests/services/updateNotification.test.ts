import { afterEach, beforeEach, describe, expect, it, jest } from "@jest/globals";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { beginUpdateNotification, checkForUpdate, compareStableRelease, queryLatestStable, upgradeCommand } from "../../src/management/updates/index.js";

const NOW = 1800000000000;
let root: string;
beforeEach(() => { root = mkdtempSync(join(tmpdir(), "papersearch-updates-")); });
afterEach(() => { jest.useRealTimers(); jest.restoreAllMocks(); rmSync(root, { recursive: true, force: true }); });
const options = () => ({ current: "0.4.7", dataRoot: root, now: () => NOW });
const cache = (data: object) => writeFileSync(join(root, "update-check.json"), JSON.stringify({ schemaVersion: 1, checkedAt: NOW, ...data }));

describe("stable release checks", () => {
  it.each([
    ["0.4.7", "0.4.8", 1], ["0.9.9", "0.10.0", 1], ["1.0.0", "0.9.0", -1],
    ["0.4.7", "0.4.7", 0], ["0.4.7+dev", "0.4.7", 0], ["0.4.8-beta.1", "0.4.8", 1],
    ["0.5.0-rc.1", "0.4.8", -1], ["0.4.7", "0.4.8-beta.1", undefined],
    ["unknown", "0.4.8", undefined], ["0.4.7", "99;bad", undefined],
  ])("compares %s with %s", (current, latest, expected) => {
    expect(compareStableRelease(current, latest)).toBe(expected);
  });

  it("uses the installation channel in upgrade instructions", () => {
    expect(upgradeCommand("0.4.8", "/opt/homebrew/lib/node_modules/papersearch")).toBe("npm install -g papersearch@0.4.8");
    expect(upgradeCommand("0.4.8", "C:\\Users\\fixture\\AppData\\Roaming\\npm\\node_modules\\papersearch")).toContain("npm install -g");
    expect(upgradeCommand("0.4.8", "/project/node_modules/papersearch")).toBe("npm install papersearch@0.4.8");
    expect(upgradeCommand("0.4.8", "/data/pnpm/global/5/node_modules/.pnpm/papersearch")).toContain("pnpm add -g");
    expect(upgradeCommand("0.4.8", "/project/node_modules/.pnpm/papersearch")).toContain("pnpm add papersearch");
    expect(upgradeCommand("0.4.8", "/cache/_npx/abc/node_modules/papersearch")).toBe("npx papersearch@0.4.8");
  });

  it("queries only public npm metadata and validates an installable stable package", async () => {
    const fetcher = jest.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      name: "papersearch", version: "0.4.8", dist: { tarball: "https://registry.npmjs.org/papersearch/-/papersearch-0.4.8.tgz" },
    })));
    expect(await queryLatestStable(new AbortController().signal)).toBe("0.4.8");
    expect(fetcher).toHaveBeenCalledWith("https://registry.npmjs.org/papersearch/latest", expect.objectContaining({ redirect: "error" }));
    fetcher.mockResolvedValue(new Response(JSON.stringify({ name: "other", version: "0.4.8" })));
    await expect(queryLatestStable(new AbortController().signal)).rejects.toThrow("invalid_registry_metadata");
    fetcher.mockResolvedValue(new Response("x".repeat(129 * 1024)));
    await expect(queryLatestStable(new AbortController().signal)).rejects.toThrow("too_large");
  });
});

describe("cached notification lifecycle", () => {
  it("prints once on every invocation from a fresh cache, with no network", async () => {
    cache({ latest: "0.4.8", latestCheckedAt: NOW });
    const queryLatest = jest.fn(async () => "0.4.9");
    for (let i = 0; i < 2; i += 1) {
      const write = jest.fn();
      const session = beginUpdateNotification({ ...options(), enabled: true, allowNetwork: true, write, queryLatest });
      await session.done;
      expect(write).toHaveBeenCalledTimes(1);
      expect(write.mock.calls[0][0]).toContain("0.4.7 → 0.4.8");
      session.stop();
    }
    expect(queryLatest).not.toHaveBeenCalled();
  });

  it("suppresses disabled, current, newer and stale-cache notifications", async () => {
    const queryLatest = jest.fn(async () => "0.4.8");
    const write = jest.fn();
    for (const [latest, timestamp] of [["0.4.7", NOW], ["0.4.6", NOW], ["0.4.8", NOW - 2 * 86400000]] as const) {
      cache({ latest, latestCheckedAt: timestamp });
      await beginUpdateNotification({ ...options(), enabled: true, allowNetwork: false, write, queryLatest }).done;
    }
    await beginUpdateNotification({ ...options(), enabled: false, allowNetwork: true, write, queryLatest }).done;
    expect(write).not.toHaveBeenCalled();
    expect(queryLatest).not.toHaveBeenCalled();
  });

  it("refreshes an expired cache alongside the command", async () => {
    cache({ checkedAt: NOW - 2 * 86400000, latest: "0.4.7", latestCheckedAt: NOW - 2 * 86400000 });
    const write = jest.fn();
    const session = beginUpdateNotification({ ...options(), enabled: true, allowNetwork: true, write, queryLatest: async () => "0.4.8" });
    await session.done;
    expect(write).toHaveBeenCalledTimes(1);
    expect(JSON.parse(readFileSync(join(root, "update-check.json"), "utf8"))).toEqual({ schemaVersion: 1, checkedAt: NOW, latest: "0.4.8", latestCheckedAt: NOW });
    session.stop();
  });

  it("a cancelled check is no attempt; a failed one waits before the next", async () => {
    let aborted = false;
    const queryLatest = jest.fn((signal: AbortSignal) => new Promise<string>((_, reject) => {
      signal.addEventListener("abort", () => { aborted = true; reject(new Error("private-network-error")); });
    }));
    const write = jest.fn();
    const session = beginUpdateNotification({ ...options(), enabled: true, allowNetwork: true, write, queryLatest });
    session.stop();
    await session.done;
    expect(aborted).toBe(true);
    expect(write).not.toHaveBeenCalled();
    expect(existsSync(join(root, "update-check.json"))).toBe(false);
    const failing = jest.fn(async () => { throw new Error("registry_unavailable"); });
    await beginUpdateNotification({ ...options(), enabled: true, allowNetwork: true, write, queryLatest: failing }).done;
    await beginUpdateNotification({ ...options(), enabled: true, allowNetwork: true, write, queryLatest: failing }).done;
    expect(failing).toHaveBeenCalledTimes(1);
  });

  it("a quick command waits for the check under way and prints its reminder", async () => {
    // journal-metrics and doctor ended before npm answered, and no reminder ever came (2026-11-08).
    jest.useFakeTimers();
    const queryLatest = () => new Promise<string>((resolve) => setTimeout(() => resolve("0.4.11"), 900));
    const write = jest.fn();
    const finished = beginUpdateNotification({ ...options(), enabled: true, allowNetwork: true, write, queryLatest }).finish();
    await jest.advanceTimersByTimeAsync(900);
    await finished;
    expect(write).toHaveBeenCalledTimes(1);
    expect(write.mock.calls[0][0]).toContain("0.4.7 → 0.4.11");
    expect(JSON.parse(readFileSync(join(root, "update-check.json"), "utf8")))
      .toEqual({ schemaVersion: 1, checkedAt: NOW, latest: "0.4.11", latestCheckedAt: NOW });
  });

  it("waits no longer than the check's own timeout", async () => {
    jest.useFakeTimers();
    const queryLatest = (signal: AbortSignal) => new Promise<string>((_, reject) => signal.addEventListener("abort", () => reject(new Error("timeout"))));
    const write = jest.fn();
    let ended = false;
    const finished = beginUpdateNotification({ ...options(), enabled: true, allowNetwork: true, write, queryLatest }).finish()
      .then(() => { ended = true; });
    await jest.advanceTimersByTimeAsync(1400);
    expect(ended).toBe(false);
    await jest.advanceTimersByTimeAsync(101);
    await finished;
    expect(write).not.toHaveBeenCalled();
    expect(JSON.parse(readFileSync(join(root, "update-check.json"), "utf8"))).toEqual({ schemaVersion: 1, checkedAt: NOW });
  });

  it("bounds network waits and lets an explicit check bypass cooldown", async () => {
    jest.useFakeTimers();
    const queryLatest = (signal: AbortSignal) => new Promise<string>((_, reject) => signal.addEventListener("abort", () => reject(new Error("timeout"))));
    const pending = checkForUpdate({ ...options(), queryLatest });
    await jest.advanceTimersByTimeAsync(1501);
    expect((await pending).status).toBe("unavailable");
    const result = await checkForUpdate({ ...options(), queryLatest: async () => "0.4.8" });
    expect(result.updateAvailable).toBe(true);
  });

  it("handles corrupt/unwritable cache without changing the command", async () => {
    cache({ latest: "invalid", latestCheckedAt: NOW });
    const write = jest.fn();
    await beginUpdateNotification({ ...options(), enabled: true, allowNetwork: true, write, queryLatest: async () => "0.4.8" }).done;
    expect(write).toHaveBeenCalledTimes(1);
    const file = join(root, "not-a-directory");
    writeFileSync(file, "keep");
    const result = await checkForUpdate({ ...options(), dataRoot: file, queryLatest: async () => "0.4.8" });
    expect(result.ok).toBe(true);
    expect(readFileSync(file, "utf8")).toBe("keep");
    expect(existsSync(join(root, "unrelated"))).toBe(false);
  });
});
