import type { FailureClass } from "../../../infrastructure/runlog/failureClass.js";
import type { CarsiProgressStage } from "./CarsiProgress.js";

export type CarsiReadinessState = "available" | "absent" | "incompatible";

export interface CarsiReadiness {
  state: CarsiReadinessState;
  code: string;
  message: string;
  missing: string[];
}

/** Position in a caller's serial batch (counts are totals before this item). */
export interface CarsiBatchPosition {
  id: string;
  index: number;
  total: number;
  done: number;
  succeeded: number;
  failed: number;
}

/** Batch totals for the backend's progress window, without a download. */
export interface CarsiBatchUpdate {
  id: string;
  total: number;
  done: number;
  succeeded: number;
  failed: number;
  current?: string;
  finished: boolean;
  /** With finished: the whole batch's outcome for the finished window. */
  results?: CarsiBatchResults;
}

/**
 * The batch's outcome as the progress window shows it; sent as is (wire
 * shape of carsi_batch_progress ``results``). Texts are display-ready.
 */
export interface CarsiBatchResults {
  content: "main" | "supplements" | "both";
  /** The batch's download folder (its papers/ once there), for the window's folder button. */
  folder: string;
  /** Epoch seconds the batch began (its open stages run before the window). */
  started: number;
  /** The user ended the batch in the window. */
  stopped: boolean;
  /** Main texts saved. */
  main: number;
  /** Supplementary files saved. */
  supplements: number;
  /** Supplements-only batch: article pages that listed none. */
  no_supplements: number;
  /** Where the saved main texts came from: [label, count], most first. */
  sources: Array<[string, number]>;
  failures: Array<{
    cls: FailureClass;
    /** A few words, e.g. 学校没有订阅. */
    reason: string;
    title?: string;
    journal?: string;
    doi?: string;
    /** What was still saved, e.g. 附录 1 个已保存. */
    note?: string;
  }>;
}

export interface CarsiDownloadRequest {
  identifier: string;
  outputDir: string;
  /** Optional separate directory for records and screenshots. */
  diagnosticsDir?: string;
  signal?: AbortSignal;
  onProgress?: (progress: CarsiProgress) => void;
  /** Sent only to backends whose download schema declares the batch fields. */
  batch?: CarsiBatchPosition;
  /** "with": also the supplementary files; "only": just those. Sent only when declared. */
  supplements?: "with" | "only";
  /**
   * "short": the user seems away (an earlier article of the batch waited on them
   * until its time was up); each wait on the user is short. Sent only when declared.
   */
  userWait?: "short";
}

/** A supplementary file reported by the backend (validated by the normalizer). */
export interface CarsiSupplement {
  label: string;
  status: "saved" | "failed" | "skipped";
  file?: string;
  size?: number;
  reason?: string;
}

/** Request-bound stages, not a completion percentage or authorization proof. */
export interface CarsiProgress {
  identifier: string;
  stage: CarsiProgressStage;
  message: string;
}

/**
 * Where the backend's browser run left its records, for the local run ledger.
 * Labels and codes are validated; file paths lie inside the request's outputDir.
 */
export interface CarsiTrace {
  driver?: string;
  publisher?: string;
  state?: string;
  /** The school's site a login stopped on (idp_no_return_to_publisher): a host name only. */
  stoppedHost?: string;
  record?: string;
  diagnostic?: string;
}

export type CarsiInvocationOutcome =
  | {
      kind: "success";
      identifier: string;
      path: string;
      source?: string;
      trace?: CarsiTrace;
      supplements?: CarsiSupplement[];
    }
  | {
      kind: "attempt_error";
      identifier: string;
      code: string;
      message: string;
      /** rate_limited: seconds until the publisher's hourly limit lets this article run. */
      retryAfterSec?: number;
      trace?: CarsiTrace;
      supplements?: CarsiSupplement[];
    }
  | {
      kind: "backend_unavailable";
      readiness: CarsiReadiness;
    };

/** Stable PaperSearch-owned port. Callers must not depend on MCP tool names or payload shapes. */
export interface CarsiBackend {
  probe(signal?: AbortSignal): Promise<CarsiReadiness>;
  downloadLegalDoi(
    request: CarsiDownloadRequest,
  ): Promise<CarsiInvocationOutcome>;
  /** Scope a reusable download browser to the lifetime of a serial batch. */
  withBatchSession?<T>(run: (backend: CarsiBackend) => Promise<T>): Promise<T>;
  /**
   * Optional: update the backend progress window of a serial batch. Resolves
   * false when the backend does not offer it; never throws for that.
   */
  reportBatchProgress?(
    update: CarsiBatchUpdate,
    signal?: AbortSignal,
  ): Promise<boolean>;
}

export interface CarsiMcpClientOptions {
  command?: string;
  args?: readonly string[];
  profileDir?: string;
  startupTimeoutMs?: number;
  toolTimeoutMs?: number;
  downloadTimeoutMs?: number;
  cleanupTimeoutMs?: number;
}

export interface CarsiToolDefinition {
  name: string;
  inputSchema: {
    [key: string]: unknown;
    type?: unknown;
    properties?: Record<string, unknown>;
    required?: unknown;
  };
}
