import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "@jest/globals";
import { resolveDefaultSchoolProfileDir } from "../../src/capabilities/pdf-discovery/school/index.js";
import { moveLegacyDataDir } from "../../src/management/school/legacy.js";

/** 0.6.0's data directory (named for CARSI) with a backend config that saved its paths. */
function oldData(): { env: Record<string, string>; home: string; from: string; to: string } {
  const base = mkdtempSync(join(tmpdir(), "psc-legacy-data-"));
  const from = join(base, "paper-search-cli", "carsi");
  mkdirSync(join(from, "browser_profiles", "Default"), { recursive: true });
  writeFileSync(join(from, "config.json"), JSON.stringify({
    output_dir: join(from, "papers"), cache_dir: join(from, "cache"), school_name: "红木兰大学", elsewhere: "/data/papers",
  }));
  return { env: { XDG_DATA_HOME: base }, home: join(base, "home"), from, to: join(base, "paper-search-cli", "school") };
}

describe("the data directory from before 0.6.1", () => {
  it("stays in use until it is renamed, then the saved paths follow it", () => {
    const d = oldData();
    expect(resolveDefaultSchoolProfileDir(d.env, d.home)).toBe(d.from);
    expect(moveLegacyDataDir(d.env, d.home).outcome).toBe("moved");
    expect(existsSync(d.from)).toBe(false);
    expect(resolveDefaultSchoolProfileDir(d.env, d.home)).toBe(d.to);
    expect(JSON.parse(readFileSync(join(d.to, "config.json"), "utf8"))).toEqual({
      output_dir: join(d.to, "papers"), cache_dir: join(d.to, "cache"), school_name: "红木兰大学", elsewhere: "/data/papers",
    });
    expect(moveLegacyDataDir(d.env, d.home).outcome).toBe("none");
  });

  it("waits while a download holds it", () => {
    const d = oldData();
    writeFileSync(join(d.from, ".paper-search-download.lock"), JSON.stringify({ pid: process.pid }));
    expect(moveLegacyDataDir(d.env, d.home).outcome).toBe("busy");
    expect(resolveDefaultSchoolProfileDir(d.env, d.home)).toBe(d.from);
  });

  it("leaves both alone once the new directory exists", () => {
    const d = oldData();
    mkdirSync(d.to, { recursive: true });
    expect(moveLegacyDataDir(d.env, d.home).outcome).toBe("none");
    expect(existsSync(d.from)).toBe(true);
    expect(resolveDefaultSchoolProfileDir(d.env, d.home)).toBe(d.to);
  });
});
