import type { CarsiBatchUpdate, CarsiDownloadRequest, CarsiBackend, CarsiInvocationOutcome, CarsiMcpClientOptions, CarsiReadiness } from "./types.js";
export declare const CARSI_STARTUP_TIMEOUT_MS = 15000;
export declare const CARSI_TOOL_TIMEOUT_MS = 15000;
export declare const CARSI_DOWNLOAD_TIMEOUT_MS = 1200000;
export declare const CARSI_CLEANUP_TIMEOUT_MS = 5000;
export declare class CarsiMcpClient implements CarsiBackend {
    private readonly command;
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
    withBatchSession<T>(run: (backend: CarsiBackend) => Promise<T>): Promise<T>;
    constructor(options?: CarsiMcpClientOptions);
    probe(signal?: AbortSignal): Promise<CarsiReadiness>;
    downloadLegalDoi(request: CarsiDownloadRequest): Promise<CarsiInvocationOutcome>;
    /**
     * Update batch progress on the retained session, or on a short progress-only
     * session if the browser has not been opened.
     */
    reportBatchProgress(update: CarsiBatchUpdate, signal?: AbortSignal): Promise<boolean>;
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
export declare function resolveDefaultCarsiProfileDir(env?: Record<string, string | undefined>, home?: string): string;
//# sourceMappingURL=CarsiMcpClient.d.ts.map