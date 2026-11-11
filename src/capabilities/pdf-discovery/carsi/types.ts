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
  /** While waiting for the next item: the window's status line. */
  phase?: string;
  /** Where the batch fetches from before any publisher, e.g. "开放下载". */
  channel?: string;
  /**
   * The papers each lane of the batch got, on one line: "开放下载 15 篇 · 机构下载 9 篇".
   * Beside a running download the backend then changes only the counts and this
   * line; a backend that does not declare it is not sent the update at all.
   */
  lanes?: string;
}

/**
 * One paper of a batch for the progress window's lists behind 成功, 失败 and 剩余
 * (wire shape of carsi_batch_papers). Its state only moves forward: "open" (open
 * access not checked yet), "school" (waiting for or in the institutional download),
 * then "ok" or "failed".
 */
export interface CarsiBatchPaper {
  /** 1..N, the paper's place in the batch. */
  index: number;
  doi: string;
  title: string;
  journal: string;
  state: "open" | "school" | "ok" | "failed";
  /** Saved: 开放下载 or 机构下载. */
  via?: string;
  /** Saved by 开放下载 from elsewhere than open access: 出版社 API, Sci-Hub, 预印本. */
  detail?: string;
  /** Saved: the PDF (absolute), shown in its folder from the window's list. */
  path?: string;
  /** Saved without every supplementary file (content "both"): the first missing file's class and reason. */
  supplement_cls?: FailureClass;
  supplement_reason?: string;
  cls?: FailureClass;
  /** Failed: a few words, e.g. 学校没有订阅. */
  reason?: string;
}

/** Every paper once, then the ones that changed (merged by index). */
export interface CarsiBatchPapers {
  id: string;
  /** The batch's download folder (absolute). */
  folder: string;
  papers: CarsiBatchPaper[];
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
  /** Where the saved main texts came from: [label, count], most first (开放下载, 机构下载). */
  sources: Array<[string, number]>;
  /**
   * A label's sources in brackets after its count, e.g. ["开放下载", "出版社 API 3"].
   * A backend that does not know it drops it and shows the counts alone.
   */
  source_details?: Array<[string, string]>;
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
  /** content "both": papers whose main text was saved but not every supplementary file, by the first file's reason. */
  supplement_failures: Array<{
    cls: FailureClass;
    reason: string;
    title?: string;
    journal?: string;
    doi?: string;
  }>;
}

export interface CarsiDownloadRequest {
  identifier: string;
  outputDir: string;
  /** Optional separate directory for records and screenshots. */
  diagnosticsDir?: string;
  /**
   * The paper's title from its metadata: the backend checks the PDF against it when the
   * article page names no title (Science on Atypon). Sent only when declared.
   */
  title?: string;
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
  /**
   * Optional: the batch's papers for the progress window's lists. Resolves true once
   * the backend has them, false when it does not take them or this report did not
   * reach it (then the caller sends them again with the next one). They ride on a
   * backend process the batch already has; only the ``last`` report of a batch may
   * start one, as the finished card's report after it would.
   */
  reportBatchPapers?(
    update: CarsiBatchPapers,
    last?: boolean,
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
