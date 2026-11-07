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
    withBatchSession<T>(run: (backend: CarsiBackend) => Promise<T>): Promise<T>;
    constructor(options?: CarsiMcpClientOptions);
    probe(signal?: AbortSignal): Promise<CarsiReadiness>;
    downloadLegalDoi(request: CarsiDownloadRequest): Promise<CarsiInvocationOutcome>;
    /**
     * Update batch progress on the retained session, or on a short progress-only
     * session if the browser has not been opened.
     */
    reportBatchProgress(update: CarsiBatchUpdate, signal?: AbortSignal): Promise<boolean>;
    private clearThenDownload;
    private openSession;
    private closeSession;
    private closeBatchBrowser;
    private closeRaw;
}
/**
 * True when the lock's recorded owner process no longer exists and no
 * browser profile under ``profileDir/browser_profiles`` is held by a live
 * process (Chrome keeps a ``SingletonLock`` symlink to "host-pid" on macOS and
 * Linux). Anything unreadable or unexpected counts as not stale.
 */
export declare function isStaleDownloadLock(lockPath: string, profileDir: string): boolean;
export declare function resolveDefaultCarsiProfileDir(env?: Record<string, string | undefined>, home?: string): string;
//# sourceMappingURL=CarsiMcpClient.d.ts.map