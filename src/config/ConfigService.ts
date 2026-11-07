import * as dotenv from "dotenv";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "fs";
import { dirname, join } from "path";
import { homedir } from "os";

export const CONFIG_KEYS = [
  "SEMANTIC_SCHOLAR_API_KEY",
  "PAPER_SEARCH_UNPAYWALL_EMAIL",
  "UNPAYWALL_EMAIL",
  "CORE_API_KEY",
  "CORE_MAX_RESULTS_CAP",
  "WOS_API_KEY",
  "WOS_API_VERSION",
  "PUBMED_API_KEY",
  "NCBI_EMAIL",
  "NCBI_TOOL",
  "ELSEVIER_API_KEY",
  "ELSEVIER_INSTTOKEN",
  "IEEE_API_KEY",
  "EASYSCHOLAR_KEY",
  "SPRINGER_API_KEY",
  "SPRINGER_OPENACCESS_API_KEY",
  "CROSSREF_MAILTO",
  "OPENAIRE_API_KEY",
  "PAPER_SEARCH_CARSI_ENABLED",
  "PAPER_SEARCH_CARSI_EXECUTABLE",
  "PAPER_SEARCH_SKILL_AUTO_UPDATE",
  "PAPER_SEARCH_UPDATE_NOTIFY",
  "LOG_LEVEL",
  "DEFAULT_DOWNLOAD_PATH",
  "MAX_FILE_SIZE_MB",
  "RATE_LIMIT_REQUESTS_PER_MINUTE",
  "RATE_LIMIT_BURST",
  "HTTP_PROXY",
  "HTTPS_PROXY",
  "GOOGLE_SCHOLAR_PROXY_URL",
  "SCHOLAR_RATE_LIMIT_RPS",
  "SCHOLAR_MAX_RETRIES",
  "SCHOLAR_TIMEOUT_MS",
] as const;

export type ConfigKey = (typeof CONFIG_KEYS)[number];

export interface ConfigEntry {
  key: string;
  configured: boolean;
  source: "environment" | "user_config" | "missing";
  value: string;
}

const CONFIG_KEY_SET = new Set<string>(CONFIG_KEYS);
const APPLIED_FROM_USER_CONFIG = new Map<
  string,
  { configPath: string; value: string }
>();

export function getConfigPath(): string {
  if (process.env.PAPER_SEARCH_CONFIG_FILE)
    return process.env.PAPER_SEARCH_CONFIG_FILE;
  const configDir =
    process.env.PAPER_SEARCH_CONFIG_DIR ||
    join(homedir(), ".config", "paper-search-cli");
  return join(configDir, "config.json");
}

export function readUserConfig(): Record<string, string> {
  const filePath = getConfigPath();
  if (!existsSync(filePath)) return {};

  const parsed = parseConfigFile(filePath);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw configError(`Config file is not a JSON object: ${filePath}. ${CONFIG_FIX_HINT}`);
  }

  const config: Record<string, string> = {};
  for (const [key, value] of Object.entries(parsed)) {
    if (CONFIG_KEY_SET.has(key) && value !== undefined && value !== null) {
      config[key] = String(value);
    }
  }
  return config;
}

const CONFIG_FIX_HINT =
  'Fix it by hand so it holds one object of "KEY": "value" pairs with nothing after the closing brace, ' +
  "or rename it and run `paper-search setup` to create a new one.";

/**
 * Parse the user config. A UTF-8 BOM (which Windows editors add) is allowed.
 * A broken file names its path and the line and column; the parser's own
 * message is left out because it can quote the file, keys included.
 */
function parseConfigFile(filePath: string): unknown {
  const text = readFileSync(filePath, "utf8").replace(/^\uFEFF/, "");
  try {
    return JSON.parse(text);
  } catch (error) {
    const position = /position (\d+)/.exec(String((error as Error)?.message));
    const where = position ? ` (${lineAndColumn(text, Number(position[1]))})` : "";
    throw configError(`Config file is not valid JSON${where}: ${filePath}. ${CONFIG_FIX_HINT}`);
  }
}

/** `CONFIG_INVALID`: the CLI reports it as is, without a provider diagnostic. */
function configError(message: string): Error {
  return Object.assign(new Error(message), { code: "CONFIG_INVALID" });
}

function lineAndColumn(text: string, offset: number): string {
  const before = text.slice(0, offset).split("\n");
  return `line ${before.length}, column ${before[before.length - 1].length + 1}`;
}

export function isConfigTrue(key: ConfigKey): boolean {
  return effectiveConfigValue(key, readUserConfig()).value === "true";
}

export function getConfigValue(key: ConfigKey): string {
  return effectiveConfigValue(key, readUserConfig()).value;
}

/** Resolve once at task start; GUI edits share the CLI config, not a second preference. */
export function resolveDownloadPath(explicit?: string): string {
  if (explicit?.trim()) return explicit;
  const config = readUserConfig();
  const applied = APPLIED_FROM_USER_CONFIG.get("DEFAULT_DOWNLOAD_PATH");
  const inherited = applied?.configPath === getConfigPath()
    && applied.value === process.env.DEFAULT_DOWNLOAD_PATH;
  const value = (inherited ? config.DEFAULT_DOWNLOAD_PATH
    : process.env.DEFAULT_DOWNLOAD_PATH ?? config.DEFAULT_DOWNLOAD_PATH)?.trim();
  if (!value) return "./downloads";
  return value === "~" ? homedir() : value.startsWith("~/") || value.startsWith("~\\")
    ? join(homedir(), value.slice(2)) : value;
}

