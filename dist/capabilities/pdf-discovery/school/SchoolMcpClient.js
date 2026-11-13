import { getConfigPath } from "../../../config/ConfigService.js";
import { paperSearchCommand } from "../../../config/selfCommand.js";
import { mkdirSync, openSync, closeSync, writeFileSync, unlinkSync, existsSync, readFileSync, readdirSync, readlinkSync, } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { ErrorCode, McpError } from "@modelcontextprotocol/sdk/types.js";
import { sanitizeDoi } from "../../../infrastructure/security/SecurityUtils.js";
import { decodeSchoolProgress } from "./SchoolProgress.js";
import { CLOSE_BATCH_BROWSER, createSchoolDownloadArguments, selectSchoolBatchSupport, selectSchoolDownloadStrategy, validateSchoolContract, } from "./SchoolReadiness.js";
import { normalizeCacheClearResult, normalizeDownloadResult, SchoolToolResultError, } from "./SchoolResultNormalizer.js";
export const SCHOOL_STARTUP_TIMEOUT_MS = 15_000;
export const SCHOOL_TOOL_TIMEOUT_MS = 15_000;
/** school_keep_session: the article page loaded again (25 s), settling back on its site (22 s), a blank tab (5 s). */
const KEEP_SESSION_TOOL_TIMEOUT_MS = 60_000;
// Entitled access waits for a person (verification, login); the backend bounds
// each wait itself, so this outer limit only catches a hung backend.
export const SCHOOL_DOWNLOAD_TIMEOUT_MS = 1_200_000;
export const SCHOOL_CLEANUP_TIMEOUT_MS = 5_000;
const SCHOOL_BACKEND_SOURCE = "school";
// MCP clientInfo is informational only; keep in step with package.json on release.
const PAPER_SEARCH_MCP_CLIENT_VERSION = "0.6.4";
const NO_BATCH_SUPPORT = {
    downloadFields: false,
    supplementsField: false,
    userWaitField: false,
    progressTool: false,
};
class SchoolProtocolIntegrityError extends Error {
}
class SchoolToolListError extends Error {
}
class SchoolCleanupError extends Error {
}
class SchoolProcessExitError extends Error {
    exitCode;
    constructor(exitCode) {
        super("School backend MCP process exited before the session was closed.");
        this.exitCode = exitCode;
        this.name = "SchoolProcessExitError";
    }
}
class TrackedStdioClientTransport extends StdioClientTransport {
    startupDeadline;
    startupSignal;
    spawnedPid = null;
    exitCode = null;
    exitObserved = false;
    exitedUnexpectedly = false;
    spawnedProcess;
    closing = false;
    resolveExit;
    exitPromise = new Promise((resolvePromise) => {
        this.resolveExit = resolvePromise;
    });
    constructor(params, startupDeadline, startupSignal) {
        super(params);
        this.startupDeadline = startupDeadline;
        this.startupSignal = startupSignal;
        this.onclose = () => this.recordExit(null);
    }
    async start() {
        // SDK 1.29 dispatches notifications in a microtask but handles responses
        // synchronously. Yield between parsed messages so a coalesced final
        // response cannot remove onprogress before earlier notifications run.
        const onmessage = this.onmessage;
        let delivery = Promise.resolve();
        this.onmessage = (message) => {
            delivery = delivery
                .then(() => {
                onmessage?.(message);
            })
                .catch(() => {
                this.onerror?.(new SchoolProtocolIntegrityError());
            });
        };
        const startPromise = super.start();
        const child = this._process;
        this.spawnedProcess = child;
        this.spawnedPid = child?.pid ?? this.pid;
        if (!child) {
            this.recordExit(null);
        }
        else if (child.exitCode !== null) {
            this.recordExit(child.exitCode);
        }
        else {
            child.once("exit", (code) => this.recordExit(code));
        }
        await withinStartupDeadline(startPromise, this.startupDeadline, this.startupSignal);
    }
    beginClose() {
        this.closing = true;
    }
    async waitForUnexpectedExit(timeoutMs) {
        if (this.exitObserved)
            return this.exitedUnexpectedly;
        await Promise.race([
            this.exitPromise,
            new Promise((resolvePromise) => setTimeout(resolvePromise, timeoutMs)),
        ]);
        return this.exitObserved && this.exitedUnexpectedly;
    }
    async waitForExit(timeoutMs) {
        if (this.hasExited())
            return true;
        if (timeoutMs > 0) {
            await Promise.race([
                this.exitPromise,
                new Promise((resolvePromise) => setTimeout(resolvePromise, timeoutMs)),
            ]);
        }
        return this.hasExited();
    }
    kill(signal) {
        if (this.spawnedProcess && !this.hasExited()) {
            try {
                this.spawnedProcess.kill(signal);
                return;
            }
            catch {
                // Fall through to the PID guard for SDK/process edge cases.
            }
        }
        if (this.spawnedPid)
            safeKill(this.spawnedPid, signal);
    }
    hasExited() {
        if (this.exitObserved)
            return true;
        if (this.spawnedProcess) {
            return (this.spawnedProcess.exitCode !== null ||
                this.spawnedProcess.signalCode !== null);
        }
        return this.spawnedPid ? !isProcessAlive(this.spawnedPid) : true;
    }
    recordExit(code) {
        if (this.exitObserved) {
            if (this.exitCode === null && code !== null)
                this.exitCode = code;
            return;
        }
        this.exitCode = code;
        this.exitObserved = true;
        this.exitedUnexpectedly = !this.closing;
        this.resolveExit();
    }
}
export class SchoolMcpClient {
    commandSource;
    args;
    profileDir;
    startupTimeoutMs;
    toolTimeoutMs;
    downloadTimeoutMs;
    cleanupTimeoutMs;
    keepBatchBrowser = false;
    retainedSession;
    /** Inside a batch, the session progress reports reuse until the first download. */
    progressSession;
    /** Downloads under way: a progress report then opens no backend process of its own. */
    downloads = 0;
    /** The backend answered once that it takes no paper lists: none are sent again. */
    papersUnsupported = false;
    async withBatchSession(run) {
        const scoped = new SchoolMcpClient({
            command: this.commandSource, args: this.args, profileDir: this.profileDir,
            startupTimeoutMs: this.startupTimeoutMs, toolTimeoutMs: this.toolTimeoutMs,
            downloadTimeoutMs: this.downloadTimeoutMs, cleanupTimeoutMs: this.cleanupTimeoutMs,
        });
        scoped.keepBatchBrowser = true;
        try {
            return await run(scoped);
        }
        finally {
            await scoped.closeProgressSession();
            const session = scoped.retainedSession;
            if (session) {
                await scoped.closeBatchBrowser(session);
                if (await scoped.closeSession(session)) {
                    unlinkSync(join(scoped.profileDir, DOWNLOAD_LOCK_FILE));
                }
                else {
                    throw new SchoolCleanupError();
                }
            }
        }
    }
    /** The executable a new backend process runs. */
    get command() {
        const command = typeof this.commandSource === "function" ? this.commandSource() : this.commandSource;
        return command || "paper-search-school";
    }
    constructor(options = {}) {
        this.commandSource = options.command || "paper-search-school";
        this.args = [...(options.args || ["run"])];
        this.profileDir = resolve(options.profileDir || resolveDefaultSchoolProfileDir());
        this.startupTimeoutMs = positiveTimeout(options.startupTimeoutMs, SCHOOL_STARTUP_TIMEOUT_MS);
        this.toolTimeoutMs = positiveTimeout(options.toolTimeoutMs, SCHOOL_TOOL_TIMEOUT_MS);
        this.downloadTimeoutMs = positiveTimeout(options.downloadTimeoutMs, SCHOOL_DOWNLOAD_TIMEOUT_MS);
        this.cleanupTimeoutMs = positiveTimeout(options.cleanupTimeoutMs, SCHOOL_CLEANUP_TIMEOUT_MS);
    }
    async probe(signal) {
        let session;
        let readiness;
        try {
            session = await this.openSession(signal);
            readiness = session.readiness;
        }
        catch (error) {
            readiness = classifyStartupError(error, signal);
        }
        if (session && !(await this.closeSession(session))) {
            return incompatible("cleanup_failed", "School backend MCP process cleanup failed.");
        }
        return readiness;
    }
    async downloadLegalDoi(request) {
        this.downloads += 1;
        try {
            return await this.download(request);
        }
        finally {
            this.downloads -= 1;
        }
    }
    async download(request) {
        const validation = sanitizeDoi(request.identifier);
        if (!validation.valid) {
            return {
                kind: "attempt_error",
                identifier: "",
                code: "invalid_identifier",
                message: "A valid DOI is required for school subscription downloads.",
            };
        }
        const identifier = validation.sanitized.toLowerCase();
        // A download opens its own session and takes the profile lock as before.
        await this.closeProgressSession();
        // Cross-process exclusion covers cache clear, browser use, and child cleanup.
        const lockPath = join(this.profileDir, DOWNLOAD_LOCK_FILE);
        try {
            if (!this.retainedSession)
                takeDownloadLock(this.profileDir);
        }
        catch (error) {
            return attemptError(identifier, error.code === "EEXIST"
                ? "profile_busy"
                : "profile_unavailable", "School backend profile is busy or unavailable.");
        }
        let session = this.retainedSession;
        let outcome;
        try {
            session ??= await this.openSession(request.signal);
            // A batch's backend from its first download on: its other lane's progress
            // reports use it meanwhile (whether it stays is decided below).
            if (this.keepBatchBrowser && session.batchSupport.keepBrowser && request.batch)
                this.retainedSession = session;
            if (session.readiness.state !== "available") {
                outcome = { kind: "backend_unavailable", readiness: session.readiness };
            }
            else {
                outcome = await this.clearThenDownload(session, identifier, request);
            }
        }
        catch (error) {
            if (isAbortError(error, request.signal)) {
                outcome = attemptError(identifier, "cancelled", "School backend download was cancelled.");
            }
            else {
                outcome = {
                    kind: "backend_unavailable",
                    readiness: classifyStartupError(error, request.signal),
                };
            }
        }
        if (session && this.keepBatchBrowser && session.batchSupport.keepBrowser && request.batch &&
            !session.transport.exitedUnexpectedly && canReuseBatchBrowser(outcome)) {
            this.retainedSession = session;
            return outcome;
        }
        this.retainedSession = undefined;
        if (session && !(await this.closeSession(session))) {
            return {
                kind: "backend_unavailable",
                readiness: incompatible("cleanup_failed", "School backend MCP process cleanup failed."),
            };
        }
        // openSession also performs cleanup on startup failure; retain its lock if
        // that cleanup failed even though no ActiveSession was returned to us.
        if (outcome.kind === "backend_unavailable" &&
            outcome.readiness.code === "cleanup_failed")
            return outcome;
        // A failed cleanup intentionally retains the lock for operator inspection.
        try {
            unlinkSync(lockPath);
        }
        catch {
            return attemptError(identifier, "profile_unavailable", "School backend profile lock could not be released.");
        }
        return outcome;
    }
    /**
     * Update batch progress on the retained session, or on a short progress-only
     * session if the browser has not been opened.
     */
    async reportBatchProgress(update, signal) {
        const count = (value) => Number.isSafeInteger(value) && value >= 0;
        if (typeof update.id !== "string" ||
            !update.id.trim() ||
            update.id.length > 128 ||
            ![update.total, update.done, update.succeeded, update.failed].every(count) ||
            update.total < 1 ||
            update.done > update.total) {
            return false;
        }
        const current = update.current ? sanitizeDoi(update.current) : undefined;
        // The lanes line rides on the batch's backend once there, never starting one of its own.
        return this.report(update.lanes === undefined, signal, async (session) => {
            if (!session.batchSupport.progressTool || (update.lanes !== undefined && !session.batchSupport.progressLanes)) {
                return false;
            }
            assertProtocolIntegrity(session.protocolState);
            const result = await session.client.callTool({
                name: "school_batch_progress",
                arguments: {
                    batch_id: update.id,
                    total: update.total,
                    done: update.done,
                    succeeded: update.succeeded,
                    failed: update.failed,
                    current: current?.valid ? current.sanitized.toLowerCase() : "",
                    finished: update.finished,
                    ...(update.finished && update.results && session.batchSupport.progressResults
                        ? { results: update.results } : {}),
                    ...(!update.finished && session.batchSupport.progressPhase
                        ? { phase: update.phase ?? "", channel: update.channel ?? "" } : {}),
                    ...(!update.finished && update.lanes !== undefined ? { lanes: update.lanes } : {}),
                },
            }, undefined, requestOptions(this.toolTimeoutMs, signal));
            assertProtocolIntegrity(session.protocolState);
            return batchProgressUpdated(result);
        });
    }
    /**
     * While the batch waits (the hourly limit the user set): its browser loads the last
     * saved paper's article page again, so the publisher's institutional session does
     * not lapse (Wiley: about half an hour without a request, 2026-11-12). Only on the
     * backend the batch already has, never starting one.
     */
    async keepSession(signal) {
        const session = this.retainedSession;
        if (!session || session.readiness.state !== "available" || !session.batchSupport.keepSessionTool)
            return false;
        try {
            assertProtocolIntegrity(session.protocolState);
            const result = await session.client.callTool({ name: "school_keep_session", arguments: {} }, undefined, 
            // Loading the page and letting it settle back on the article's site take up to 52 s.
            requestOptions(Math.max(this.toolTimeoutMs, KEEP_SESSION_TOOL_TIMEOUT_MS), signal));
            assertProtocolIntegrity(session.protocolState);
            return sessionKept(result);
        }
        catch {
            return false;
        }
    }
    /** The batch's papers for the window's lists, on the backend the batch already has. */
    async reportBatchPapers(update, last = false) {
        if (this.papersUnsupported || typeof update.id !== "string" || !update.id.trim() || update.id.length > 128) {
            return false;
        }
        return this.report(last, undefined, async (session) => {
            if (!session.batchSupport.papersTool) {
                this.papersUnsupported = true;
                return false;
            }
            assertProtocolIntegrity(session.protocolState);
            const result = await session.client.callTool({ name: "school_batch_papers", arguments: { batch_id: update.id, folder: update.folder, papers: update.papers } }, undefined, requestOptions(this.toolTimeoutMs));
            assertProtocolIntegrity(session.protocolState);
            return batchProgressUpdated(result);
        });
    }
    /**
     * A report on the batch's backend: its retained session, the session kept for
     * reports until the first download, or a short one of its own (``mayOpen``).
     */
    async report(mayOpen, signal, call) {
        let session = this.retainedSession ?? this.progressSession;
        // A download is opening its own backend process; a second one only for a
        // report would write the same window's state.
        if (!session && (this.downloads || !mayOpen))
            return false;
        let opened = false;
        let updated = false;
        try {
            if (!session) {
                session = await this.openSession(signal);
                opened = true;
                // One backend process serves a batch's reports until its first download.
                if (this.keepBatchBrowser && !this.downloads)
                    this.progressSession = session;
            }
            if (session.readiness.state === "available")
                updated = await call(session);
        }
        catch {
            updated = false;
            if (session && session === this.progressSession) {
                await this.closeProgressSession();
                session = undefined;
            }
        }
        // Only a process opened for this report, and not kept for the next ones.
        if (opened && session && session !== this.progressSession &&
            !(await this.closeSession(session)))
            return false;
        return updated;
    }
    async closeProgressSession() {
        const session = this.progressSession;
        if (!session)
            return;
        this.progressSession = undefined;
        // Progress is optional: a failed cleanup does not fail the batch.
        await this.closeSession(session).catch(() => false);
    }
    async clearThenDownload(session, identifier, request) {
        try {
            assertProtocolIntegrity(session.protocolState);
            const clearResult = await session.client.callTool({
                name: "school_cache_clear",
                arguments: { identifier },
            }, undefined, requestOptions(this.toolTimeoutMs, request.signal));
            assertProtocolIntegrity(session.protocolState);
            normalizeCacheClearResult(clearResult);
        }
        catch (error) {
            if (isAbortError(error, request.signal)) {
                return attemptError(identifier, "cancelled", "School backend download was cancelled.");
            }
            return {
                kind: "backend_unavailable",
                readiness: incompatible("cache_clear_failed", "School backend DOI-scoped cache clear failed."),
            };
        }
        let receivingProgress = true;
        let lastProgress = 0;
        let lastStage = "";
        try {
            assertProtocolIntegrity(session.protocolState);
            const downloadResult = await session.client.callTool({
                name: "school_download",
                arguments: {
                    ...createSchoolDownloadArguments(identifier, request.outputDir, session.downloadStrategy, session.batchSupport.downloadFields ? request.batch : undefined, session.batchSupport.supplementsField ? request.supplements : undefined, session.batchSupport.userWaitField ? request.userWait : undefined, session.batchSupport.diagnosticsDirField ? request.diagnosticsDir : undefined, session.batchSupport.titleField ? request.title : undefined),
                    ...(this.keepBatchBrowser && session.batchSupport.keepBrowser && request.batch ? { keep_browser: true } : {}),
                },
            }, undefined, {
                ...requestOptions(this.downloadTimeoutMs, request.signal),
                // The SDK supplies a request-specific _meta.progressToken, outside
                // the seven fixed download arguments. Old servers may ignore it.
                onprogress: (value) => {
                    if (!receivingProgress || request.signal?.aborted)
                        return;
                    if (!Number.isSafeInteger(value.progress) ||
                        value.progress <= lastProgress)
                        return;
                    const event = decodeSchoolProgress(value, identifier);
                    if (!event)
                        return;
                    lastProgress = value.progress;
                    if (event.stage === lastStage)
                        return;
                    lastStage = event.stage;
                    try {
                        request.onProgress?.(event);
                    }
                    catch {
                        // An optional UI observer cannot change the download outcome.
                    }
                },
            });
            assertProtocolIntegrity(session.protocolState);
            return normalizeDownloadResult(downloadResult, identifier, request.outputDir, session.batchSupport.diagnosticsDirField ? request.diagnosticsDir : undefined);
        }
        catch (error) {
            if (isAbortError(error, request.signal)) {
                return attemptError(identifier, "cancelled", "School backend download was cancelled.");
            }
            if (isTimeoutError(error)) {
                return attemptError(identifier, "download_timeout", "School backend download timed out.");
            }
            if (error instanceof SchoolToolResultError) {
                return attemptError(identifier, "invalid_download_result", "School backend returned an unusable download result.");
            }
            return attemptError(identifier, "invalid_download_result", "School backend download failed.");
        }
        finally {
            receivingProgress = false;
        }
    }
    async openSession(signal) {
        mkdirSync(this.profileDir, { recursive: true, mode: 0o700 });
        const startupDeadline = Date.now() + this.startupTimeoutMs;
        const transport = new TrackedStdioClientTransport({
            command: this.command,
            args: this.args,
            env: {
                SCHOOL_DATA_DIR: this.profileDir,
                PAPER_SEARCH_CONFIG_FILE: getConfigPath(),
                // The progress window's key test runs this same CLI.
                PAPER_SEARCH_CLI: paperSearchCommand(),
            },
            stderr: "pipe",
        }, startupDeadline, signal);
        transport.stderr?.on("data", () => {
            // Drain upstream diagnostics without forwarding cookies, tokens, URLs, or profile content.
        });
        const client = new Client({ name: "papersearch", version: PAPER_SEARCH_MCP_CLIENT_VERSION }, { capabilities: {} });
        const protocolState = { failed: false };
        client.onerror = () => {
            protocolState.failed = true;
        };
        try {
            await withinStartupDeadline(client.connect(transport, requestOptions(remainingTimeout(startupDeadline), signal)), startupDeadline, signal);
            assertProtocolIntegrity(protocolState);
            const tools = [];
            const seenCursors = new Set();
            let cursor;
            do {
                const result = await client.listTools(cursor === undefined ? undefined : { cursor }, requestOptions(remainingTimeout(startupDeadline), signal));
                assertProtocolIntegrity(protocolState);
                tools.push(...result.tools);
                cursor = result.nextCursor;
                if (cursor !== undefined) {
                    if (seenCursors.has(cursor) || seenCursors.size >= 64) {
                        throw new SchoolToolListError();
                    }
                    seenCursors.add(cursor);
                }
            } while (cursor !== undefined);
            if (await transport.waitForUnexpectedExit(25)) {
                throw new SchoolProcessExitError(transport.exitCode);
            }
            const readiness = validateSchoolContract(client.getServerVersion()?.name, tools);
            const downloadTool = tools.find((tool) => tool.name === "school_download");
            const downloadStrategy = readiness.state === "available" && downloadTool
                ? selectSchoolDownloadStrategy(downloadTool.inputSchema)
                : "legal_only";
            const batchSupport = readiness.state === "available"
                ? selectSchoolBatchSupport(tools, downloadStrategy)
                : NO_BATCH_SUPPORT;
            return {
                client,
                transport,
                readiness,
                downloadStrategy,
                batchSupport,
                protocolState,
            };
        }
        catch (error) {
            const failure = transport.exitedUnexpectedly &&
                !shouldPreserveStartupError(error, signal)
                ? new SchoolProcessExitError(transport.exitCode)
                : error;
            if (!(await this.closeRaw(client, transport))) {
                throw new SchoolCleanupError();
            }
            throw failure;
        }
    }
    async closeSession(session) {
        return this.closeRaw(session.client, session.transport);
    }
    async closeBatchBrowser(session) {
        try {
            await session.client.callTool({ name: CLOSE_BATCH_BROWSER, arguments: {} }, undefined, requestOptions(this.cleanupTimeoutMs));
        }
        catch {
            // Closing the owning process also closes its Playwright pipe.
        }
    }
    async closeRaw(client, transport) {
        const cleanupDeadline = Date.now() + this.cleanupTimeoutMs;
        const killReserve = Math.min(500, Math.max(20, Math.floor(this.cleanupTimeoutMs / 2)));
        const gracefulBudget = Math.max(1, this.cleanupTimeoutMs - killReserve);
        transport.beginClose();
        await settlesWithin(client.close(), gracefulBudget);
        if (!transport.hasExited()) {
            transport.kill("SIGTERM");
            await transport.waitForExit(Math.min(250, Math.floor(remainingMillis(cleanupDeadline) / 2)));
        }
        if (!transport.hasExited()) {
            transport.kill("SIGKILL");
            await transport.waitForExit(remainingMillis(cleanupDeadline));
        }
        return transport.hasExited();
    }
}
function canReuseBatchBrowser(outcome) {
    if (outcome.kind === "backend_unavailable")
        return false;
    const broken = (code) => code === "browser_unresponsive" || code === "browser_operation_timeout";
    if (broken(outcome.trace?.state) || outcome.supplements?.some((file) => broken(file.reason)))
        return false;
    if (outcome.kind === "success")
        return true;
    // A site's verification timeout ended normally. Only a stalled transport
    // (no completed browser diagnostic) needs a new process for the next item.
    return !broken(outcome.code) && outcome.code !== "cancelled" && outcome.code !== "invalid_download_result" &&
        (outcome.code !== "download_timeout" || outcome.trace?.state === "challenge_or_viewer_timeout");
}
/** One backend at a time per profile: downloads, and updating the extension, hold this lock. */
export const DOWNLOAD_LOCK_FILE = ".paper-search-download.lock";
/**
 * Take the profile's download lock, or throw (``EEXIST`` while another process
 * holds it). A lock is reclaimed only when its owner has exited and no browser
 * still holds a profile: the browser may outlive the process that started it.
 */
