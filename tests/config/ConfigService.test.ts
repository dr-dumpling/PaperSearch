import { mkdtempSync, rmSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { afterEach, beforeEach, describe, expect, it } from "@jest/globals";
import {
  CONFIG_KEYS,
  resolveDownloadPath,
  getConfigPath,
  getConfigValue,
  importEnvFile,
  initUserConfig,
  isConfigTrue,
  listConfigEntries,
  loadUserConfigIntoEnv,
  readUserConfig,
  setUserConfigValue,
  unsetUserConfigValue,
} from "../../src/config/ConfigService.js";

describe("ConfigService", () => {
  it("uses one download preference and notices edits made by the capsule", () => {
    const old = process.env.DEFAULT_DOWNLOAD_PATH;
    try {
      delete process.env.DEFAULT_DOWNLOAD_PATH;
      expect(resolveDownloadPath()).toBe("./downloads");
      setUserConfigValue("DEFAULT_DOWNLOAD_PATH", "/first");
      loadUserConfigIntoEnv();
      expect(resolveDownloadPath()).toBe("/first");
      writeFileSync(getConfigPath(), JSON.stringify({ DEFAULT_DOWNLOAD_PATH: "/from-capsule" }));
      expect(resolveDownloadPath()).toBe("/from-capsule");
      expect(resolveDownloadPath("/explicit")).toBe("/explicit");
      process.env.DEFAULT_DOWNLOAD_PATH = "/shell-override";
      expect(resolveDownloadPath()).toBe("/shell-override");
    } finally {
      if (old === undefined) delete process.env.DEFAULT_DOWNLOAD_PATH;
      else process.env.DEFAULT_DOWNLOAD_PATH = old;
    }
  });
  it("selects the configured executable with environment precedence", () => {
    const previous = process.env.PAPER_SEARCH_CARSI_EXECUTABLE;
    try {
      delete process.env.PAPER_SEARCH_CARSI_EXECUTABLE;
      setUserConfigValue(
        "PAPER_SEARCH_CARSI_EXECUTABLE",
        "/candidate/bin/paper-search-carsi",
      );
      expect(getConfigValue("PAPER_SEARCH_CARSI_EXECUTABLE")).toBe(
        "/candidate/bin/paper-search-carsi",
      );
      process.env.PAPER_SEARCH_CARSI_EXECUTABLE = "/override/bin/paper-search-carsi";
      expect(getConfigValue("PAPER_SEARCH_CARSI_EXECUTABLE")).toBe(
        "/override/bin/paper-search-carsi",
      );
    } finally {
      if (previous === undefined)
        delete process.env.PAPER_SEARCH_CARSI_EXECUTABLE;
      else process.env.PAPER_SEARCH_CARSI_EXECUTABLE = previous;
    }
  });
  let tempDir: string;
  let originalConfigFile: string | undefined;
  let originalSemanticKey: string | undefined;
  let originalCarsiEnabled: string | undefined;
  let originalScholarProxy: string | undefined;
  let originalScholarRate: string | undefined;
  let originalScholarRetries: string | undefined;
  let originalScholarTimeout: string | undefined;

  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "paper-search-config-test-"));
    originalConfigFile = process.env.PAPER_SEARCH_CONFIG_FILE;
    originalSemanticKey = process.env.SEMANTIC_SCHOLAR_API_KEY;
    originalCarsiEnabled = process.env.PAPER_SEARCH_CARSI_ENABLED;
    process.env.PAPER_SEARCH_CONFIG_FILE = join(tempDir, "config.json");
    delete process.env.SEMANTIC_SCHOLAR_API_KEY;
    delete process.env.PAPER_SEARCH_CARSI_ENABLED;
    originalScholarProxy = process.env.GOOGLE_SCHOLAR_PROXY_URL;
    originalScholarRate = process.env.SCHOLAR_RATE_LIMIT_RPS;
    originalScholarRetries = process.env.SCHOLAR_MAX_RETRIES;
    originalScholarTimeout = process.env.SCHOLAR_TIMEOUT_MS;
    delete process.env.GOOGLE_SCHOLAR_PROXY_URL;
    delete process.env.SCHOLAR_RATE_LIMIT_RPS;
    delete process.env.SCHOLAR_MAX_RETRIES;
    delete process.env.SCHOLAR_TIMEOUT_MS;
  });

  afterEach(() => {
    if (originalConfigFile === undefined)
      delete process.env.PAPER_SEARCH_CONFIG_FILE;
    else process.env.PAPER_SEARCH_CONFIG_FILE = originalConfigFile;

    if (originalSemanticKey === undefined)
      delete process.env.SEMANTIC_SCHOLAR_API_KEY;
    else process.env.SEMANTIC_SCHOLAR_API_KEY = originalSemanticKey;

    if (originalCarsiEnabled === undefined)
      delete process.env.PAPER_SEARCH_CARSI_ENABLED;
    else process.env.PAPER_SEARCH_CARSI_ENABLED = originalCarsiEnabled;

    if (originalScholarProxy === undefined)
      delete process.env.GOOGLE_SCHOLAR_PROXY_URL;
    else process.env.GOOGLE_SCHOLAR_PROXY_URL = originalScholarProxy;

    if (originalScholarRate === undefined)
      delete process.env.SCHOLAR_RATE_LIMIT_RPS;
    else process.env.SCHOLAR_RATE_LIMIT_RPS = originalScholarRate;
    if (originalScholarRetries === undefined)
      delete process.env.SCHOLAR_MAX_RETRIES;
    else process.env.SCHOLAR_MAX_RETRIES = originalScholarRetries;
    if (originalScholarTimeout === undefined)
      delete process.env.SCHOLAR_TIMEOUT_MS;
    else process.env.SCHOLAR_TIMEOUT_MS = originalScholarTimeout;

    rmSync(tempDir, { recursive: true, force: true });
  });

  it("creates and reads a user config file", () => {
    const init = initUserConfig();
    expect(init.path).toBe(getConfigPath());
    expect(init.created).toBe(true);

    setUserConfigValue("SEMANTIC_SCHOLAR_API_KEY", "semantic-test-key");
    expect(readUserConfig()).toEqual({
      SEMANTIC_SCHOLAR_API_KEY: "semantic-test-key",
    });

    unsetUserConfigValue("SEMANTIC_SCHOLAR_API_KEY");
    expect(readUserConfig()).toEqual({});
  });

  it("loads user config into missing environment variables without overriding shell env", () => {
    setUserConfigValue("SEMANTIC_SCHOLAR_API_KEY", "from-config");
    process.env.SEMANTIC_SCHOLAR_API_KEY = "from-env";

    expect(loadUserConfigIntoEnv()).toEqual([]);
    expect(process.env.SEMANTIC_SCHOLAR_API_KEY).toBe("from-env");

    delete process.env.SEMANTIC_SCHOLAR_API_KEY;
    expect(loadUserConfigIntoEnv()).toEqual(["SEMANTIC_SCHOLAR_API_KEY"]);
    expect(process.env.SEMANTIC_SCHOLAR_API_KEY).toBe("from-config");
  });

  it("imports supported keys from a dotenv file and masks listed values", () => {
    const envPath = join(tempDir, ".env");
    writeFileSync(
      envPath,
      [
        "SEMANTIC_SCHOLAR_API_KEY=semantic-test-key",
        "PAPER_SEARCH_UNPAYWALL_EMAIL=user@example.com",
        "CORE_MAX_RESULTS_CAP=300",
        "UNSUPPORTED_KEY=ignored",
      ].join("\n"),
    );

    const result = importEnvFile(envPath);
    expect(result.imported).toEqual([
      "SEMANTIC_SCHOLAR_API_KEY",
      "PAPER_SEARCH_UNPAYWALL_EMAIL",
      "CORE_MAX_RESULTS_CAP",
    ]);

    const entries = listConfigEntries();
    expect(entries).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "SEMANTIC_SCHOLAR_API_KEY",
          configured: true,
          value: "sema...-key",
        }),
        expect.objectContaining({
          key: "PAPER_SEARCH_UNPAYWALL_EMAIL",
          configured: true,
          value: "us***@example.com",
        }),
        expect.objectContaining({
          key: "CORE_MAX_RESULTS_CAP",
          configured: true,
          value: "***",
        }),
      ]),
    );
  });

  it("keeps the Elsevier metadata key and rejects the removed Wiley TDM token", () => {
    setUserConfigValue("ELSEVIER_API_KEY", "elsevier-metadata-key");

    expect(readUserConfig()).toEqual({
      ELSEVIER_API_KEY: "elsevier-metadata-key",
    });
    expect(() => setUserConfigValue("WILEY_TDM_TOKEN", "legacy-token")).toThrow(
      "Unsupported config key: WILEY_TDM_TOKEN",
    );
  });

  it("exposes the opt-in flag and explicit executable without account settings", () => {
    expect(CONFIG_KEYS.filter((key) => key.includes("CARSI"))).toEqual([
      "PAPER_SEARCH_CARSI_ENABLED",
      "PAPER_SEARCH_CARSI_EXECUTABLE",
    ]);
  });

  it("enables CARSI only for the exact true string in user config", () => {
    expect(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED")).toBe(false);

    for (const value of ["false", "TRUE", "1", "yes", " true ", ""]) {
      setUserConfigValue("PAPER_SEARCH_CARSI_ENABLED", value);
      expect(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED")).toBe(false);
    }

    setUserConfigValue("PAPER_SEARCH_CARSI_ENABLED", "true");
    expect(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED")).toBe(true);
  });

  it("gives the environment value priority over user config without coercion", () => {
    setUserConfigValue("PAPER_SEARCH_CARSI_ENABLED", "true");

    for (const value of ["false", "TRUE", "1", "yes", " true ", ""]) {
      process.env.PAPER_SEARCH_CARSI_ENABLED = value;
      expect(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED")).toBe(false);
    }

    process.env.PAPER_SEARCH_CARSI_ENABLED = "true";
    expect(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED")).toBe(true);
  });

  it.each([
    ["", false],
    ["false", true],
  ])(
    "does not overwrite an explicitly defined %p environment value from user config",
    (environmentValue, configured) => {
      setUserConfigValue("PAPER_SEARCH_CARSI_ENABLED", "true");
      process.env.PAPER_SEARCH_CARSI_ENABLED = environmentValue;

      expect(loadUserConfigIntoEnv()).not.toContain(
        "PAPER_SEARCH_CARSI_ENABLED",
      );
      expect(process.env.PAPER_SEARCH_CARSI_ENABLED).toBe(environmentValue);
      expect(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED")).toBe(false);
      expect(
        listConfigEntries(true).find(
          (entry) => entry.key === "PAPER_SEARCH_CARSI_ENABLED",
        ),
      ).toEqual(
        expect.objectContaining({
          configured,
          source: "environment",
        }),
      );
    },
  );

  it("lets a value copied from the config file follow a later write of that file", () => {
    // setup reported the extension disabled right after installing it: the
    // process kept the copy "false" it had loaded (review 2026-11-02).
    setUserConfigValue("PAPER_SEARCH_CARSI_ENABLED", "false");
    expect(loadUserConfigIntoEnv()).toContain("PAPER_SEARCH_CARSI_ENABLED");
    expect(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED")).toBe(false);

    setUserConfigValue("PAPER_SEARCH_CARSI_ENABLED", "true");
    expect(process.env.PAPER_SEARCH_CARSI_ENABLED).toBe("true");
    expect(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED")).toBe(true);
    expect(
      listConfigEntries(true).find(
        (entry) => entry.key === "PAPER_SEARCH_CARSI_ENABLED",
      )?.source,
    ).toBe("user_config");

    unsetUserConfigValue("PAPER_SEARCH_CARSI_ENABLED");
    expect(process.env.PAPER_SEARCH_CARSI_ENABLED).toBeUndefined();
    expect(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED")).toBe(false);
  });

  it("keeps the environment's own value when the config file is written", () => {
    process.env.PAPER_SEARCH_CARSI_ENABLED = "false";
    setUserConfigValue("PAPER_SEARCH_CARSI_ENABLED", "true");
    expect(process.env.PAPER_SEARCH_CARSI_ENABLED).toBe("false");
    expect(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED")).toBe(false);
  });

  it("does not carry user-config provenance across config file paths", () => {
    const firstConfigPath = join(tempDir, "first-config.json");
    const secondConfigPath = join(tempDir, "second-config.json");

    process.env.PAPER_SEARCH_CONFIG_FILE = firstConfigPath;
    setUserConfigValue("PAPER_SEARCH_CARSI_ENABLED", "true");
    expect(loadUserConfigIntoEnv()).toContain("PAPER_SEARCH_CARSI_ENABLED");
    expect(
      listConfigEntries(true).find(
        (entry) => entry.key === "PAPER_SEARCH_CARSI_ENABLED",
      )?.source,
    ).toBe("user_config");

    process.env.PAPER_SEARCH_CONFIG_FILE = secondConfigPath;
    setUserConfigValue("PAPER_SEARCH_CARSI_ENABLED", "true");
    process.env.PAPER_SEARCH_CARSI_ENABLED = "true";

    expect(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED")).toBe(true);
    expect(
      listConfigEntries(true).find(
        (entry) => entry.key === "PAPER_SEARCH_CARSI_ENABLED",
      )?.source,
    ).toBe("environment");
  });

  it("accepts Scholar proxy configuration and masks the full proxy value", () => {
    setUserConfigValue(
      "GOOGLE_SCHOLAR_PROXY_URL",
      "socks5://user:password@127.0.0.1:1080",
    );

    const entry = listConfigEntries().find(
      (item) => item.key === "GOOGLE_SCHOLAR_PROXY_URL",
    );
    expect(entry).toEqual({
      key: "GOOGLE_SCHOLAR_PROXY_URL",
      configured: true,
      source: "user_config",
      value: "***configured***",
    });
  });

  it("accepts the low-volume Scholar tuning keys", () => {
    setUserConfigValue("SCHOLAR_RATE_LIMIT_RPS", "0.5");
    setUserConfigValue("SCHOLAR_MAX_RETRIES", "2");
    setUserConfigValue("SCHOLAR_TIMEOUT_MS", "15000");

    expect(readUserConfig()).toEqual(
      expect.objectContaining({
        SCHOLAR_RATE_LIMIT_RPS: "0.5",
        SCHOLAR_MAX_RETRIES: "2",
        SCHOLAR_TIMEOUT_MS: "15000",
      }),
    );
  });
});
