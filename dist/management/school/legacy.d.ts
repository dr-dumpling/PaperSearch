/**
 * Before 0.6.1 school subscription downloads were named for CARSI, the first
 * federation they supported: the config keys (ConfigService), the backend's data
 * directory and its runtime. What 0.6.0 left is taken over here once:
 * - the data directory ``paper-search-cli/carsi`` (school, logins, progress, runs)
 *   is renamed ``school`` when nothing uses it;
 * - the runtime ``paper-search-cli/carsi-runtime`` cannot be moved (its Python
 *   environment holds its own paths): ``school update`` installs a new one beside
 *   it and removes the old (installer.ts).
 */
export declare const LEGACY_RUNTIME_DIR = "carsi-runtime";
export declare function legacyRuntimeRoot(env?: Record<string, string | undefined>, home?: string): string;
export interface DataMove {
    outcome: "none" | "moved" | "busy" | "failed";
    from?: string;
    to?: string;
    error?: string;
}
/**
 * Renames 0.6.0's data directory once nothing uses it: no download holds its
 * lock and no download browser has a profile open in it. 0.6.0's progress window,
 * which would keep showing the old place, is closed first. Paths the backend saved
 * in its config follow the directory. Until the rename succeeds the old directory
 * stays in use (resolveDefaultSchoolProfileDir), and the next command tries again.
 */
export declare function moveLegacyDataDir(env?: Record<string, string | undefined>, home?: string, platform?: NodeJS.Platform): DataMove;
/**
 * 0.6.0's progress window, recorded in ``progress/bar.pid``: closed when that
 * process is still the window (its command line names the module), never another
 * process that took over the number.
 */
export declare function closeLegacyProgressWindow(dataDir: string, platform?: NodeJS.Platform): void;
//# sourceMappingURL=legacy.d.ts.map