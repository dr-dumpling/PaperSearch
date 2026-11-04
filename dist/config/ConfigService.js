import * as dotenv from "dotenv";
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync, } from "fs";
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
];
const CONFIG_KEY_SET = new Set(CONFIG_KEYS);
const APPLIED_FROM_USER_CONFIG = new Map();
export function getConfigPath() {
    if (process.env.PAPER_SEARCH_CONFIG_FILE)
        return process.env.PAPER_SEARCH_CONFIG_FILE;
    const configDir = process.env.PAPER_SEARCH_CONFIG_DIR ||
        join(homedir(), ".config", "paper-search-cli");
    return join(configDir, "config.json");
}
export function readUserConfig() {
    const filePath = getConfigPath();
    if (!existsSync(filePath))
        return {};
    const parsed = JSON.parse(readFileSync(filePath, "utf8"));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error(`Invalid config file: ${filePath}`);
    }
    const config = {};
    for (const [key, value] of Object.entries(parsed)) {
        if (CONFIG_KEY_SET.has(key) && value !== undefined && value !== null) {
            config[key] = String(value);
        }
    }
    return config;
}
export function isConfigTrue(key) {
    return effectiveConfigValue(key, readUserConfig()).value === "true";
}
export function getConfigValue(key) {
    return effectiveConfigValue(key, readUserConfig()).value;
}
/** Resolve once at task start; GUI edits share the CLI config, not a second preference. */
export function resolveDownloadPath(explicit) {
    if (explicit?.trim())
        return explicit;
    const config = readUserConfig();
    const applied = APPLIED_FROM_USER_CONFIG.get("DEFAULT_DOWNLOAD_PATH");
    const inherited = applied?.configPath === getConfigPath()
        && applied.value === process.env.DEFAULT_DOWNLOAD_PATH;
    const value = (inherited ? config.DEFAULT_DOWNLOAD_PATH
        : process.env.DEFAULT_DOWNLOAD_PATH ?? config.DEFAULT_DOWNLOAD_PATH)?.trim();
    if (!value)
        return "./downloads";
    return value === "~" ? homedir() : value.startsWith("~/") || value.startsWith("~\\")
        ? join(homedir(), value.slice(2)) : value;
}
export function writeUserConfig(config) {
    const filePath = getConfigPath();
    mkdirSync(dirname(filePath), { recursive: true });
    writeFileSync(filePath, `${JSON.stringify(config, null, 2)}\n`, {
        mode: 0o600,
    });
    chmodSync(filePath, 0o600);
    return filePath;
}
export function initUserConfig(force = false) {
    const filePath = getConfigPath();
    if (existsSync(filePath) && !force) {
        chmodSync(filePath, 0o600);
        return { path: filePath, created: false };
    }
    writeUserConfig({});
    return { path: filePath, created: true };
}
export function setUserConfigValue(key, value) {
    assertConfigKey(key);
    const config = readUserConfig();
    config[key] = value;
    writeUserConfig(config);
    followConfigWrite(key, value);
    return config;
}
export function unsetUserConfigValue(key) {
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
function followConfigWrite(key, value) {
    const applied = APPLIED_FROM_USER_CONFIG.get(key);
    if (!applied ||
        applied.configPath !== getConfigPath() ||
        process.env[key] !== applied.value) {
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
export function importEnvFile(filePath) {
    if (!existsSync(filePath))
        throw new Error(`Env file not found: ${filePath}`);
    const parsed = dotenv.parse(readFileSync(filePath));
    const config = readUserConfig();
    const imported = [];
    for (const [key, value] of Object.entries(parsed)) {
        if (!CONFIG_KEY_SET.has(key))
            continue;
        config[key] = value;
        imported.push(key);
    }
    writeUserConfig(config);
    return { path: getConfigPath(), imported };
}
export function loadUserConfigIntoEnv() {
    const config = readUserConfig();
    const configPath = getConfigPath();
    const applied = [];
    for (const [key, value] of Object.entries(config)) {
        if (process.env[key] !== undefined)
            continue;
        process.env[key] = value;
        APPLIED_FROM_USER_CONFIG.set(key, { configPath, value });
        applied.push(key);
    }
    return applied;
}
export function listConfigEntries(includeMissing = false) {
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
function effectiveConfigValue(key, config) {
    const environmentValue = process.env[key];
    if (environmentValue !== undefined) {
        const provenance = APPLIED_FROM_USER_CONFIG.get(key);
        const source = provenance?.configPath === getConfigPath() &&
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
export function maskValue(key, value) {
    if (!value)
        return "";
    if (key === "GOOGLE_SCHOLAR_PROXY_URL" ||
        key === "HTTP_PROXY" ||
        key === "HTTPS_PROXY") {
        return "***configured***";
    }
    if (key.toLowerCase().includes("email") || value.includes("@")) {
        const [name, domain] = value.split("@");
        if (!domain)
            return "***";
        return `${name.slice(0, 2)}***@${domain}`;
    }
    if (value.length <= 8)
        return "***";
    return `${value.slice(0, 4)}...${value.slice(-4)}`;
}
export function assertConfigKey(key) {
    if (!CONFIG_KEY_SET.has(key)) {
        throw new Error(`Unsupported config key: ${key}. Run "paper-search config keys" to list supported keys.`);
    }
}
//# sourceMappingURL=ConfigService.js.map