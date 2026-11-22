import type { FailureClass } from "../runlog/failureClass.js";
import type { CapturedFulltextPage } from "../../capabilities/download/types.js";
import type { SchoolProgressStage } from "./SchoolProgress.js";

export type SchoolReadinessState = "available" | "absent" | "incompatible";

export interface SchoolReadiness {
  state: SchoolReadinessState;
  code: string;
  message: string;
  missing: string[];
}

/** Position in a caller's serial batch (counts are totals before this item). */
export interface SchoolBatchPosition {
  id: string;
  index: number;
  total: number;
  done: number;
  succeeded: number;
  failed: number;
}

/** Batch totals for the backend's progress window, without a download. */
export interface SchoolBatchUpdate {
  id: string;
  total: number;
  done: number;
  succeeded: number;
  failed: number;
  current?: string;
  finished: boolean;
  /** With finished: the whole batch's outcome for the finished window. */
  results?: SchoolBatchResults;
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
  /**
   * Publishers whose school login stopped working mid-batch, their papers held: the window
   * shows them with a button to go on ([] clears them). Only to a backend that declares it.
   */
  held?: SchoolHeldPublisher[];
  /**
   * Nothing is left but the held publishers' papers and the batch waits for the user
   * (登录并继续 or 终止): the window says so, collapsed too. Only to a backend that declares it.
   */
  heldWait?: boolean;
}

/** A publisher a batch holds: its DOI prefix, its name, how many papers wait. */
export interface SchoolHeldPublisher {
  key: string;
  name: string;
  count: number;
}

/** What the user asked of a batch in its window since the last report. */
export interface SchoolBatchRequests {
  /** Held publishers (DOI prefixes) to go on with. */
  resume: string[];
  /** The batch was ended in the window. */
  stop: boolean;
}

/**
 * One paper of a batch for the progress window's lists behind 成功, 失败 and 剩余
 * (wire shape of school_batch_papers). Its state only moves forward: "open" (open
 * access not checked yet), "school" (waiting for or in the institutional download),
 * then "ok" or "failed".
 */
export interface SchoolBatchPaper {
  /** 1..N, the paper's place in the batch. */
  index: number;
  doi: string;
  title: string;
  journal: string;
  /** stopped: left undone by the user's stop (told apart from failed, 2026-11-16). */
  state: "open" | "school" | "ok" | "failed" | "stopped";
  /** Saved: 开放下载 or 机构下载. */
  via?: string;
  /** Saved by 开放下载 from elsewhere than open access: 出版社 API, Sci-Hub, 预印本. */
  detail?: string;
  /** Saved: the PDF (absolute), shown in its folder from the window's list. */
  path?: string;
  /** A batch of the supplementary files alone: how many this paper got (0: its page listed none). */
  supplements_saved?: number;
  /** Its Markdown not saved (asked for beside the PDF or the files): class, reason, a note. */
  markdown_cls?: FailureClass;
  markdown_reason?: string;
  markdown_note?: string;
  /** Its Markdown saved from a registered site's page whose checks found something short: the group and the note. */
  markdown_doubt_reason?: string;
  markdown_doubt_note?: string;
  /** Its page came from a site not yet supported: the host, and whether its Markdown was kept. */
  markdown_host?: string;
  markdown_saved?: boolean;
  /** Not tried: this batch gave the site up after its first three papers failed. */
  markdown_skipped?: boolean;
  /** Whose rules converted its page, or came closest ("Atypon"): the window says which were borrowed. */
  markdown_rules?: string;
  /** The saved page and its check results kept for a report (absolute). */
  markdown_report?: string;
  /** Saved without every supplementary file (content "both"): the first missing file's class and reason. */
  supplement_cls?: FailureClass;
  supplement_reason?: string;
  cls?: FailureClass;
  /** Failed: a few words, e.g. 学校没有订阅. */
  reason?: string;
}

/** Every paper once, then the ones that changed (merged by index). */
export interface SchoolBatchPapers {
  id: string;
  /** The batch's download folder (absolute). */
  folder: string;
  papers: SchoolBatchPaper[];
}

/**
 * The batch's outcome as the progress window shows it; sent as is (wire
 * shape of school_batch_progress ``results``). Texts are display-ready.
 */
