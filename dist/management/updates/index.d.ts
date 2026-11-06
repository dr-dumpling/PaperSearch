export declare const RELEASE_NOTES = "https://github.com/dr-dumpling/PaperSearch/releases";
/** Only recommend stable releases. A newer local prerelease is never downgraded. */
export declare function compareStableRelease(current: string, latest: string): number | undefined;
/** Upgrade the installation being used, including temporary npx and local installs. */
export declare function upgradeCommand(latest: string, packageRoot?: string): string;
export interface UpdateOptions {
    current: string;
    packageRoot?: string;
    dataRoot?: string;
    now?: () => number;
    queryLatest?: (signal: AbortSignal) => Promise<string>;
}
export interface UpdateResult {
    ok: boolean;
    currentVersion: string;
    latestVersion: string | null;
    updateAvailable: boolean | null;
    status: "update_available" | "up_to_date" | "newer_than_registry" | "unavailable";
    source: "npm";
    checkedAt: string | null;
    upgradeCommand?: string;
    releaseNotesUrl: string;
}
/** Fixed public endpoint, no credentials, bounded response and no redirects. */
export declare function queryLatestStable(signal: AbortSignal): Promise<string>;
export declare function checkForUpdate(options: UpdateOptions): Promise<UpdateResult>;
export declare function renderUpdateNotice(result: UpdateResult): string;
/** Runs alongside the original command. stop() cancels at command completion. */
export declare function beginUpdateNotification(options: UpdateOptions & {
    enabled: boolean;
    allowNetwork: boolean;
    write: (text: string) => void;
}): {
    stop(): void;
    done: Promise<void>;
};
//# sourceMappingURL=index.d.ts.map