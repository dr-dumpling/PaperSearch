#!/usr/bin/env node
import * as dotenv from "dotenv";
import { randomBytes } from "crypto";
import { readFileSync } from "fs";
import { createInterface as createPromiseInterface } from "readline/promises";
import { emitKeypressEvents } from "readline";
import { TOOLS } from "./core/tools.js";
import { initializeSearchers } from "./core/searchers.js";
import { handleToolCall } from "./core/handleToolCall.js";
import { diagnoseError, diagnoseToolResult, diagnosticContextFromCli, getRequirementStatus, } from "./management/diagnostics/index.js";
import { buildCapabilityProfile } from "./management/capability-profile/index.js";
import { resolveCarsiReadiness } from "./management/capability-profile/carsiReadiness.js";
import { createCarsiBackend, } from "./capabilities/pdf-discovery/carsi/index.js";
import { CONFIG_KEYS, getConfigPath, importEnvFile, initUserConfig, listConfigEntries, loadUserConfigIntoEnv, maskValue, readUserConfig, assertConfigKey, getConfigValue, setUserConfigValue, isConfigTrue, unsetUserConfigValue, } from "./management/config/index.js";
import { setupGlobalProxy } from "./infrastructure/http/HttpClient.js";
import { autoSyncSkill, defaultSkillTargetIds, describeSkillTargets, diffSkillTargets, installSkillTargets, parseSkillTargets, skillLocations, statusSkillTargets, } from "./management/skills/index.js";
import { renderDoctorTextReport, renderSkillDiffTextReport, } from "./management/reports/index.js";
import { renderFailuresText, summarizeFailures } from "./management/failures/index.js";
import { createNodeHost } from "./management/carsi/host.js";
import { InstallError, installCarsi, carsiStatus, renderStatusText, uninstallCarsi, updateCarsi, } from "./management/carsi/installer.js";
import { resolveDefaultCarsiProfileDir } from "./capabilities/pdf-discovery/carsi/index.js";
import { fileURLToPath } from "node:url";
import { resolveRunLogRoot } from "./infrastructure/runlog/RunLedger.js";
import { runLiveSmoke } from "./management/smoke/index.js";
dotenv.config();
loadUserConfigIntoEnv();
setupGlobalProxy();
class CliError extends Error {
    code;
    exitCode;
    constructor(message, code = "CLI_ERROR", exitCode = 1) {
        super(message);
        this.code = code;
        this.exitCode = exitCode;
        this.name = "CliError";
    }
}
const GLOBAL_FLAGS = new Set([
    "pretty",
    "format",
    "includeText",
    "include-text",
    "help",
    "h",
    "version",
    "v",
]);
function packageVersion() {
    const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
    return pkg.version || "0.0.0";
}
/** This package's own Skill, whatever the working directory. */
const PACKAGE_SKILL_ROOT = fileURLToPath(new URL("../skills/paper-search", import.meta.url));
function usage() {
    return `paper-search - PaperSearch, an agent-friendly academic paper search command

Usage:
  paper-search search <query> [--platform crossref] [--max-results 10] [--year 2024]
  paper-search search <query> [--sources crossref,openalex,pmc] [--max-results 10]
  paper-search search <query> [--sources no-key] [--max-results 10]
  paper-search journal-metrics <journal...> [--include-raw]
  paper-search run <tool-name> --json-args '{"query":"machine learning","maxResults":5}'
  paper-search status [--validate]
  paper-search doctor [--validate]
  paper-search failures [--run <id>|latest] [--since 2026-11-01] [--runs 5] [--all]
  paper-search carsi <install|status> [--browser camoufox|ego] [--yes] [--force] [--skip-school]
  paper-search carsi update [--force]
  paper-search carsi uninstall [--yes] [--remove-browser] [--remove-data]
  paper-search smoke --mock|--live
  paper-search skills <status|update|diff> [--targets agents,codex]
  paper-search tools
  paper-search diagnostics
  paper-search config <init|set|get|unset|list|doctor|path|import-env|keys>
  paper-search setup [--all] [--install-skills agents,codex] [--skip-skills] [--skip-carsi|--install-carsi]
  paper-search download <paper-id> --platform pmc [--save-path ./downloads]

Global flags:
  --pretty         Pretty-print JSON output
  --format text    Print only the human-readable tool text
  --include-text   Include raw tool response text in JSON output
  --version, -v    Print the CLI version

Examples:
  paper-search search "large language model evaluation" --platform crossref --max-results 5 --pretty
  paper-search search "machine learning" --sources crossref,openalex --max-results 2 --pretty
  paper-search search "machine learning" --sources no-key --max-results 5 --pretty
  paper-search journal-metrics "Nature" "BMJ" --pretty
  paper-search setup
  paper-search config set SEMANTIC_SCHOLAR_API_KEY sk_xxx
  paper-search run search_pubmed --arg query="osteoarthritis occupational exposure" --arg maxResults=3
  paper-search doctor --pretty
  paper-search doctor --format text
  paper-search failures --format text
  paper-search skills status --pretty
  paper-search skills diff --format text
`;
}
function parseCli(argv) {
    if (argv[0] === "--help" || argv[0] === "-h") {
        return { command: "help", positionals: [], flags: { help: true } };
    }
    if (argv[0] === "--version" || argv[0] === "-v") {
        return { command: "version", positionals: [], flags: { version: true } };
    }
    const [command = "help", ...rest] = argv;
    const flags = {};
    const positionals = [];
    for (let i = 0; i < rest.length; i += 1) {
        const token = rest[i];
        if (token === "--") {
            positionals.push(...rest.slice(i + 1));
            break;
        }
        if (token.startsWith("--")) {
            const withoutPrefix = token.slice(2);
            const eqIndex = withoutPrefix.indexOf("=");
            const rawKey = eqIndex >= 0 ? withoutPrefix.slice(0, eqIndex) : withoutPrefix;
            const key = toCamelKey(rawKey);
            let value = true;
            if (eqIndex >= 0) {
                value = withoutPrefix.slice(eqIndex + 1);
            }
            else if (rest[i + 1] && !rest[i + 1].startsWith("-")) {
                value = rest[i + 1];
                i += 1;
            }
            if (key === "arg") {
                const existing = flags.arg;
                flags.arg = Array.isArray(existing)
                    ? [...existing, String(value)]
                    : [String(value)];
            }
            else {
                flags[key] = value;
            }
            continue;
        }
        if (token.startsWith("-") && token.length > 1) {
            if (token === "-h") {
                flags.help = true;
                continue;
            }
            if (token === "-v") {
                flags.version = true;
                continue;
            }
            throw new CliError(`Unsupported short flag: ${token}`, "UNSUPPORTED_FLAG");
        }
        positionals.push(token);
    }
    return { command, positionals, flags };
}
function toCamelKey(key) {
    return key.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
}
function coerceValue(value) {
    if (typeof value === "boolean")
        return value;
    if (value === "true")
        return true;
    if (value === "false")
        return false;
    if (value === "null")
        return null;
    if (/^-?\d+(\.\d+)?$/.test(value))
        return Number(value);
    if ((value.startsWith("{") && value.endsWith("}")) ||
        (value.startsWith("[") && value.endsWith("]"))) {
        return JSON.parse(value);
    }
    return value;
}
function parseJsonArgs(value) {
    if (!value)
        return {};
    if (typeof value !== "string") {
        throw new CliError("--json-args expects a JSON string or @file path", "INVALID_JSON_ARGS");
    }
    const raw = value.startsWith("@")
        ? readFileSync(value.slice(1), "utf8")
        : value;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new CliError("--json-args must decode to a JSON object", "INVALID_JSON_ARGS");
    }
    return parsed;
}
function parseArgFlags(value) {
    if (!value)
        return {};
    const entries = Array.isArray(value) ? value : [String(value)];
    const args = {};
    for (const entry of entries) {
        const eqIndex = entry.indexOf("=");
        if (eqIndex <= 0) {
            throw new CliError(`--arg must use key=value form: ${entry}`, "INVALID_ARG");
        }
        const key = toCamelKey(entry.slice(0, eqIndex));
        const rawValue = entry.slice(eqIndex + 1);
        const stringKeys = new Set([
            "paperId",
            "doi",
            "doiOrUrl",
            "source",
            "title",
            "savePath",
        ]);
        args[key] = stringKeys.has(key) ? rawValue : coerceValue(rawValue);
    }
    return args;
}
function flagsToArgs(flags) {
    const args = {};
    for (const [key, value] of Object.entries(flags)) {
        if (GLOBAL_FLAGS.has(key) || key === "arg" || key === "jsonArgs")
            continue;
        args[key] = coerceValue(value === true ? "true" : String(value));
    }
    return args;
}
function formatOutput(payload, flags) {
    return JSON.stringify(payload, null, flags.pretty ? 2 : 0);
}
function prepareOutput(result) {
    if (!result || typeof result !== "object" || Array.isArray(result)) {
        return { payload: result };
    }
    const exitCode = result.exitCode;
    if (typeof exitCode !== "number") {
        return { payload: result };
    }
    const { exitCode: _exitCode, ...payload } = result;
    return { payload, exitCode };
}
function extractText(response) {
    const content = response?.content;
    if (!Array.isArray(content))
        return "";
    return content
        .filter((item) => item?.type === "text")
        .map((item) => String(item.text || ""))
        .join("\n");
}
function extractFirstJsonValue(text) {
    const start = text.search(/[\[{]/);
    if (start < 0)
        return undefined;
    const open = text[start];
    const close = open === "[" ? "]" : "}";
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let i = start; i < text.length; i += 1) {
        const char = text[i];
        if (inString) {
            if (escaped) {
                escaped = false;
            }
            else if (char === "\\") {
                escaped = true;
            }
            else if (char === '"') {
                inString = false;
            }
            continue;
        }
        if (char === '"') {
            inString = true;
            continue;
        }
        if (char === open)
            depth += 1;
        if (char === close)
            depth -= 1;
        if (depth === 0) {
            return JSON.parse(text.slice(start, i + 1));
        }
    }
    return undefined;
}
function firstLine(text) {
    return (text
        .split("\n")
        .find((line) => line.trim())
        ?.trim() || "");
}
async function callTool(tool, args, flags) {
    const searchers = initializeSearchers();
    const carsiBackend = carsiBackendForToolCall(tool, args);
    const response = await handleToolCall(tool, args, searchers, {
        carsiBackend,
    });
    const text = extractText(response);
    if (flags.format === "text") {
        return text;
    }
    const payload = {
        ok: !response?.isError,
        tool,
        message: firstLine(text),
        data: extractFirstJsonValue(text),
    };
    const diagnostic = diagnoseToolResult({
        tool,
        args,
        platform: typeof args.platform === "string" ? args.platform : undefined,
        sources: typeof args.sources === "string" ? args.sources : undefined,
        data: payload.data,
        message: String(payload.message || ""),
    });
    if (diagnostic) {
        payload.diagnostic = diagnostic;
    }
    if (flags.includeText) {
        payload.text = text;
    }
    return payload;
}
function carsiBackendForToolCall(tool, args) {
    const isDownloadTool = tool === "download_paper" ||
        tool === "download_with_fallback" ||
        tool === "download_batch";
    if (!isDownloadTool ||
        args.useEntitledAccess === false ||
        !isConfigTrue("PAPER_SEARCH_CARSI_ENABLED")) {
        return undefined;
    }
    const backend = createCarsiBackend();
    return {
        probe: (signal) => backend.probe(signal),
        reportBatchProgress: async (update, signal) => (await backend.reportBatchProgress?.(update, signal)) ?? false,
        downloadLegalDoi: async (request) => {
            const controller = new AbortController();
            const cancel = () => controller.abort();
            process.once("SIGINT", cancel);
            process.once("SIGTERM", cancel);
            if (process.stderr.isTTY) {
                process.stderr.write("正在通过 CARSI 获取全文；若浏览器要求登录或安全验证，请在窗口中完成。\n");
            }
            try {
                return await backend.downloadLegalDoi({
                    ...request,
                    signal: controller.signal,
                    onProgress: (progress) => {
                        process.stderr.write(`[CARSI] ${progress.message}\n`);
                        request.onProgress?.(progress);
                    },
                });
            }
            finally {
                process.removeListener("SIGINT", cancel);
                process.removeListener("SIGTERM", cancel);
            }
        },
    };
}
function getToolNames() {
    return TOOLS.map((tool) => tool.name);
}
function assertToolName(tool) {
    if (!getToolNames().includes(tool)) {
        throw new CliError(`Unknown tool: ${tool}. Run "paper-search tools" to list tools.`, "UNKNOWN_TOOL");
    }
}
async function run(parsed) {
    const { command, positionals, flags } = parsed;
    if (flags.help || command === "help") {
        return usage();
    }
    if (flags.version || command === "version") {
        return packageVersion();
    }
    if (command === "tools") {
        return {
            ok: true,
            tools: TOOLS.map((tool) => ({
                name: tool.name,
                description: tool.description,
                inputSchema: tool.inputSchema,
            })),
        };
    }
    if (command === "diagnostics" || command === "requirements") {
        return {
            ok: true,
            requirements: getRequirementStatus(),
        };
    }
    if (command === "smoke") {
        return handleSmokeCommand(flags);
    }
    if (command === "skills") {
        return handleSkillsCommand(positionals, flags);
    }
    if (command === "config") {
        return handleConfigCommand(positionals, flags);
    }
    if (command === "setup") {
        return handleSetupCommand(positionals, flags);
    }
    if (command === "doctor") {
        return handleDoctorCommand(flags);
    }
    if (command === "failures") {
        return handleFailuresCommand(flags);
    }
    if (command === "carsi") {
        return handleCarsiCommand(positionals, flags);
    }
    if (command === "status") {
        return callTool("get_platform_status", { validate: flags.validate === true }, flags);
    }
    if (command === "search") {
        const query = typeof flags.query === "string"
            ? flags.query
            : positionals.join(" ").trim();
        if (!query) {
            throw new CliError("Missing search query", "MISSING_QUERY");
        }
        const args = {
            ...flagsToArgs(flags),
            query,
        };
        return callTool("search_papers", args, flags);
    }
    if (command === "download") {
        const paperId = typeof flags.paperId === "string" ? flags.paperId : positionals[0];
        if (!paperId)
            throw new CliError("Missing paper id", "MISSING_PAPER_ID");
        if (!flags.platform)
            throw new CliError("Missing --platform", "MISSING_PLATFORM");
        return callTool("download_paper", {
            ...flagsToArgs(flags),
            paperId,
        }, flags);
    }
    if (command === "journal-metrics" || command === "metrics") {
        const journals = typeof flags.journals === "string"
            ? flags.journals
            : positionals.join("\n").trim();
        const file = typeof flags.file === "string" ? flags.file : undefined;
        if (!journals && !file) {
            throw new CliError("Missing journal name or --file", "MISSING_JOURNAL");
        }
        return callTool("query_journal_metrics", {
            ...flagsToArgs(flags),
            journals,
            file,
        }, flags);
    }
    if (command === "run") {
        const tool = positionals[0];
        if (!tool)
            throw new CliError("Missing tool name", "MISSING_TOOL");
        assertToolName(tool);
        const args = {
            ...parseJsonArgs(flags.jsonArgs),
            ...parseArgFlags(flags.arg),
            ...flagsToArgs(flags),
        };
        return callTool(tool, args, flags);
    }
    throw new CliError(`Unknown command: ${command}`, "UNKNOWN_COMMAND");
}
function handleConfigCommand(positionals, flags) {
    const subcommand = positionals[0] || "list";
    if (subcommand === "path") {
        return { ok: true, path: getConfigPath() };
    }
    if (subcommand === "keys") {
        return { ok: true, keys: CONFIG_KEYS };
    }
    if (subcommand === "init") {
        const result = initUserConfig(flags.force === true);
        return { ok: true, ...result };
    }
    if (subcommand === "list") {
        return {
            ok: true,
            path: getConfigPath(),
            entries: listConfigEntries(flags.all === true),
        };
    }
    if (subcommand === "doctor") {
        const entries = listConfigEntries(true);
        return {
            ok: true,
            path: getConfigPath(),
            message: "Use `paper-search doctor --pretty` for capability and health checks.",
            configured: entries.filter((entry) => entry.configured).length,
            missing: entries
                .filter((entry) => !entry.configured)
                .map((entry) => entry.key),
            entries,
        };
    }
    if (subcommand === "get") {
        const key = positionals[1];
        if (!key)
            throw new CliError("Missing config key", "MISSING_CONFIG_KEY");
        assertConfigKey(key);
        const entry = listConfigEntries(true).find((item) => item.key === key);
        const value = process.env[key] || readUserConfig()[key] || "";
        return {
            ok: true,
            key,
            configured: Boolean(value),
            value: flags.raw === true ? value : maskValue(key, value),
            source: entry?.source || "missing",
        };
    }
    if (subcommand === "set") {
        const parsed = parseConfigAssignment(positionals.slice(1), flags);
        setUserConfigValue(parsed.key, parsed.value);
        process.env[parsed.key] = parsed.value;
        return {
            ok: true,
            path: getConfigPath(),
            key: parsed.key,
            value: maskValue(parsed.key, parsed.value),
        };
    }
    if (subcommand === "unset" ||
        subcommand === "delete" ||
        subcommand === "remove") {
        const key = positionals[1];
        if (!key)
            throw new CliError("Missing config key", "MISSING_CONFIG_KEY");
        unsetUserConfigValue(key);
        return { ok: true, path: getConfigPath(), key, removed: true };
    }
    if (subcommand === "import-env") {
        const envPath = positionals[1] || (typeof flags.file === "string" ? flags.file : ".env");
        const result = importEnvFile(envPath);
        return {
            ok: true,
            path: result.path,
            imported: result.imported,
            count: result.imported.length,
        };
    }
    throw new CliError(`Unknown config command: ${subcommand}`, "UNKNOWN_CONFIG_COMMAND");
}
const AUTO_EMAIL_CONFIG_KEYS = new Set([
    "PAPER_SEARCH_UNPAYWALL_EMAIL",
    "UNPAYWALL_EMAIL",
    "CROSSREF_MAILTO",
]);
const DEFAULT_SETUP_PROMPTS = [
    {
        key: "SEMANTIC_SCHOLAR_API_KEY",
        label: "Semantic Scholar API key, required for search_semantic_snippets",
        secret: true,
    },
    {
        key: "PAPER_SEARCH_UNPAYWALL_EMAIL",
        label: "Unpaywall email, recommended for open-access DOI lookup",
        secret: false,
    },
    {
        key: "CROSSREF_MAILTO",
        label: "Crossref contact email, recommended for polite API access",
        secret: false,
    },
    {
        key: "CORE_API_KEY",
        label: "CORE API key, optional but recommended for stable CORE access",
        secret: true,
    },
    {
        key: "EASYSCHOLAR_KEY",
        label: "EasyScholar SecretKey, required for journal metrics (IF/JCR/CAS)",
        secret: true,
    },
    {
        key: "PAPER_SEARCH_CARSI_ENABLED",
        label: "Institutional download extension switch, set by paper-search carsi install; enter true only once the extension is installed",
        secret: false,
    },
];
function setupPromptsFor(flags, positionals) {
    const keysFlag = typeof flags.keys === "string" ? flags.keys : positionals[0];
    if (keysFlag) {
        return keysFlag
            .split(",")
            .map((key) => key.trim())
            .filter(Boolean)
            .map((key) => {
            assertConfigKey(key);
            return { key, label: key, secret: isSecretConfigKey(key) };
        });
    }
    if (flags.all === true) {
        return CONFIG_KEYS.map((key) => ({
            key,
            label: key,
            secret: isSecretConfigKey(key),
        }));
    }
    return DEFAULT_SETUP_PROMPTS;
}
function isSecretConfigKey(key) {
    const normalized = key.toLowerCase();
    return (normalized.includes("key") ||
        normalized.includes("token") ||
        normalized.includes("proxy"));
}
async function handleSetupCommand(positionals, flags) {
    const { path } = initUserConfig(false);
    const prompts = setupPromptsFor(flags, positionals);
    const entries = new Map(listConfigEntries(true).map((entry) => [entry.key, entry]));
    const session = new PromptSession();
    const updated = [];
    const kept = [];
    const skipped = [];
    const autoGenerated = [];
    let defaultEmail = "";
    const skillsRoot = typeof flags.skillsRoot === "string" ? flags.skillsRoot : undefined;
    const skipSkills = flags.skipSkills === true;
    const explicitSkillTargets = typeof flags.installSkills === "string"
        ? parseSkillTargets(flags.installSkills, skillsRoot)
        : undefined;
    process.stderr.write(`PaperSearch setup\n`);
    process.stderr.write(`Config file: ${path}\n`);
    process.stderr.write(`Press Enter to keep an existing value or skip an optional value.\n`);
    process.stderr.write(`For Unpaywall/Crossref email fields, Enter auto-generates a random Gmail-format address.\n\n`);
    try {
        for (const prompt of prompts) {
            const entry = entries.get(prompt.key);
            const current = entry?.configured
                ? ` current=${entry.value} source=${entry.source}`
                : " not configured";
            const question = `${prompt.label}\n${prompt.key} (${current})`;
            const answer = prompt.secret
                ? await session.secret(question)
                : await session.line(`${question}: `);
            const value = answer.trim();
            if (!value) {
                if (entry?.configured) {
                    kept.push(prompt.key);
                }
                else if (AUTO_EMAIL_CONFIG_KEYS.has(prompt.key)) {
                    defaultEmail ||= randomCommonEmail();
                    setUserConfigValue(prompt.key, defaultEmail);
                    process.env[prompt.key] = defaultEmail;
                    updated.push(prompt.key);
                    autoGenerated.push(prompt.key);
                }
                else {
                    skipped.push(prompt.key);
                }
                continue;
            }
            setUserConfigValue(prompt.key, value);
            process.env[prompt.key] = value;
            updated.push(prompt.key);
        }
        let selectedSkillTargets = [];
        if (!skipSkills) {
            if (explicitSkillTargets) {
                selectedSkillTargets = explicitSkillTargets;
            }
            else {
                selectedSkillTargets = await promptSkillTargets(session, skillsRoot);
            }
        }
        const skillDestinations = describeSkillTargets(selectedSkillTargets, skillsRoot);
        const skillResult = selectedSkillTargets.length > 0
            ? installSkillTargets(selectedSkillTargets, { skillsRoot })
            : undefined;
        const carsi = await offerCarsiInstall(session, flags);
        const carsiReadiness = await resolveCarsiReadiness(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED"));
        const capabilityProfile = buildCapabilityProfile({ carsiReadiness });
        const nextSteps = [
            'Run "paper-search doctor --pretty" to review capability and platform health.',
            'Run "paper-search smoke --mock --pretty" for an offline self-check.',
            'Run "paper-search search \\"machine learning\\" --platform crossref --max-results 1 --pretty" for a no-key search check.',
            ...(carsi.installed
                ? []
                : ['Run "paper-search carsi install" to download papers through your school\'s subscription.']),
        ];
        return {
            ok: skillResult ? skillResult.ok : true,
            path,
            updated,
            kept,
            skipped,
            autoGenerated,
            capabilityProfile,
            skills: {
                skipped: skipSkills || selectedSkillTargets.length === 0,
                destinations: skillDestinations,
                result: skillResult,
            },
            carsi,
            nextSteps,
        };
    }
    finally {
        session.close();
    }
}
/**
 * Setup's last question (ADR 0013): install the institutional download
 * extension. Not asked when it is installed already or with
 * --skip-carsi; --install-carsi installs without asking.
 */
async function offerCarsiInstall(session, flags) {
    const host = createNodeHost((question) => session.line(question));
    const context = carsiContext();
    if ((await carsiStatus(host, context)).complete)
        return { installed: true, asked: false };
    if (flags.skipCarsi === true)
        return { installed: false, asked: false };
    const answer = flags.installCarsi === true
        ? "y"
        : await session.line("Install the institutional download extension? It downloads papers through your school's subscription in a browser (about 3 GB to download). [y/N]: ");
    if (!/^y(es)?$/i.test(answer.trim()))
        return { installed: false, asked: true };
    try {
        const outcome = await installCarsi(
        // Confirmed by setup's question or by --install-carsi: not asked again (an agent's
        // setup without a terminal cancelled itself here, review 2026-11-02).
        host, { browser: "camoufox", yes: false, confirmed: true, force: false, skipSchool: false }, context);
        return { installed: outcome.status === "installed", asked: true, outcome: outcome.status };
    }
    catch (error) {
        if (!(error instanceof InstallError))
            throw error;
        return {
            installed: false, asked: true, error: error.message,
            hint: "处理后再运行 paper-search carsi install，会从这一步接着装。",
        };
    }
}
function carsiContext() {
    return {
        packageRoot: fileURLToPath(new URL("..", import.meta.url)),
        paperSearchVersion: packageVersion(),
        dataDir: resolveDefaultCarsiProfileDir(),
        getConfig: (key) => getConfigValue(key),
        setConfig: (key, value) => {
            setUserConfigValue(key, value);
        },
        unsetConfig: (key) => {
            unsetUserConfigValue(key);
        },
        readiness: (executable) => resolveCarsiReadiness(true, () => createCarsiBackend(executable)),
        now: () => new Date(),
    };
}
/** Install or inspect the institutional download extension (ADR 0013). */
async function handleCarsiCommand(positionals, flags) {
    const sub = positionals[0];
    let session;
    const host = createNodeHost((question) => {
        session ??= new PromptSession();
        return session.line(question);
    });
    const context = carsiContext();
    try {
        if (sub === "install") {
            if (flags.browser !== undefined && flags.browser !== "camoufox" && flags.browser !== "ego") {
                return { ok: false, error: "--browser 只能是 camoufox 或 ego" };
            }
            const browser = flags.browser === "ego" ? "ego" : "camoufox";
            const outcome = await installCarsi(host, {
                browser,
                yes: flags.yes === true,
                force: flags.force === true,
                skipSchool: flags.skipSchool === true,
            }, context);
            if (outcome.status === "installed") {
                host.log("安装完成，机构下载已启用。第一次下载时，在弹出的浏览器里登录学校。");
                if (browser === "ego") {
                    host.log("用 ego 前，请在 ego 里打开 chrome://inspect/#remote-debugging，勾选 “Allow remote debugging for this browser instance”。");
                }
            }
            const status = await carsiStatus(host, context);
            return flags.format === "text"
                ? renderStatusText(status)
                : { ok: outcome.status !== "cancelled", outcome: outcome.status, ...status };
        }
        if (sub === "status") {
            const status = await carsiStatus(host, context);
            return flags.format === "text" ? renderStatusText(status) : { ok: true, ...status };
        }
        if (sub === "update") {
            const outcome = await updateCarsi(host, { force: flags.force === true }, context);
            if (outcome.status === "updated")
                host.log("更新完成。");
            const status = await carsiStatus(host, context);
            return flags.format === "text"
                ? renderStatusText(status)
                : { ok: true, outcome: outcome.status, ...status };
        }
        if (sub === "uninstall") {
            const outcome = await uninstallCarsi(host, {
                yes: flags.yes === true,
                removeBrowser: flags.removeBrowser === true,
                removeData: flags.removeData === true,
            }, context);
            if (flags.format === "text") {
                return [
                    outcome.status === "uninstalled" ? "已卸载机构下载扩展。" : outcome.status === "cancelled" ? "已取消。" : "没有安装。",
                    ...outcome.removed.map((item) => `  已删除：${item}`),
                    ...outcome.kept.map((item) => `  保留：${item}`),
                ].join("\n");
            }
            return { ok: outcome.status !== "cancelled", ...outcome };
        }
        return {
            ok: false,
            error: "用法：paper-search carsi <install|status|update|uninstall>（见 paper-search --help）",
        };
    }
    catch (error) {
        if (error instanceof InstallError) {
            return {
                ok: false,
                step: error.step,
                error: error.message,
                log: error.logFile,
                hint: "处理后再运行 paper-search carsi install，会从这一步接着装。",
            };
        }
        throw error;
    }
    finally {
        session?.close();
    }
}
/** Failed institutional downloads from the run ledgers, by class (ADR 0012). */
function handleFailuresCommand(flags) {
    const root = resolveRunLogRoot();
    if (!root) {
        return { ok: false, error: "运行记录已关闭（PAPER_SEARCH_RUNLOG=0），没有可汇总的失败。" };
    }
    const summary = summarizeFailures(root, {
        ...(typeof flags.run === "string" ? { run: flags.run } : {}),
        ...(typeof flags.since === "string" ? { since: flags.since } : {}),
        ...(typeof flags.runs === "string" && Number(flags.runs) > 0 ? { runs: Number(flags.runs) } : {}),
    });
    if (flags.format === "text") {
        return renderFailuresText(summary, { all: flags.all === true });
    }
    return { ok: true, ...summary };
}
async function handleDoctorCommand(flags) {
    const platformStatus = await callTool("get_platform_status", { validate: flags.validate === true }, {});
    const configEntries = listConfigEntries(true);
    const carsiReadiness = await resolveCarsiReadiness(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED"));
    const capabilityProfile = buildCapabilityProfile({ carsiReadiness });
    const extension = await carsiStatus(createNodeHost(() => Promise.resolve("")), carsiContext());
    const report = {
        ok: true,
        skills: skillReport(),
        carsi: {
            installed: extension.installed,
            complete: extension.complete,
            enabled: extension.enabled,
            upToDate: extension.upToDate,
            usesThisInstall: extension.usesThisInstall,
            notes: extension.notes,
        },
        config: {
            path: getConfigPath(),
            configured: configEntries.filter((entry) => entry.configured).length,
            missing: configEntries
                .filter((entry) => !entry.configured)
                .map((entry) => entry.key),
            entries: configEntries,
        },
        capabilityProfile,
        platformStatus,
    };
    if (flags.format === "text") {
        return renderDoctorTextReport(report);
    }
    return report;
}
/** The installed copies of the Skill and whether they follow upgrades, for doctor. */
function skillReport() {
    const autoUpdate = getConfigValue("PAPER_SEARCH_SKILL_AUTO_UPDATE") !== "false";
    try {
        return {
            autoUpdate,
            locations: skillLocations({ sourceRoot: PACKAGE_SKILL_ROOT }),
        };
    }
    catch (error) {
        return {
            autoUpdate,
            locations: [],
            error: error?.message || String(error),
        };
    }
}
async function handleSmokeCommand(flags) {
    const mode = typeof flags.mode === "string"
        ? flags.mode
        : flags.live === true
            ? "live"
            : "mock";
    if (flags.live === true || mode === "live") {
        const carsiReadiness = await resolveCarsiReadiness(isConfigTrue("PAPER_SEARCH_CARSI_ENABLED"));
        const capabilityProfile = buildCapabilityProfile({ carsiReadiness });
        const skillsRoot = typeof flags.skillsRoot === "string" ? flags.skillsRoot : undefined;
        const skillStatus = statusSkillTargets(defaultSkillTargetIds(skillsRoot), {
            skillsRoot,
        });
        return runLiveSmoke({
            capabilityProfile,
            carsiReadiness,
            skillStatus,
            hasConfig: (key) => Boolean(process.env[key] || readUserConfig()[key]),
            callTool: (tool, args) => callTool(tool, args, {}),
        });
    }
    const capabilityProfile = buildCapabilityProfile();
    const skillStatus = statusSkillTargets(defaultSkillTargetIds(typeof flags.skillsRoot === "string" ? flags.skillsRoot : undefined), {
        skillsRoot: typeof flags.skillsRoot === "string" ? flags.skillsRoot : undefined,
    });
    const cases = [
        {
            name: "metadata_search excludes Sci-Hub",
            ok: !capabilityProfile.entries
                .find((entry) => entry.id === "metadata_search")
                ?.configured.includes("scihub"),
        },
        {
            name: "citation_expansion uses Semantic Scholar Graph API",
            ok: capabilityProfile.entries
                .find((entry) => entry.id === "citation_expansion")
                ?.configured.includes("semantic_scholar_graph") === true,
        },
        {
            name: "pdf_discovery has source groups",
            ok: Boolean(capabilityProfile.entries.find((entry) => entry.id === "pdf_discovery")?.sourceGroups?.open_access_sources) &&
                Boolean(capabilityProfile.entries.find((entry) => entry.id === "pdf_discovery")?.sourceGroups?.entitled_access_sources) &&
                Boolean(capabilityProfile.entries.find((entry) => entry.id === "pdf_discovery")?.sourceGroups?.scihub_sources),
        },
        {
            name: "journal_metrics uses EASYSCHOLAR_KEY",
            ok: capabilityProfile.entries
                .find((entry) => entry.id === "journal_metrics")
                ?.requiredKeys?.join(",") === "EASYSCHOLAR_KEY",
        },
        {
            name: "skill status runs offline",
            ok: skillStatus.ok,
        },
    ];
    const failed = cases.filter((item) => !item.ok);
    return {
        ok: failed.length === 0,
        mode: "mock",
        cases,
        failedCases: failed,
        capabilityProfile,
        skillStatus,
    };
}
function handleSkillsCommand(positionals, flags) {
    const subcommand = positionals[0] || "status";
    const skillsRoot = typeof flags.skillsRoot === "string" ? flags.skillsRoot : undefined;
    const sourceRoot = typeof flags.sourceRoot === "string" ? flags.sourceRoot : undefined;
    const targetIds = flags.all === true
        ? parseSkillTargets("all", skillsRoot)
        : parseSkillTargets(typeof flags.targets === "string" ? flags.targets : "", skillsRoot);
    if (subcommand === "status") {
        return statusSkillTargets(targetIds, { skillsRoot, sourceRoot });
    }
    if (subcommand === "update") {
        return installSkillTargets(targetIds, { skillsRoot, sourceRoot });
    }
    if (subcommand === "diff") {
        const result = diffSkillTargets(targetIds, { skillsRoot, sourceRoot });
        if (flags.format === "text") {
            return renderSkillDiffTextReport(result);
        }
        return result;
    }
    throw new CliError(`Unknown skills command: ${subcommand}`, "UNKNOWN_SKILLS_COMMAND");
}
async function promptSkillTargets(session, skillsRoot) {
    const defaults = defaultSkillTargetIds(skillsRoot);
    const destinations = describeSkillTargets(defaults, skillsRoot);
    process.stderr.write("\n[Optional] Install paper-search Skill\n");
    process.stderr.write("Purpose: teach local AI agents to use paper-search CLI for literature tasks.\n");
    process.stderr.write("Detected destinations:\n");
    for (const item of destinations) {
        process.stderr.write(`  ${item.target.padEnd(12)} ${item.path}\n`);
    }
    const answer = await session.line(`Install targets [agents/codex/claude/cursor/gemini/antigravity/all/skip] (${defaults.join(",")}): `);
    if (!answer.trim())
        return defaults;
    return parseSkillTargets(answer, skillsRoot);
}
function randomCommonEmail() {
    return `paper.search.${randomBytes(6).toString("hex")}@gmail.com`;
}
class PromptSession {
    rl;
    scriptedAnswers;
    constructor() {
        if (!process.stdin.isTTY) {
            this.scriptedAnswers = readFileSync(0, "utf8").split(/\r?\n/);
        }
    }
    async line(question) {
        if (this.scriptedAnswers) {
            process.stderr.write(question);
            const answer = this.scriptedAnswers.shift() || "";
            process.stderr.write("\n");
            return answer;
        }
        this.rl ??= createPromiseInterface({
            input: process.stdin,
            output: process.stderr,
        });
        return this.rl.question(question);
    }
    async secret(question) {
        if (!process.stdin.isTTY ||
            !process.stderr.isTTY ||
            typeof process.stdin.setRawMode !== "function") {
            return this.line(`${question}: `);
        }
        this.close();
        return readHiddenLine(`${question}: `);
    }
    close() {
        this.rl?.close();
        this.rl = undefined;
    }
}
function readHiddenLine(question) {
    return new Promise((resolve, reject) => {
        let value = "";
        const stdin = process.stdin;
        const wasRaw = stdin.isRaw;
        const cleanup = () => {
            stdin.off("keypress", onKeypress);
            if (!wasRaw)
                stdin.setRawMode(false);
            stdin.pause();
        };
        const onKeypress = (text, key) => {
            if (key?.ctrl && key.name === "c") {
                cleanup();
                process.stderr.write("\n");
                reject(new CliError("Interrupted", "INTERRUPTED", 130));
                return;
            }
            if (key?.name === "return" || key?.name === "enter") {
                cleanup();
                process.stderr.write("\n");
                resolve(value);
                return;
            }
            if (key?.name === "backspace" || key?.name === "delete") {
                if (value.length > 0) {
                    value = value.slice(0, -1);
                    process.stderr.write("\b \b");
                }
                return;
            }
            if (text && !key?.ctrl && !key?.meta) {
                value += text;
                process.stderr.write("*");
            }
        };
        process.stderr.write(question);
        emitKeypressEvents(stdin);
        stdin.setRawMode(true);
        stdin.resume();
        stdin.on("keypress", onKeypress);
    });
}
function parseConfigAssignment(positionals, flags) {
    const first = positionals[0];
    if (!first)
        throw new CliError("Missing config assignment", "MISSING_CONFIG_ASSIGNMENT");
    const eqIndex = first.indexOf("=");
    if (eqIndex > 0) {
        return {
            key: first.slice(0, eqIndex),
            value: first.slice(eqIndex + 1),
        };
    }
    const value = positionals[1] ?? flags.value;
    if (typeof value !== "string") {
        throw new CliError('Missing config value. Use "paper-search config set KEY VALUE".', "MISSING_CONFIG_VALUE");
    }
    return { key: first, value };
}
async function main() {
    const parsed = parseCli(process.argv.slice(2));
    try {
        maybePrintSetupHint(parsed);
        maybeAutoSyncSkill(parsed);
        const result = await run(parsed);
        const output = prepareOutput(result);
        if (typeof output.exitCode === "number") {
            process.exitCode = output.exitCode;
        }
        if (typeof output.payload === "string") {
            process.stdout.write(`${output.payload}\n`);
        }
        else {
            process.stdout.write(`${formatOutput(output.payload, parsed.flags)}\n`);
        }
    }
    catch (error) {
        const diagnostic = diagnoseError(error, diagnosticContextFromCli(parsed.command, parsed.positionals, parsed.flags));
        const errorPayload = {
            name: error?.name || "Error",
            code: error?.code || "ERROR",
            message: error?.message || String(error),
        };
        const payload = {
            ok: false,
            error: errorPayload,
        };
        if (diagnostic) {
            payload.diagnostic = diagnostic;
        }
        process.stderr.write(`${errorPayload.message}\n`);
        if (diagnostic) {
            process.stderr.write(`Diagnostic: ${diagnostic.summary}\n`);
            if (diagnostic.actions[0]) {
                process.stderr.write(`Next: ${diagnostic.actions[0]}\n`);
            }
        }
        process.stdout.write(`${formatOutput(payload, parsed.flags)}\n`);
        process.exitCode = error?.exitCode || 1;
    }
}
function maybePrintSetupHint(parsed) {
    if (process.env.PAPER_SEARCH_HIDE_SETUP_HINT === "1")
        return;
    if (parsed.command !== "status" && parsed.command !== "doctor")
        return;
    if (listConfigEntries(false).length > 0)
        return;
    process.stderr.write([
        "No PaperSearch API credentials are configured yet.",
        "Free metadata search still works, but body-snippet search and higher provider limits need optional keys.",
        'Run "paper-search setup" to add keys, or "paper-search doctor --pretty" to inspect config and capabilities.',
        "",
    ].join("\n"));
}
const SKILL_SYNC_EXEMPT = new Set(["skills", "setup", "help", "version"]);
/**
 * The first run after an install or upgrade brings the Skill copies the user
 * installed up to this package's Skill (PAPER_SEARCH_SKILL_AUTO_UPDATE=false
 * turns it off); stdout stays the command's own output.
 */
function maybeAutoSyncSkill(parsed) {
    if (SKILL_SYNC_EXEMPT.has(parsed.command))
        return;
    if (getConfigValue("PAPER_SEARCH_SKILL_AUTO_UPDATE") === "false")
        return;
    try {
        const result = autoSyncSkill({
            sourceRoot: PACKAGE_SKILL_ROOT,
            version: packageVersion(),
        });
        if (result.notice)
            process.stderr.write(`${result.notice}\n`);
    }
    catch (error) {
        process.stderr.write(`paper-search：检查已安装的 Skill 时出错：${error?.message || String(error)}\n`);
    }
}
/**
 * Download commands can leave a network request behind when a stage hits its
 * wall-clock deadline. Once the result has been written, exit instead of
 * waiting for such a socket; the write callbacks guarantee nothing is lost.
 */
function exitWhenFlushed() {
    const command = process.argv[2];
    if (command !== "run" && command !== "download")
        return;
    let pending = 2;
    const done = () => {
        pending -= 1;
        if (pending === 0)
            process.exit();
    };
    process.stdout.write("", done);
    process.stderr.write("", done);
}
main().then(exitWhenFlushed);
//# sourceMappingURL=cli.js.map