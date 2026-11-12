import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";
import {
  applyLegacyEnvironment,
  canonicalConfigKey,
  migrateLegacyConfigFile,
  readUserConfig,
  setUserConfigValue,
} from "../../src/config/ConfigService.js";

// School subscription downloads were named for CARSI before 0.6.1: their old keys still count.
describe("config keys from before 0.6.1", () => {
  let previous: string | undefined;
  let file: string;
  beforeEach(() => {
    previous = process.env.PAPER_SEARCH_CONFIG_FILE;
    file = join(mkdtempSync(join(tmpdir(), "psc-legacy-config-")), "config.json");
    process.env.PAPER_SEARCH_CONFIG_FILE = file;
  });
  afterEach(() => {
    if (previous === undefined) delete process.env.PAPER_SEARCH_CONFIG_FILE;
    else process.env.PAPER_SEARCH_CONFIG_FILE = previous;
  });

  it("reads the old keys of the config file as the new ones and rewrites the file once", () => {
    writeFileSync(file, JSON.stringify({
      PAPER_SEARCH_CARSI_ENABLED: "true",
      PAPER_SEARCH_CARSI_EXECUTABLE: "/old/carsi-runtime/venv/bin/paper-search-carsi",
      PAPER_SEARCH_CARSI_DECLINED: "false",
      PAPER_SEARCH_SCHOOL_AUTO_UPDATE: "false",
      PAPER_SEARCH_CARSI_AUTO_UPDATE: "true", // the new key wins
      EASYSCHOLAR_KEY: "kept",
    }));
    expect(readUserConfig()).toEqual({
      PAPER_SEARCH_SCHOOL_ENABLED: "true",
      PAPER_SEARCH_SCHOOL_EXECUTABLE: "/old/carsi-runtime/venv/bin/paper-search-carsi",
      PAPER_SEARCH_SCHOOL_DECLINED: "false",
      PAPER_SEARCH_SCHOOL_AUTO_UPDATE: "false",
      EASYSCHOLAR_KEY: "kept",
    });
    expect(migrateLegacyConfigFile()).toBe(true);
    expect(Object.keys(JSON.parse(readFileSync(file, "utf8"))).sort()).toEqual([
      "EASYSCHOLAR_KEY", "PAPER_SEARCH_SCHOOL_AUTO_UPDATE", "PAPER_SEARCH_SCHOOL_DECLINED",
      "PAPER_SEARCH_SCHOOL_ENABLED", "PAPER_SEARCH_SCHOOL_EXECUTABLE",
    ]);
    expect(migrateLegacyConfigFile()).toBe(false);
  });

  it("takes an old key named by an older Skill, and old keys in the environment", () => {
    setUserConfigValue("PAPER_SEARCH_CARSI_DECLINED", "true");
    expect(JSON.parse(readFileSync(file, "utf8"))).toEqual({ PAPER_SEARCH_SCHOOL_DECLINED: "true" });
    expect(canonicalConfigKey("PAPER_SEARCH_CARSI_AUTO_UPDATE")).toBe("PAPER_SEARCH_SCHOOL_AUTO_UPDATE");
    expect(canonicalConfigKey("EASYSCHOLAR_KEY")).toBe("EASYSCHOLAR_KEY");
    const env: NodeJS.ProcessEnv = { PAPER_SEARCH_CARSI_ENABLED: "true", PAPER_SEARCH_CARSI_EXECUTABLE: "/a",
      PAPER_SEARCH_SCHOOL_EXECUTABLE: "/b" };
    applyLegacyEnvironment(env);
    expect([env.PAPER_SEARCH_SCHOOL_ENABLED, env.PAPER_SEARCH_SCHOOL_EXECUTABLE]).toEqual(["true", "/b"]);
  });
});