export function takeDownloadLock(profileDir) {
    const lockPath = join(profileDir, DOWNLOAD_LOCK_FILE);
    mkdirSync(profileDir, { recursive: true, mode: 0o700 });
    if (existsSync(lockPath) && isStaleDownloadLock(lockPath, profileDir)) {
        unlinkSync(lockPath);
        process.stderr.write("[学校订阅] 已回收上次异常退出留下的下载锁。\n");
    }
    const descriptor = openSync(lockPath, "wx", 0o600);
    try {
        writeFileSync(descriptor, `${JSON.stringify({ pid: process.pid })}\n`);
    }
    catch (error) {
        unlinkSync(lockPath);
        throw error;
    }
    finally {
        closeSync(descriptor);
    }
    return lockPath;
}
/**
 * True when the lock's recorded owner process no longer exists and no
 * browser profile under ``profileDir/browser_profiles`` is held by a live
 * process (Chrome keeps a ``SingletonLock`` symlink to "host-pid" on macOS and
 * Linux). Anything unreadable or unexpected counts as not stale.
 */
export function isStaleDownloadLock(lockPath, profileDir) {
    let owner;
    try {
        owner = Number(JSON.parse(readFileSync(lockPath, "utf8")).pid);
    }
    catch {
        return false;
    }
    if (!Number.isSafeInteger(owner) || owner <= 0 || processAlive(owner))
        return false;
    return !browserProfileInUse(profileDir);
}
/**
 * True when a browser profile under ``profileDir/browser_profiles`` is held by a
 * live process (Chrome's ``SingletonLock`` symlink to "host-pid" on macOS and
 * Linux); a lock that cannot be read counts as held.
 */
