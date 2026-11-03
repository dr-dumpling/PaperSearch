import type { ChildProcess } from "node:child_process";
import {
  mkdirSync,
  openSync,
  closeSync,
  writeFileSync,
  unlinkSync,
  existsSync,
  readFileSync,
  readdirSync,
  readlinkSync,
} from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { ErrorCode, McpError } from "@modelcontextprotocol/sdk/types.js";
import { sanitizeDoi } from "../../../infrastructure/security/SecurityUtils.js";
import { decodeCarsiProgress } from "./CarsiProgress.js";
import {
  createCarsiDownloadArguments,
  selectCarsiBatchSupport,
  selectCarsiDownloadStrategy,
  validateCarsiContract,
  type CarsiBatchSupport,
  type CarsiDownloadStrategy,
} from "./CarsiReadiness.js";
import {
  normalizeCacheClearResult,
  normalizeDownloadResult,
  CarsiToolResultError,
} from "./CarsiResultNormalizer.js";
import type {
  CarsiBatchUpdate,
  CarsiDownloadRequest,
  CarsiBackend,
  CarsiInvocationOutcome,
  CarsiMcpClientOptions,
  CarsiReadiness,
  CarsiToolDefinition,
} from "./types.js";

export const CARSI_STARTUP_TIMEOUT_MS = 15_000;
export const CARSI_TOOL_TIMEOUT_MS = 15_000;
// Entitled access waits for a person (verification, login); the backend bounds
// each wait itself, so this outer limit only catches a hung backend.
export const CARSI_DOWNLOAD_TIMEOUT_MS = 1_200_000;
export const CARSI_CLEANUP_TIMEOUT_MS = 5_000;

const CARSI_BACKEND_SOURCE = "carsi";
// MCP clientInfo is informational only; keep in step with package.json on release.
const PAPER_SEARCH_MCP_CLIENT_VERSION = "0.4.0";

interface ActiveSession {
  client: Client;
  transport: TrackedStdioClientTransport;
  readiness: CarsiReadiness;
  downloadStrategy: CarsiDownloadStrategy;
  batchSupport: CarsiBatchSupport;
  protocolState: { failed: boolean };
}

const NO_BATCH_SUPPORT: CarsiBatchSupport = {
  downloadFields: false,
  supplementsField: false,
  userWaitField: false,
  progressTool: false,
};

class CarsiProtocolIntegrityError extends Error {}
class CarsiToolListError extends Error {}
class CarsiCleanupError extends Error {}

class CarsiProcessExitError extends Error {
  constructor(readonly exitCode: number | null) {
    super("CARSI MCP process exited before the session was closed.");
    this.name = "CarsiProcessExitError";
  }
}

class TrackedStdioClientTransport extends StdioClientTransport {
  spawnedPid: number | null = null;
  exitCode: number | null = null;
  exitObserved = false;
  exitedUnexpectedly = false;
  private spawnedProcess: ChildProcess | undefined;
  private closing = false;
  private resolveExit!: () => void;
  private readonly exitPromise = new Promise<void>((resolvePromise) => {
    this.resolveExit = resolvePromise;
  });

  constructor(
    params: ConstructorParameters<typeof StdioClientTransport>[0],
    private readonly startupDeadline: number,
    private readonly startupSignal?: AbortSignal,
  ) {
    super(params);
    this.onclose = () => this.recordExit(null);
  }

