import { describe, expect, it } from "@jest/globals";
import { readFileSync } from "fs";
import { CONFIG_KEYS } from "../../src/config/ConfigService.js";
import { API_KEY_SIGNUP_URLS, CONTACT_EMAIL_URLS, SETTINGS_WINDOW_KEYS, apiKeyHint } from "../../src/config/apiKeySignup.js";
import { SETTINGS_WINDOW_UNAVAILABLE, openSettingsWindow, settingsWindowEnv } from "../../src/management/school/settingsWindow.js";

// The window's list of keys lives with the backend that draws it.
const catalog = JSON.parse(readFileSync("school/paper_search_school/assets/api_keys.json", "utf8")) as {
  groups: Array<{ services: Array<{ id: string; url: string; keys: Array<{ key: string }> }> }>;
};
const services = catalog.groups.flatMap((group) => group.services);

describe("the settings window's API keys", () => {
  it("are the CLI's keys and contact emails, each once, with the CLI's sign-up or about page", () => {
    const keys = services.flatMap((service) => service.keys.map((k) => k.key));
    expect(new Set(keys).size).toBe(keys.length);
    expect(new Set(keys)).toEqual(new Set(SETTINGS_WINDOW_KEYS));
    for (const key of keys) expect(CONFIG_KEYS).toContain(key);
    for (const service of services) {
      const key = service.keys[0].key as keyof typeof API_KEY_SIGNUP_URLS;
      expect(service.url).toBe(API_KEY_SIGNUP_URLS[key] ?? CONTACT_EMAIL_URLS[key]);
    }
  });

  it("come second in the hint for a missing key, after the terminal that works everywhere", () => {
    expect(apiKeyHint("EASYSCHOLAR_KEY")).toBe(
      "Get one at https://www.easyscholar.cc/, then run `paper-search setup EASYSCHOLAR_KEY` in your own terminal; "
      + "with school subscription downloads installed, `paper-search settings EASYSCHOLAR_KEY` opens a window for it instead.");
    expect(apiKeyHint("ELSEVIER_INSTTOKEN")).toBe("Run `paper-search setup ELSEVIER_INSTTOKEN` in your own terminal.");
    expect(apiKeyHint("NCBI_EMAIL")).toBe("Run `paper-search setup NCBI_EMAIL` in your own terminal.");
    expect(apiKeyHint("PAPER_SEARCH_UNPAYWALL_EMAIL")).toBe("Run `paper-search setup PAPER_SEARCH_UNPAYWALL_EMAIL` in your own terminal; "
      + "with school subscription downloads installed, `paper-search settings PAPER_SEARCH_UNPAYWALL_EMAIL` opens a window for it instead.");
  });
});

describe("paper-search settings", () => {
  const env = { SCHOOL_DATA_DIR: "/data" };

  it("says how to get the window when school subscription downloads are not installed", async () => {
    const run = async () => { throw new Error("must not run"); };
    expect(await openSettingsWindow({ executable: "", env, run })).toEqual({ ok: false, error: SETTINGS_WINDOW_UNAVAILABLE, exitCode: 1 });
    expect(await openSettingsWindow({ executable: "/gone/paper-search-school", env, exists: () => false, run }))
      .toMatchObject({ ok: false, exitCode: 1 });
  });

  it("asks the backend to open the window and relays its answer", async () => {
    const calls: unknown[] = [];
    const run = async (file: string, args: string[], given: Record<string, string | undefined>) => {
      calls.push([file, args, given]);
      return { stdout: '{"ok": true, "window": "opened", "page": "keys", "service": "easyscholar"}\n', code: 0 };
    };
    const reply = await openSettingsWindow({ executable: "/rt/paper-search-school", target: "EASYSCHOLAR_KEY", env, exists: () => true, run });
    expect(reply).toEqual({ ok: true, window: "opened", page: "keys", service: "easyscholar" });
    expect(calls).toEqual([["/rt/paper-search-school", ["settings", "EASYSCHOLAR_KEY"], env]]);
  });

  it("passes the backend's refusal on with its exit code, and refuses odd targets itself", async () => {
    const run = async () => ({ stdout: '{"ok": false, "error": "没有这一项设置：FOO"}', code: 2 });
    expect(await openSettingsWindow({ executable: "/rt/x", target: "FOO", env, exists: () => true, run }))
      .toEqual({ ok: false, error: "没有这一项设置：FOO", exitCode: 2 });
    const silent = async () => ({ stdout: "Traceback ...", code: 1 });
    expect(await openSettingsWindow({ executable: "/rt/x", env, exists: () => true, run: silent })).toMatchObject({ ok: false, exitCode: 1 });
    expect(await openSettingsWindow({ executable: "/rt/x", target: "--help", env, exists: () => true, run }))
      .toMatchObject({ ok: false, exitCode: 2 });
  });
});

describe("the settings window's environment", () => {
  it("carries its screen, proxy and paths, and none of PaperSearch's keys", () => {
    const env = settingsWindowEnv({ dataDir: "/data", configFile: "/cfg.json", cli: '["node","cli.js"]' },
      { EASYSCHOLAR_KEY: "secret", ELSEVIER_API_KEY: "secret", DISPLAY: ":0", HTTPS_PROXY: "http://proxy:7890" });
    expect(env).toMatchObject({ SCHOOL_DATA_DIR: "/data", PAPER_SEARCH_CONFIG_FILE: "/cfg.json", PAPER_SEARCH_CLI: '["node","cli.js"]',
      DISPLAY: ":0", HTTPS_PROXY: "http://proxy:7890" });
    expect(Object.values(env)).not.toContain("secret");
  });
});