export function browserProfileInUse(profileDir) {
    const profiles = join(profileDir, "browser_profiles");
    let entries = [];
    try {
        entries = readdirSync(profiles);
    }
    catch {
        return false; // no browser profiles at all
    }
    for (const entry of entries) {
        let target;
        try {
            target = readlinkSync(join(profiles, entry, "SingletonLock"));
        }
        catch {
            continue; // no Chrome lock in this profile
        }
        const pid = Number(/-(\d+)$/.exec(target)?.[1]);
        if (!Number.isSafeInteger(pid) || pid <= 0 || processAlive(pid))
            return true;
    }
    return false;
}
function processAlive(pid) {
    try {
        process.kill(pid, 0);
        return true;
    }
    catch (error) {
        return error.code === "EPERM";
    }
}
/** Where PaperSearch keeps its own data: ``${XDG_DATA_HOME:-~/.local/share}/paper-search-cli``. */
export function paperSearchDataHome(env = process.env, home = homedir()) {
    return join(env.XDG_DATA_HOME ? resolve(env.XDG_DATA_HOME) : join(home, ".local", "share"), "paper-search-cli");
}
/** The backend's data directory before 0.6.1, named for CARSI (management/school/legacy.ts moves it). */
export const LEGACY_SCHOOL_DATA_DIR = "carsi";
/**
 * The backend's data directory (school, logins, progress): ``paper-search-cli/school``,
 * or 0.6.0's ``paper-search-cli/carsi`` while it has not been moved (it waits while
 * a download or its browser uses it).
 */