  override async start(): Promise<void> {
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
          this.onerror?.(new CarsiProtocolIntegrityError());
        });
    };
    const startPromise = super.start();
    const child = (this as unknown as { _process?: ChildProcess })._process;
    this.spawnedProcess = child;
    this.spawnedPid = child?.pid ?? this.pid;
    if (!child) {
      this.recordExit(null);
    } else if (child.exitCode !== null) {
      this.recordExit(child.exitCode);
    } else {
      child.once("exit", (code) => this.recordExit(code));
    }
    await withinStartupDeadline(
      startPromise,
      this.startupDeadline,
      this.startupSignal,
    );
  }

  beginClose(): void {
    this.closing = true;
  }

  async waitForUnexpectedExit(timeoutMs: number): Promise<boolean> {
    if (this.exitObserved) return this.exitedUnexpectedly;
    await Promise.race([
      this.exitPromise,
      new Promise<void>((resolvePromise) =>
        setTimeout(resolvePromise, timeoutMs),
      ),
    ]);
    return this.exitObserved && this.exitedUnexpectedly;
  }

  async waitForExit(timeoutMs: number): Promise<boolean> {
    if (this.hasExited()) return true;
    if (timeoutMs > 0) {
      await Promise.race([
        this.exitPromise,
        new Promise<void>((resolvePromise) =>
          setTimeout(resolvePromise, timeoutMs),
        ),
      ]);
    }
    return this.hasExited();
  }

  kill(signal: NodeJS.Signals): void {
    if (this.spawnedProcess && !this.hasExited()) {
      try {
        this.spawnedProcess.kill(signal);
        return;
      } catch {
        // Fall through to the PID guard for SDK/process edge cases.
      }
    }
    if (this.spawnedPid) safeKill(this.spawnedPid, signal);
  }

  hasExited(): boolean {
    if (this.exitObserved) return true;
    if (this.spawnedProcess) {
      return (
        this.spawnedProcess.exitCode !== null ||
        this.spawnedProcess.signalCode !== null
      );
    }
    return this.spawnedPid ? !isProcessAlive(this.spawnedPid) : true;
  }

  private recordExit(code: number | null): void {
    if (this.exitObserved) {
      if (this.exitCode === null && code !== null) this.exitCode = code;
      return;
    }
    this.exitCode = code;
    this.exitObserved = true;
    this.exitedUnexpectedly = !this.closing;
    this.resolveExit();
  }
}

export class CarsiMcpClient implements CarsiBackend {
  private readonly command: string;
  private readonly args: string[];
  private readonly profileDir: string;
  private readonly startupTimeoutMs: number;
  private readonly toolTimeoutMs: number;
  private readonly downloadTimeoutMs: number;
  private readonly cleanupTimeoutMs: number;

  constructor(options: CarsiMcpClientOptions = {}) {
    this.command = options.command || "paper-search-carsi";
    this.args = [...(options.args || ["run"])];
    this.profileDir = resolve(
      options.profileDir || resolveDefaultCarsiProfileDir(),
    );
    this.startupTimeoutMs = positiveTimeout(
      options.startupTimeoutMs,
      CARSI_STARTUP_TIMEOUT_MS,
    );
    this.toolTimeoutMs = positiveTimeout(
      options.toolTimeoutMs,
      CARSI_TOOL_TIMEOUT_MS,
    );
    this.downloadTimeoutMs = positiveTimeout(
      options.downloadTimeoutMs,
      CARSI_DOWNLOAD_TIMEOUT_MS,
    );
    this.cleanupTimeoutMs = positiveTimeout(
      options.cleanupTimeoutMs,
      CARSI_CLEANUP_TIMEOUT_MS,
    );
  }

  async probe(signal?: AbortSignal): Promise<CarsiReadiness> {
    let session: ActiveSession | undefined;
    let readiness: CarsiReadiness;

    try {
      session = await this.openSession(signal);
      readiness = session.readiness;
    } catch (error) {
      readiness = classifyStartupError(error, signal);
    }

    if (session && !(await this.closeSession(session))) {
      return incompatible(
        "cleanup_failed",
        "CARSI MCP process cleanup failed.",
      );
    }
    return readiness;
  }

