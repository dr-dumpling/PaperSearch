import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";
import {
  prepareProSchoolLogin,
  SCHOOL_LOGIN_ENV,
  useMarkdownPro,
} from "../../src/capabilities/download/content/markdown/pro.js";
import { schoolLoginEnv } from "../../src/infrastructure/school/index.js";
import { settingsWindowEnv } from "../../src/management/school/settingsWindow.js";
import { fakeMarkdownPro } from "../helpers/fakeMarkdownPro.js";

// PaperSearch Pro's features on, whatever the edition (src/config/edition.ts).
process.env.PAPER_SEARCH_PRO_FEATURES = "1";

// PaperSearch Pro's school sign-in: its Python part written beside
// Pro and named for the backend once Pro may be used; never otherwise.
describe("PaperSearch Pro's school sign-in, prepared for the backend", () => {
  let dir: string;
  let env: Record<string, string | undefined>;
  const files = { "school_login/__init__.py": "API = 1\n", "school_login/schools/carsi/a_school.py": "STATUS = 'trial'\n" };
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "paper-search-pro-login-"));
    env = { PAPER_SEARCH_PRO_PATH: join(dir, "index.js"), [SCHOOL_LOGIN_ENV]: "/stale/school_login.py" };
  });
  afterEach(() => {
    useMarkdownPro(undefined);
    rmSync(dir, { recursive: true, force: true });
  });

  it("writes the package beside Pro, the user's alone, names its entry, and drops a school Pro no longer has", async () => {
    useMarkdownPro(fakeMarkdownPro({ schoolLogin: { apiVersion: 1, files: () => files } }));
    const entry = await prepareProSchoolLogin(env);
    expect(entry).toBe(join(dir, "school", "school_login", "__init__.py"));
    expect(env[SCHOOL_LOGIN_ENV]).toBe(entry);
    for (const [path, text] of Object.entries(files)) expect(readFileSync(join(dir, "school", path), "utf8")).toBe(text);
    if (process.platform !== "win32") expect(statSync(entry!).mode & 0o777).toBe(0o600);
    const fewer = { "school_login/__init__.py": "API = 1\n" };
    useMarkdownPro(fakeMarkdownPro({ schoolLogin: { apiVersion: 1, files: () => fewer } }));
    await prepareProSchoolLogin(env);
    expect(existsSync(join(dir, "school", "school_login", "schools", "carsi", "a_school.py"))).toBe(false);
  });

  it("names none when Pro is missing, may not be used now, or has another interface", async () => {
    for (const pro of [undefined,
      fakeMarkdownPro({ access: () => ({ ok: false, code: "markdown_pro_offline" }), schoolLogin: { apiVersion: 1, files: () => files } }),
      fakeMarkdownPro({ schoolLogin: { apiVersion: 2, files: () => files } }),
      fakeMarkdownPro()]) {
      useMarkdownPro(pro);
      env[SCHOOL_LOGIN_ENV] = "/stale/school_login.py";
      expect(await prepareProSchoolLogin(env)).toBeUndefined();
      expect(env[SCHOOL_LOGIN_ENV]).toBeUndefined();
    }
    expect(existsSync(join(dir, "school"))).toBe(false);
  });

  it("goes to the backend and the settings window, with the maintainers' trial switch", () => {
    const given = { PAPER_SEARCH_PRO_SCHOOL_LOGIN: "/data/pro/school_login.py", PAPER_SEARCH_SCHOOL_LOGIN_TRIAL: "1",
      PAPER_SEARCH_SCHOOL_LOGIN_SURVEY: "1" };
    expect(schoolLoginEnv(given)).toEqual(given);
    expect(schoolLoginEnv({})).toEqual({});
    const window = settingsWindowEnv({ dataDir: "/data", configFile: "/cfg.json", cli: "" }, { ...given, PAPER_SEARCH_PRO_FEATURES: "1" });
    expect(window).toMatchObject(given);
  });
});