export interface SchoolBatchResults {
  content: "main" | "supplements" | "both" | "markdown";
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
  /** Article pages checked that listed no supplementary files. */
  no_supplements: number;
  /** Papers whose article.md was saved, when the batch asked for the Markdown beside the PDF or the files. */
  markdown?: number;
  /** Papers the user's stop left undone (counted in the failed ones, told apart). */
  stopped_count?: number;
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
    /** What was still saved, e.g. 附录 1 个已保存; the Markdown alone, a site not yet supported's note. */
    note?: string;
    unverified?: boolean;
  }>;
  /** content "both": papers whose main text was saved but not every supplementary file, by the first file's reason. */
  supplement_failures: Array<{
    cls: FailureClass;
    reason: string;
    title?: string;
    journal?: string;
    doi?: string;
  }>;
  /** A batch that asked for the Markdown: papers saved without it (the PDF, or only the files), by its reason. */
  markdown_failures?: Array<{
    cls: FailureClass;
    reason: string;
    title?: string;
    journal?: string;
    doi?: string;
    /** A site not yet supported: "ard.eular.org · 不完整：参考文献少 1 条". */
    note?: string;
    unverified?: boolean;
  }>;
  /**
   * Saved with the Markdown from a registered site's page whose checks found something short
   * (user, 2026-11-17): grouped by the first thing short, the note saying all of it.
   */
  markdown_doubts?: Array<{ reason: string; note: string; title?: string; journal?: string; doi?: string }>;
}

export interface SchoolDownloadRequest {
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
  onProgress?: (progress: SchoolProgress) => void;
  /** Sent only to backends whose download schema declares the batch fields. */
  batch?: SchoolBatchPosition;
  /** "with": also the supplementary files; "only": just those. Sent only when declared. */
  supplements?: "with" | "only";
  /**
   * "short": the user seems away (an earlier article of the batch waited on them
   * until its time was up); each wait on the user is short. Sent only when declared.
   */
  userWait?: "short";
  /**
   * --fulltext: "with" also saves the article's full-text page and its figures while on it;
   * "only" opens the article for its page alone, no PDF. Sent only when declared.
   */
  fulltext?: "with" | "only";
  /** Another saved school for this download alone, as the user asked (the configured one stays). */
  school?: string;
}

/** The article's full-text page the backend saved while on it (--fulltext); paths inside outputDir. */
export type SchoolFulltextPage = CapturedFulltextPage;

/** A supplementary file reported by the backend (validated by the normalizer). */
export interface SchoolSupplement {
  label: string;
  status: "saved" | "failed" | "skipped";
  file?: string;
  size?: number;
  reason?: string;
}

/** Request-bound stages, not a completion percentage or authorization proof. */
export interface SchoolProgress {
  identifier: string;
  stage: SchoolProgressStage;
  message: string;
}

/**
 * Where the backend's browser run left its records, for the local run ledger.
 * Labels and codes are validated; file paths lie inside the request's outputDir.
 */
export interface SchoolTrace {
  driver?: string;
  publisher?: string;
  state?: string;
  /** The school's site a login stopped on (idp_no_return_to_publisher): a host name only. */
  stoppedHost?: string;
  /**
   * Where a wait on a school login ended (school_login: the school's own sign-in page;
   * also school_choice, institution_chooser, authentication_redirect, publisher, other, closed).
   */
  loginWaitPage?: string;
  /**
   * The backend's watchdog ended its browser calls during this download, also when its PDF was
   * saved: every later call of that backend fails at once, so the next download starts another.
   */
  browserStopped?: boolean;
  record?: string;
  diagnostic?: string;
}

/** The extension is older than the Markdown full text: it saves no article page. */
export const SCHOOL_UPDATE_NEEDED = "school_update_needed";
export const SCHOOL_UPDATE_NEEDED_MESSAGE =
  "The school subscription extension is older than this PaperSearch and saves no article page for the Markdown; " +
  "update it with: paper-search school update.";