export function resolveDefaultSchoolProfileDir(env = process.env, home = homedir()) {
    const base = paperSearchDataHome(env, home);
    const current = join(base, "school");
    const legacy = join(base, LEGACY_SCHOOL_DATA_DIR);
    return !existsSync(current) && existsSync(legacy) ? legacy : current;
}
function requestOptions(timeout, signal) {
    return {
        timeout,
        maxTotalTimeout: timeout,
        ...(signal ? { signal } : {}),
    };
}
function remainingTimeout(deadline) {
    const remaining = remainingMillis(deadline);
    if (remaining <= 0) {
        throw new McpError(ErrorCode.RequestTimeout, "School backend startup deadline exceeded.");
    }
    return remaining;
}
function remainingMillis(deadline) {
    return Math.max(0, deadline - Date.now());
}
async function withinStartupDeadline(promise, deadline, signal) {
    const timeout = remainingMillis(deadline);
    if (timeout <= 0) {
        void promise.catch(() => undefined);
        throw new McpError(ErrorCode.RequestTimeout, "School backend process spawn timed out.");
    }
    return new Promise((resolvePromise, rejectPromise) => {
        let settled = false;
        const finish = (callback) => {
            if (settled)
                return;
            settled = true;
            clearTimeout(timer);
            signal?.removeEventListener("abort", onAbort);
            callback();
        };
        const onAbort = () => finish(() => {
            const error = new Error("School backend startup was aborted.");
            error.name = "AbortError";
            rejectPromise(error);
        });
        const timer = setTimeout(() => finish(() => rejectPromise(new McpError(ErrorCode.RequestTimeout, "School backend process spawn timed out."))), timeout);
        promise.then((value) => finish(() => resolvePromise(value)), (error) => finish(() => rejectPromise(error)));
        if (signal?.aborted)
            onAbort();
        else
            signal?.addEventListener("abort", onAbort, { once: true });
    });
}
function positiveTimeout(value, fallback) {
    return typeof value === "number" && Number.isFinite(value) && value > 0
        ? value
        : fallback;
}
function classifyStartupError(error, signal) {
    if (error instanceof SchoolCleanupError) {
        return incompatible("cleanup_failed", "School backend MCP process cleanup failed.");
    }
    if (isExecutableMissing(error)) {
        return {
            state: "absent",
            code: "executable_missing",
            message: "School backend executable was not found.",
            missing: [SCHOOL_BACKEND_SOURCE],
        };
    }
    if (isAbortError(error, signal)) {
        return incompatible("probe_cancelled", "School backend MCP readiness probe was cancelled.");
    }
    if (error instanceof SchoolProcessExitError) {
        return error.exitCode !== null && error.exitCode !== 0
            ? incompatible("process_exited_nonzero", "School backend MCP process exited with an error.")
            : incompatible("process_exited", "School backend MCP process exited before readiness completed.");
    }
    if (isTimeoutError(error)) {
        return incompatible("startup_timeout", "School backend MCP startup timed out.");
    }
    if (error instanceof SchoolToolListError) {
        return incompatible("tools_list_incomplete", "School backend did not provide a complete, consistent tool list.");
    }
    if (error instanceof SchoolProtocolIntegrityError) {
        return incompatible("protocol_error", "School backend MCP stdout contained invalid protocol data.");
    }
    return incompatible("probe_failed", "School backend MCP readiness probe failed.");
}
function shouldPreserveStartupError(error, signal) {
    return (error instanceof SchoolCleanupError ||
        error instanceof SchoolProtocolIntegrityError ||
        isExecutableMissing(error) ||
        isAbortError(error, signal) ||
        isTimeoutError(error));
}
function incompatible(code, message) {
    return { state: "incompatible", code, message, missing: [] };
}
function attemptError(identifier, code, message) {
    return { kind: "attempt_error", identifier, code, message };
}
function isExecutableMissing(error) {
    return Boolean(error &&
        typeof error === "object" &&
        error.code === "ENOENT");
}
function isTimeoutError(error) {
    return error instanceof McpError
        ? error.code === ErrorCode.RequestTimeout
        : error instanceof Error && /timed?\s*out|timeout/i.test(error.message);
}
function isAbortError(error, signal) {
    return Boolean(signal?.aborted ||
        (error instanceof Error &&
            (error.name === "AbortError" ||
                /aborted|cancelled/i.test(error.message))));
}
async function settlesWithin(promise, timeoutMs) {
    return new Promise((resolvePromise) => {
        let settled = false;
        const timer = setTimeout(() => {
            if (settled)
                return;
            settled = true;
            resolvePromise(false);
        }, timeoutMs);
        promise.then(() => {
            if (settled)
                return;
            settled = true;
            clearTimeout(timer);
            resolvePromise(true);
        }, () => {
            if (settled)
                return;
            settled = true;
            clearTimeout(timer);
            resolvePromise(false);
        });
    });
}
function isProcessAlive(pid) {
    try {
        process.kill(pid, 0);
        return true;
    }
    catch {
        return false;
    }
}
function safeKill(pid, signal) {
    try {
        process.kill(pid, signal);
    }
    catch {
        // The process already exited.
    }
}
function assertProtocolIntegrity(state) {
    if (state.failed)
        throw new SchoolProtocolIntegrityError();
}
/** The batch progress tool answers {"updated": boolean} as one text block. */
function sessionKept(result) {
    const content = result?.content;
    if (result?.isError === true || !Array.isArray(content) || content.length !== 1)
        return false;
    const block = content[0];
    if (block?.type !== "text" || typeof block.text !== "string")
        return false;
    try {
        return JSON.parse(block.text).kept === true;
    }
    catch {
        return false;
    }
}
function batchProgressUpdated(result) {
    const content = result
        ?.content;
    if (result?.isError === true)
        return false;
    if (!Array.isArray(content) || content.length !== 1)
        return false;
    const block = content[0];
    if (block?.type !== "text" || typeof block.text !== "string")
        return false;
    try {
        return JSON.parse(block.text).updated === true;
    }
    catch {
        return false;
    }
}
//# sourceMappingURL=SchoolMcpClient.js.map