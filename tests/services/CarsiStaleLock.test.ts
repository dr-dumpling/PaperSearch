import { mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "@jest/globals";
import { isStaleDownloadLock } from "../../src/capabilities/pdf-discovery/carsi/CarsiMcpClient.js";

function deadPid(): number {
  const child = spawnSync(process.execPath, ["-e", ""]);
  return child.pid as number;
}

function setup(owner: unknown, browserLock?: string) {
  const dir = mkdtempSync(join(tmpdir(), "carsi-lock-"));
  const lock = join(dir, ".paper-search-download.lock");
  writeFileSync(lock, typeof owner === "string" ? owner : JSON.stringify({ pid: owner }));
  if (browserLock !== undefined) {
    mkdirSync(join(dir, "browser_profiles", "publisher-camoufox"), { recursive: true });
    symlinkSync(browserLock, join(dir, "browser_profiles", "publisher-camoufox", "lock"));
  }
  return { dir, lock };
}

describe("stale download lock", () => {
  it("is stale only when the owner exited and no browser holds a profile", () => {
    const dead = deadPid();
    let s = setup(dead);
    expect(isStaleDownloadLock(s.lock, s.dir)).toBe(true);
    s = setup(dead, `192.168.1.5:+${deadPid()}`);
    expect(isStaleDownloadLock(s.lock, s.dir)).toBe(true);
    s = setup(dead, `192.168.1.5:+${process.pid}`);
    expect(isStaleDownloadLock(s.lock, s.dir)).toBe(false);
  });

  it("never reclaims a live owner or an unreadable lock", () => {
    let s = setup(process.pid);
    expect(isStaleDownloadLock(s.lock, s.dir)).toBe(false);
    s = setup("not json");
    expect(isStaleDownloadLock(s.lock, s.dir)).toBe(false);
    s = setup(0);
    expect(isStaleDownloadLock(s.lock, s.dir)).toBe(false);
  });
});
