import type { SchoolBatchPapers, SchoolBatchUpdate, SchoolDownloadRequest, SchoolBackend, SchoolInvocationOutcome, SchoolMcpClientOptions, SchoolReadiness } from "./types.js";
export declare const SCHOOL_STARTUP_TIMEOUT_MS = 15000;
export declare const SCHOOL_TOOL_TIMEOUT_MS = 15000;
export declare const SCHOOL_DOWNLOAD_TIMEOUT_MS = 1200000;
export declare const SCHOOL_CLEANUP_TIMEOUT_MS = 5000;
export declare class SchoolMcpClient implements SchoolBackend {
    private readonly commandSource;
    private readonly args;
    private readonly profileDir;
    private readonly startupTimeoutMs;
    private readonly toolTimeoutMs;
    private readonly downloadTimeoutMs;
    private readonly cleanupTimeoutMs;
    private keepBatchBrowser;
    private retainedSession?;
    /** Inside a batch, the session progress reports reuse until the first download. */
    private progressSession?;
    /** Downloads under way: a progress report then opens no backend process of its own. */
    private downloads;
    /** The backend answered once that it takes no paper lists: none are sent again. */
    private papersUnsupported;
    withBatchSession<T>(run: (backend: SchoolBackend) => Promise<T>): Promise<T>;
    /** The executable a new backend process runs. */
    private get command();
    constructor(options?: SchoolMcpClientOptions);
    probe(signal?: AbortSignal): Promise<SchoolReadiness>;
    downloadLegalDoi(request: SchoolDownloadRequest): Promise<SchoolInvocationOutcome>;
    private download;
    /**
     * Update batch progress on the retained session, or on a short progress-only
     * session if the browser has not been opened.
     */
    reportBatchProgress(update: SchoolBatchUpdate, signal?: AbortSignal): Promise<boolean>;
    /**
     * While the batch waits (the hourly limit the user set): its browser loads the last
     * saved paper's article page again, so the publisher's institutional session does
     * not lapse (Wiley: about half an hour without a request, 2026-11-12). Only on the
     * backend the batch already has, never starting one.
     */
    keepSession(signal?: AbortSignal): Promise<boolean>;
    /** The batch's papers for the window's lists, on the backend the batch already has. */
    reportBatchPapers(update: SchoolBatchPapers, last?: boolean): Promise<boolean>;
    /**
     * A report on the batch's backend: its retained session, the session kept for
     * reports until the first download, or a short one of its own (``mayOpen``).
     */
    private report;
    private closeProgressSession;
    private clearThenDownload;
    private openSession;
    private closeSession;
    private closeBatchBrowser;
    private closeRaw;
}
/** One backend at a time per profile: downloads, and updating the extension, hold this lock. */
export declare const DOWNLOAD_LOCK_FILE = ".paper-search-download.lock";
/**
 * Take the profile's download lock, or throw (``EEXIST`` while another process
 * holds it). A lock is reclaimed only when its owner has exited and no browser
 * still holds a profile: the browser may outlive the process that started it.
 */
export declare function takeDownloadLock(profileDir: string): string;
/**
 * True when the lock's recorded owner process no longer exists and no
 * browser profile under ``profileDir/browser_profiles`` is held by a live
 * process (Chrome keeps a ``SingletonLock`` symlink to "host-pid" on macOS and
 * Linux). Anything unreadable or unexpected counts as not stale.
 */
export declare function isStaleDownloadLock(lockPath: string, profileDir: string): boolean;
/**
 * True when a browser profile under ``profileDir/browser_profiles`` is held by a
 * live process (Chrome's ``SingletonLock`` symlink to "host-pid" on macOS and
 * Linux); a lock that cannot be read counts as held.
 */
export declare function browserProfileInUse(profileDir: string): boolean;
/** Where PaperSearch keeps its own data: ``${XDG_DATA_HOME:-~/.local/share}/paper-search-cli``. */
export declare function paperSearchDataHome(env?: Record<string, string | undefined>, home?: string): string;
/** The backend's data directory before 0.6.1, named for CARSI (management/school/legacy.ts moves it). */
export declare const LEGACY_SCHOOL_DATA_DIR = "carsi";
/**
 * The backend's data directory (school, logins, progress): ``paper-search-cli/school``,
 * or 0.6.0's ``paper-search-cli/carsi`` while it has not been moved (it waits while
 * a download or its browser uses it).
 */
export declare function resolveDefaultSchoolProfileDir(env?: Record<string, string | undefined>, home?: string): string;
//# sourceMappingURL=SchoolMcpClient.d.ts.map