  async downloadLegalDoi(
    request: CarsiDownloadRequest,
  ): Promise<CarsiInvocationOutcome> {
    const validation = sanitizeDoi(request.identifier);
    if (!validation.valid) {
      return {
        kind: "attempt_error",
        identifier: "",
        code: "invalid_identifier",
        message: "A valid DOI is required for CARSI entitled access.",
      };
    }
    const identifier = validation.sanitized.toLowerCase();

    // Cross-process exclusion covers cache clear, browser use, and child cleanup.
    // A lock is reclaimed only when its owner has exited and no browser still
    // holds a profile: the browser may outlive the process that started it.
    const lockPath = join(this.profileDir, ".paper-search-download.lock");
    try {
      mkdirSync(this.profileDir, { recursive: true, mode: 0o700 });
      if (existsSync(lockPath) && isStaleDownloadLock(lockPath, this.profileDir)) {
        unlinkSync(lockPath);
        process.stderr.write("[CARSI] 已回收上次异常退出留下的下载锁。\n");
      }
      const descriptor = openSync(lockPath, "wx", 0o600);
      try {
        writeFileSync(descriptor, `${JSON.stringify({ pid: process.pid })}\n`);
      } catch (error) {
        unlinkSync(lockPath);
        throw error;
      } finally {
        closeSync(descriptor);
      }
    } catch (error) {
      return attemptError(
        identifier,
        (error as NodeJS.ErrnoException).code === "EEXIST"
          ? "profile_busy"
          : "profile_unavailable",
        "CARSI profile is busy or unavailable.",
      );
    }

    let session: ActiveSession | undefined;
    let outcome: CarsiInvocationOutcome;

    try {
      session = await this.openSession(request.signal);
      if (session.readiness.state !== "available") {
        outcome = { kind: "backend_unavailable", readiness: session.readiness };
      } else {
        outcome = await this.clearThenDownload(session, identifier, request);
      }
    } catch (error) {
      if (isAbortError(error, request.signal)) {
        outcome = attemptError(
          identifier,
          "cancelled",
          "CARSI download was cancelled.",
        );
      } else {
        outcome = {
          kind: "backend_unavailable",
          readiness: classifyStartupError(error, request.signal),
        };
      }
    }

    if (session && !(await this.closeSession(session))) {
      return {
        kind: "backend_unavailable",
        readiness: incompatible(
          "cleanup_failed",
          "CARSI MCP process cleanup failed.",
        ),
      };
    }
    // openSession also performs cleanup on startup failure; retain its lock if
    // that cleanup failed even though no ActiveSession was returned to us.
    if (
      outcome.kind === "backend_unavailable" &&
      outcome.readiness.code === "cleanup_failed"
    )
      return outcome;
    // A failed cleanup intentionally retains the lock for operator inspection.
    try {
      unlinkSync(lockPath);
    } catch {
      return attemptError(
        identifier,
        "profile_unavailable",
        "CARSI profile lock could not be released.",
      );
    }
    return outcome;
  }

  /**
   * Update the backend's progress window for a serial batch. Uses a short
   * session of its own and no profile lock: it never touches the browser.
   */
  async reportBatchProgress(
    update: CarsiBatchUpdate,
    signal?: AbortSignal,
  ): Promise<boolean> {
    const count = (value: number) => Number.isSafeInteger(value) && value >= 0;
    if (
      typeof update.id !== "string" ||
      !update.id.trim() ||
      update.id.length > 128 ||
      ![update.total, update.done, update.succeeded, update.failed].every(
        count,
      ) ||
      update.total < 1 ||
      update.done > update.total
    ) {
      return false;
    }
    const current = update.current ? sanitizeDoi(update.current) : undefined;
    let session: ActiveSession | undefined;
    let updated = false;
    try {
      session = await this.openSession(signal);
      if (
        session.readiness.state === "available" &&
        session.batchSupport.progressTool
      ) {
        assertProtocolIntegrity(session.protocolState);
        const result = await session.client.callTool(
          {
            name: "carsi_batch_progress",
            arguments: {
              batch_id: update.id,
              total: update.total,
              done: update.done,
              succeeded: update.succeeded,
              failed: update.failed,
              current: current?.valid ? current.sanitized.toLowerCase() : "",
              finished: update.finished,
            },
          },
          undefined,
          requestOptions(this.toolTimeoutMs, signal),
        );
        assertProtocolIntegrity(session.protocolState);
        updated = batchProgressUpdated(result);
      }
    } catch {
      updated = false;
    }
    if (session && !(await this.closeSession(session))) return false;
    return updated;
  }