export function writeUserConfig(config: Record<string, string>): string {
  const filePath = getConfigPath();
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(filePath, `${JSON.stringify(config, null, 2)}\n`, {
    mode: 0o600,
  });
  chmodSync(filePath, 0o600);
  return filePath;
}

export function initUserConfig(force = false): {
  path: string;
  created: boolean;
} {
  const filePath = getConfigPath();
  if (existsSync(filePath) && !force) {
    chmodSync(filePath, 0o600);
    return { path: filePath, created: false };
  }
  writeUserConfig({});
  return { path: filePath, created: true };
}

export function setUserConfigValue(
  key: string,
  value: string,
): Record<string, string> {
  assertConfigKey(key);
  const config = readUserConfig();
  config[key] = value;
  writeUserConfig(config);
  followConfigWrite(key, value);
  return config;
}

export function unsetUserConfigValue(key: string): Record<string, string> {
  assertConfigKey(key);
  const config = readUserConfig();
  delete config[key];
  writeUserConfig(config);
  followConfigWrite(key, undefined);
  return config;
}

/**
 * A value this process copied from the config file (loadUserConfigIntoEnv)
 * follows a later write of that file; a value the environment set itself still
 * wins. Without it, setup reported the institutional extension disabled right
 * after installing it: the copy said false (review 2026-11-02).
 */
function followConfigWrite(key: string, value: string | undefined): void {
  const applied = APPLIED_FROM_USER_CONFIG.get(key);
  if (
    !applied ||
    applied.configPath !== getConfigPath() ||
    process.env[key] !== applied.value
  ) {
    return;
  }
  if (value === undefined) {
    delete process.env[key];
    APPLIED_FROM_USER_CONFIG.delete(key);
    return;
  }
  process.env[key] = value;
  APPLIED_FROM_USER_CONFIG.set(key, { configPath: applied.configPath, value });
}

export function importEnvFile(filePath: string): {
  path: string;
  imported: string[];
} {
  if (!existsSync(filePath)) throw new Error(`Env file not found: ${filePath}`);
  const parsed = dotenv.parse(readFileSync(filePath));
  const config = readUserConfig();
  const imported: string[] = [];

  for (const [key, value] of Object.entries(parsed)) {
    if (!CONFIG_KEY_SET.has(key)) continue;
    config[key] = value;
    imported.push(key);
  }

  writeUserConfig(config);
  return { path: getConfigPath(), imported };
}

export function loadUserConfigIntoEnv(): string[] {
  const config = readUserConfig();
  const configPath = getConfigPath();
  const applied: string[] = [];

  for (const [key, value] of Object.entries(config)) {
    if (process.env[key] !== undefined) continue;
    process.env[key] = value;
    APPLIED_FROM_USER_CONFIG.set(key, { configPath, value });
    applied.push(key);
  }

  return applied;
}

export function listConfigEntries(includeMissing = false): ConfigEntry[] {
  const config = readUserConfig();
  return CONFIG_KEYS.map((key) => {
    const { value, source } = effectiveConfigValue(key, config);

    return {
      key,
      configured: Boolean(value),
      source,
      value: value ? maskValue(key, value) : "",
    };
  }).filter((entry) => includeMissing || entry.configured);
}

function effectiveConfigValue(
  key: ConfigKey,
  config: Record<string, string>,
): Pick<ConfigEntry, "source" | "value"> {
  const environmentValue = process.env[key];
  if (environmentValue !== undefined) {
    const provenance = APPLIED_FROM_USER_CONFIG.get(key);
    const source =
      provenance?.configPath === getConfigPath() &&
      provenance.value === environmentValue &&
      config[key] === environmentValue
        ? "user_config"
        : "environment";
    return { value: environmentValue, source };
  }
  if (config[key] !== undefined) {
    return { value: config[key], source: "user_config" };
  }
  return { value: "", source: "missing" };
}

export function maskValue(key: string, value: string): string {
  if (!value) return "";
  if (
    key === "GOOGLE_SCHOLAR_PROXY_URL" ||
    key === "HTTP_PROXY" ||
    key === "HTTPS_PROXY"
  ) {
    return "***configured***";
  }
  if (key.toLowerCase().includes("email") || value.includes("@")) {
    const [name, domain] = value.split("@");
    if (!domain) return "***";
    return `${name.slice(0, 2)}***@${domain}`;
  }
  if (value.length <= 8) return "***";
  return `${value.slice(0, 4)}...${value.slice(-4)}`;
}

export function assertConfigKey(key: string): asserts key is ConfigKey {
  if (!CONFIG_KEY_SET.has(key)) {
    throw new Error(
      `Unsupported config key: ${key}. Run "paper-search config keys" to list supported keys.`,
    );
  }
}