export type SchoolInvocationOutcome =
  | {
      kind: "success";
      identifier: string;
      path: string;
      source?: string;
      /** Got through a saved school other than the default one (没权限时换下一所学校): its name, for the lists. */
      school?: string;
      trace?: SchoolTrace;
      supplements?: SchoolSupplement[];
      fulltextPage?: SchoolFulltextPage;
      /** --fulltext: the article page was read on this visit and showed no full text. */
      fulltextNotShown?: boolean;
    }
  | {
      kind: "attempt_error";
      identifier: string;
      code: string;
      message: string;
      /** rate_limited: seconds until the publisher's hourly limit lets this article run. */
      retryAfterSec?: number;
      /** rate_limited: the publisher whose hour it is, as the backend counts it (hourlyWait asks for it). */
      hourlyPublisher?: string;
      /** No access with any of the saved schools tried, this many (没权限时换下一所学校). */
      schoolsTried?: number;
      trace?: SchoolTrace;
      supplements?: SchoolSupplement[];
      fulltextPage?: SchoolFulltextPage;
    }
  | {
      kind: "backend_unavailable";
      readiness: SchoolReadiness;
    };

/** Stable PaperSearch-owned port. Callers must not depend on MCP tool names or payload shapes. */
export interface SchoolBackend {
  probe(signal?: AbortSignal): Promise<SchoolReadiness>;
  downloadLegalDoi(
    request: SchoolDownloadRequest,
  ): Promise<SchoolInvocationOutcome>;
  /** Scope a reusable download browser to the lifetime of a serial batch. */
  withBatchSession?<T>(run: (backend: SchoolBackend) => Promise<T>): Promise<T>;
  /**
   * Optional: update the backend progress window of a serial batch. Resolves
   * false when the backend does not offer it; never throws for that.
   */
  reportBatchProgress?(
    update: SchoolBatchUpdate,
    signal?: AbortSignal,
  ): Promise<boolean>;
  /** Optional: whether the window can show held publishers with a button to go on (``held``). */
  holdSupported?(): Promise<boolean>;
  /**
   * Optional: what the user asked of this batch in its window, as the answers to its
   * progress reports brought it (each request once).
   */
  takeBatchRequests?(batchId: string): SchoolBatchRequests;
  /**
   * Optional: the batch's papers for the progress window's lists. Resolves true once
   * the backend has them, false when it does not take them or this report did not
   * reach it (then the caller sends them again with the next one). They ride on a
   * backend process the batch already has; only the ``last`` report of a batch may
   * start one, as the finished card's report after it would.
   */
  reportBatchPapers?(
    update: SchoolBatchPapers,
    last?: boolean,
  ): Promise<boolean>;
  /**
   * Optional: while a batch waits (the publisher's hourly limit the user set), the
   * batch's browser loads the last saved paper's article page again, so the
   * publisher's institutional session does not lapse. Only on a backend the batch
   * already has; resolves false when there is none or it cannot. Never throws.
   */
  keepSession?(signal?: AbortSignal): Promise<boolean>;
  /**
   * Optional: while a batch waits for the hourly limit the user set, how long ``publisher``
   * (an attempt's ``hourlyPublisher``) still waits under the setting as it is now, so a limit
   * raised in the settings window lets the batch go on at once (2026-11-19). Only on a backend
   * the batch already has; undefined when there is none or it cannot say. Never throws.
   */
  hourlyWait?(publisher: string, signal?: AbortSignal): Promise<{ waitSec: number; limit: number } | undefined>;
  /**
   * Optional: whether a batch takes one journal's papers one after another (PaperSearch Pro's 没权限时换下一所学校: the
   * switch on and more than one school taking part, user 2026-11-21). Only on a backend the batch already has;
   * undefined when there is none or it cannot say. Never throws.
   */
  schoolSwitch?(signal?: AbortSignal): Promise<{ group: boolean } | undefined>;
}

export interface SchoolMcpClientOptions {
  /** The backend executable, or how to read it when a process starts (the config can change
   * in between: an update after an upgrade installs the backend at a new path). */
  command?: string | (() => string);
  args?: readonly string[];
  profileDir?: string;
  startupTimeoutMs?: number;
  toolTimeoutMs?: number;
  downloadTimeoutMs?: number;
  cleanupTimeoutMs?: number;
}

export interface SchoolToolDefinition {
  name: string;
  inputSchema: {
    [key: string]: unknown;
    type?: unknown;
    properties?: Record<string, unknown>;
    required?: unknown;
  };
}