  private async clearThenDownload(
    session: ActiveSession,
    identifier: string,
    request: CarsiDownloadRequest,
  ): Promise<CarsiInvocationOutcome> {
    try {
      assertProtocolIntegrity(session.protocolState);
      const clearResult = await session.client.callTool(
        {
          name: "carsi_cache_clear",
          arguments: { identifier },
        },
        undefined,
        requestOptions(this.toolTimeoutMs, request.signal),
      );
      assertProtocolIntegrity(session.protocolState);
      normalizeCacheClearResult(clearResult);
    } catch (error) {
      if (isAbortError(error, request.signal)) {
        return attemptError(
          identifier,
          "cancelled",
          "CARSI download was cancelled.",
        );
      }
      return {
        kind: "backend_unavailable",
        readiness: incompatible(
          "cache_clear_failed",
          "CARSI DOI-scoped cache clear failed.",
        ),
      };
    }

    let receivingProgress = true;
    let lastProgress = 0;
    let lastStage = "";
    try {
      assertProtocolIntegrity(session.protocolState);
      const downloadResult = await session.client.callTool(
        {
          name: "carsi_download",
          arguments: createCarsiDownloadArguments(
            identifier,
            request.outputDir,
            session.downloadStrategy,
            session.batchSupport.downloadFields ? request.batch : undefined,
            session.batchSupport.supplementsField ? request.supplements : undefined,
            session.batchSupport.userWaitField ? request.userWait : undefined,
          ),
        },
        undefined,
        {
          ...requestOptions(this.downloadTimeoutMs, request.signal),
          // The SDK supplies a request-specific _meta.progressToken, outside
          // the seven fixed download arguments. Old servers may ignore it.
          onprogress: (value) => {
            if (!receivingProgress || request.signal?.aborted) return;
            if (
              !Number.isSafeInteger(value.progress) ||
              value.progress <= lastProgress
            )
              return;
            const event = decodeCarsiProgress(value, identifier);
            if (!event) return;
            lastProgress = value.progress;
            if (event.stage === lastStage) return;
            lastStage = event.stage;
            try {
              request.onProgress?.(event);
            } catch {
              // An optional UI observer cannot change the download outcome.
            }
          },
        },
      );
      assertProtocolIntegrity(session.protocolState);
      return normalizeDownloadResult(downloadResult, identifier, request.outputDir);
    } catch (error) {
      if (isAbortError(error, request.signal)) {
        return attemptError(
          identifier,
          "cancelled",
          "CARSI download was cancelled.",
        );
      }
      if (isTimeoutError(error)) {
        return attemptError(
          identifier,
          "download_timeout",
          "CARSI download timed out.",
        );
      }
      if (error instanceof CarsiToolResultError) {
        return attemptError(
          identifier,
          "invalid_download_result",
          "CARSI returned an unusable download result.",
        );
      }
      return attemptError(
        identifier,
        "invalid_download_result",
        "CARSI download failed.",
      );
    } finally {
      receivingProgress = false;
    }
  }

  private async openSession(signal?: AbortSignal): Promise<ActiveSession> {
    mkdirSync(this.profileDir, { recursive: true, mode: 0o700 });
    const startupDeadline = Date.now() + this.startupTimeoutMs;
    const transport = new TrackedStdioClientTransport(
      {
        command: this.command,
        args: this.args,
        env: {
          CARSI_DATA_DIR: this.profileDir,
        },
        stderr: "pipe",
      },
      startupDeadline,
      signal,
    );
    transport.stderr?.on("data", () => {
      // Drain upstream diagnostics without forwarding cookies, tokens, URLs, or profile content.
    });

    const client = new Client(
      { name: "papersearch", version: PAPER_SEARCH_MCP_CLIENT_VERSION },
      { capabilities: {} },
    );
    const protocolState = { failed: false };
    client.onerror = () => {
      protocolState.failed = true;
    };

    try {
      await withinStartupDeadline(
        client.connect(
          transport,
          requestOptions(remainingTimeout(startupDeadline), signal),
        ),
        startupDeadline,
        signal,
      );
      assertProtocolIntegrity(protocolState);
      const tools: CarsiToolDefinition[] = [];
      const seenCursors = new Set<string>();
      let cursor: string | undefined;
      do {
        const result = await client.listTools(
          cursor === undefined ? undefined : { cursor },
          requestOptions(remainingTimeout(startupDeadline), signal),
        );
        assertProtocolIntegrity(protocolState);
        tools.push(...result.tools);
        cursor = result.nextCursor;
        if (cursor !== undefined) {
          if (seenCursors.has(cursor) || seenCursors.size >= 64) {
            throw new CarsiToolListError();
          }
          seenCursors.add(cursor);
        }
      } while (cursor !== undefined);
      if (await transport.waitForUnexpectedExit(25)) {
        throw new CarsiProcessExitError(transport.exitCode);
      }
      const readiness = validateCarsiContract(
        client.getServerVersion()?.name,
        tools,
      );
      const downloadTool = tools.find(
        (tool) => tool.name === "carsi_download",
      );
      const downloadStrategy =
        readiness.state === "available" && downloadTool
          ? selectCarsiDownloadStrategy(downloadTool.inputSchema)
          : "legal_only";
      const batchSupport =
        readiness.state === "available"
          ? selectCarsiBatchSupport(tools, downloadStrategy)
          : NO_BATCH_SUPPORT;
      return {
        client,
        transport,
        readiness,
        downloadStrategy,
        batchSupport,
        protocolState,
      };
    } catch (error) {
      const failure =
        transport.exitedUnexpectedly &&
        !shouldPreserveStartupError(error, signal)
          ? new CarsiProcessExitError(transport.exitCode)
          : error;
      if (!(await this.closeRaw(client, transport))) {
        throw new CarsiCleanupError();
      }
      throw failure;
    }
  }

