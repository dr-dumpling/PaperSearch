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
    constructor(options?: CarsiMcpClientOptions);
    probe(signal?: AbortSignal): Promise<CarsiReadiness>;
    downloadLegalDoi(request: CarsiDownloadRequest): Promise<CarsiInvocationOutcome>;
    /**
     * Update the backend's progress window for a serial batch. Uses a short
     * session of its own and no profile lock: it never touches the browser.
     */
    reportBatchProgress(update: CarsiBatchUpdate, signal?: AbortSignal): Promise<boolean>;
    private clearThenDownload;
    private openSession;
    private closeSession;
    private closeRaw;
}
/**
 * True when the lock's recorded owner process no longer exists and no
 * browser profile under ``profileDir/browser_profiles`` is held by a live
 * process (Firefox keeps a ``lock`` symlink to "host:+pid"). Anything
 * unreadable or unexpected counts as not stale.
 */
export declare function isStaleDownloadLock(lockPath: string, profileDir: string): boolean;
export declare function resolveDefaultCarsiProfileDir(env?: Record<string, string | undefined>, home?: string): string;
//# sourceMappingURL=CarsiMcpClient.d.ts.map