  private async closeSession(session: ActiveSession): Promise<boolean> {
    return this.closeRaw(session.client, session.transport);
  }

  private async closeRaw(
    client: Client,
    transport: TrackedStdioClientTransport,
  ): Promise<boolean> {
    const cleanupDeadline = Date.now() + this.cleanupTimeoutMs;
    const killReserve = Math.min(
      500,
      Math.max(20, Math.floor(this.cleanupTimeoutMs / 2)),
    );
    const gracefulBudget = Math.max(1, this.cleanupTimeoutMs - killReserve);
    transport.beginClose();
    await settlesWithin(client.close(), gracefulBudget);

    if (!transport.hasExited()) {
      transport.kill("SIGTERM");
      await transport.waitForExit(
        Math.min(250, Math.floor(remainingMillis(cleanupDeadline) / 2)),
      );
    }
    if (!transport.hasExited()) {
      transport.kill("SIGKILL");
      await transport.waitForExit(remainingMillis(cleanupDeadline));
    }

    return transport.hasExited();
  }
}

/**
 * True when the lock's recorded owner process no longer exists and no
 * browser profile under ``profileDir/browser_profiles`` is held by a live
 * process (Firefox keeps a ``lock`` symlink to "host:+pid"). Anything
 * unreadable or unexpected counts as not stale.
 */
export function isStaleDownloadLock(lockPath: string, profileDir: string): boolean {
  let owner: number;
  try {
    owner = Number((JSON.parse(readFileSync(lockPath, "utf8")) as { pid?: unknown }).pid);
  } catch {
    return false;
  }
  if (!Number.isSafeInteger(owner) || owner <= 0 || processAlive(owner)) return false;
  const profiles = join(profileDir, "browser_profiles");
  let entries: string[] = [];
  try {
    entries = readdirSync(profiles);
  } catch {
    return true; // no browser profiles at all
  }
  for (const entry of entries) {
    let target: string;
    try {
      target = readlinkSync(join(profiles, entry, "lock"));
    } catch {
      continue; // no Firefox lock in this profile
    }
    const pid = Number(/\+(\d+)$/.exec(target)?.[1]);
    if (!Number.isSafeInteger(pid) || pid <= 0 || processAlive(pid)) return false;
  }
  return true;
}

function processAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

export function resolveDefaultCarsiProfileDir(
  env: Record<string, string | undefined> = process.env,
  home: string = homedir(),
): string {
  const base = env.XDG_DATA_HOME
    ? resolve(env.XDG_DATA_HOME)
    : join(home, ".local", "share");
  return join(base, "paper-search-cli", "carsi");
}

function requestOptions(timeout: number, signal?: AbortSignal) {
  return {
    timeout,
    maxTotalTimeout: timeout,
    ...(signal ? { signal } : {}),
  };
}

function remainingTimeout(deadline: number): number {
  const remaining = remainingMillis(deadline);
  if (remaining <= 0) {
    throw new McpError(
      ErrorCode.RequestTimeout,
      "CARSI startup deadline exceeded.",
    );
  }
  return remaining;
}

function remainingMillis(deadline: number): number {
  return Math.max(0, deadline - Date.now());
}

async function withinStartupDeadline<T>(
  promise: Promise<T>,
  deadline: number,
  signal?: AbortSignal,
): Promise<T> {
  const timeout = remainingMillis(deadline);
  if (timeout <= 0) {
    void promise.catch(() => undefined);
    throw new McpError(
      ErrorCode.RequestTimeout,
      "CARSI process spawn timed out.",
    );
  }
  return new Promise<T>((resolvePromise, rejectPromise) => {
    let settled = false;
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      callback();
    };
    const onAbort = () =>
      finish(() => {
        const error = new Error("CARSI startup was aborted.");
        error.name = "AbortError";
        rejectPromise(error);
      });
    const timer = setTimeout(
      () =>
        finish(() =>
          rejectPromise(
            new McpError(
              ErrorCode.RequestTimeout,
              "CARSI process spawn timed out.",
            ),
          ),
        ),
      timeout,
    );

    promise.then(
      (value) => finish(() => resolvePromise(value)),
      (error) => finish(() => rejectPromise(error)),
    );
    if (signal?.aborted) onAbort();
    else signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function positiveTimeout(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : fallback;
}

function classifyStartupError(
  error: unknown,
  signal?: AbortSignal,
): CarsiReadiness {
  if (error instanceof CarsiCleanupError) {
    return incompatible(
      "cleanup_failed",
      "CARSI MCP process cleanup failed.",
    );
  }
  if (isExecutableMissing(error)) {
    return {
      state: "absent",
      code: "executable_missing",
      message: "CARSI executable was not found.",
      missing: [CARSI_BACKEND_SOURCE],
    };
  }
  if (isAbortError(error, signal)) {
    return incompatible(
      "probe_cancelled",
      "CARSI MCP readiness probe was cancelled.",
    );
  }
  if (error instanceof CarsiProcessExitError) {
    return error.exitCode !== null && error.exitCode !== 0
      ? incompatible(
          "process_exited_nonzero",
          "CARSI MCP process exited with an error.",
        )
      : incompatible(
          "process_exited",
          "CARSI MCP process exited before readiness completed.",
        );
  }
  if (isTimeoutError(error)) {
    return incompatible("startup_timeout", "CARSI MCP startup timed out.");
  }
  if (error instanceof CarsiToolListError) {
    return incompatible(
      "tools_list_incomplete",
      "CARSI did not provide a complete, consistent tool list.",
    );
  }
  if (error instanceof CarsiProtocolIntegrityError) {
    return incompatible(
      "protocol_error",
      "CARSI MCP stdout contained invalid protocol data.",
    );
  }
  return incompatible("probe_failed", "CARSI MCP readiness probe failed.");
}

function shouldPreserveStartupError(
  error: unknown,
  signal?: AbortSignal,
): boolean {
  return (
    error instanceof CarsiCleanupError ||
    error instanceof CarsiProtocolIntegrityError ||
    isExecutableMissing(error) ||
    isAbortError(error, signal) ||
    isTimeoutError(error)
  );
}

function incompatible(code: string, message: string): CarsiReadiness {
  return { state: "incompatible", code, message, missing: [] };
}

function attemptError(
  identifier: string,
  code: string,
  message: string,
): CarsiInvocationOutcome {
  return { kind: "attempt_error", identifier, code, message };
}

function isExecutableMissing(error: unknown): boolean {
  return Boolean(
    error &&
    typeof error === "object" &&
    (error as { code?: unknown }).code === "ENOENT",
  );
}

function isTimeoutError(error: unknown): boolean {
  return error instanceof McpError
    ? error.code === ErrorCode.RequestTimeout
    : error instanceof Error && /timed?\s*out|timeout/i.test(error.message);
}

function isAbortError(error: unknown, signal?: AbortSignal): boolean {
  return Boolean(
    signal?.aborted ||
    (error instanceof Error &&
      (error.name === "AbortError" ||
        /aborted|cancelled/i.test(error.message))),
  );
}

async function settlesWithin(
  promise: Promise<unknown>,
  timeoutMs: number,
): Promise<boolean> {
  return new Promise((resolvePromise) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      resolvePromise(false);
    }, timeoutMs);

    promise.then(
      () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolvePromise(true);
      },
      () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolvePromise(false);
      },
    );
  });
}

function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function safeKill(pid: number, signal: NodeJS.Signals): void {
  try {
    process.kill(pid, signal);
  } catch {
    // The process already exited.
  }
}

function assertProtocolIntegrity(state: { failed: boolean }): void {
  if (state.failed) throw new CarsiProtocolIntegrityError();
}

/** The batch progress tool answers {"updated": boolean} as one text block. */
function batchProgressUpdated(result: unknown): boolean {
  const content = (result as { content?: unknown; isError?: unknown })
    ?.content;
  if ((result as { isError?: unknown })?.isError === true) return false;
  if (!Array.isArray(content) || content.length !== 1) return false;
  const block = content[0] as { type?: unknown; text?: unknown };
  if (block?.type !== "text" || typeof block.text !== "string") return false;
  try {
    return (JSON.parse(block.text) as { updated?: unknown }).updated === true;
  } catch {
    return false;
  }
}
