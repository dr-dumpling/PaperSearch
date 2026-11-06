import { type RuntimePaths } from "./runtime.js";
/**
 * `paper-search carsi install / status` (ADR 0013, plan in
 * docs/history/institutional-installer-2026-11-03.zh.md). Every step is recorded in
 * install.json as it completes; running install again continues from the
 * step that failed. Everything outside the process goes through the host, so
 * tests run the steps without network, downloads or windows.
 */
export type InstallBrowser = "camoufox" | "ego";
export declare const INSTALL_STEPS: readonly ["preflight", "uv", "python", "backend", "browser", "config", "school", "notifications", "check"];
export type InstallStep = (typeof INSTALL_STEPS)[number];
export interface InstallOptions {
    browser: InstallBrowser;
    /** Do not ask before installing or before replacing another configured backend. */
    yes: boolean;
    /** The start was confirmed already (setup's question, or --install-carsi): only
     * the start is not asked again; replacing another configured backend still is. */
    confirmed?: boolean;
    /** Start again from the first step. */
    force: boolean;
    skipSchool: boolean;
}
export interface CommandResult {
    code: number;
    stdout: string;
    stderr: string;
}
export interface InstallerHost {
    platform: NodeJS.Platform;
    arch: string;
    home: string;
    env: Record<string, string | undefined>;
    run(command: string, args: string[], options?: {
        env?: Record<string, string>;
        echo?: boolean;
    }): Promise<CommandResult>;
    download(url: string, file: string): Promise<void>;
    sha256(file: string): Promise<string>;
    /** Free bytes on the volume holding ``path`` (or its nearest existing parent). */
    freeBytes(path: string): number;
    confirm(question: string): Promise<boolean>;
    ask(question: string): Promise<string>;
    log(line: string): void;
}
/** What install needs from PaperSearch itself. */
export interface InstallContext {
    /** The npm package's root: holds carsi/ with the backend's source. */
    packageRoot: string;
    paperSearchVersion: string;
    /** The backend's data directory (school, logins), as PaperSearch passes it. */
    dataDir: string;
    getConfig(key: "PAPER_SEARCH_CARSI_ENABLED" | "PAPER_SEARCH_CARSI_EXECUTABLE"): string;
    setConfig(key: "PAPER_SEARCH_CARSI_ENABLED" | "PAPER_SEARCH_CARSI_EXECUTABLE", value: string): void;
    unsetConfig(key: "PAPER_SEARCH_CARSI_ENABLED" | "PAPER_SEARCH_CARSI_EXECUTABLE"): void;
    /** The MCP handshake with the backend at ``executable``: its readiness state. */
    readiness(executable: string): Promise<{
        state: string;
        message?: string;
    }>;
    now(): Date;
}
export interface InstallRecord {
    schema: 1;
    paperSearchVersion: string;
    browser: InstallBrowser;
    startedAt: string;
    finishedAt?: string;
    steps: Partial<Record<InstallStep, string>>;
    uv?: string;
    python?: string;
    backend?: string;
    executable?: string;
    camoufoxBrowser?: string;
    ego?: string;
    school?: string;
    notifications?: boolean;
    /** Set by update: when the extension was last brought to this PaperSearch version. */
    updatedAt?: string;
    warnings?: string[];
}
export declare class InstallError extends Error {
    readonly step: InstallStep | "update";
    readonly logFile: string;
    constructor(step: InstallStep | "update", message: string, logFile: string);
}
export declare function readInstallRecord(paths: RuntimePaths): InstallRecord | undefined;
export declare function installCarsi(host: InstallerHost, options: InstallOptions, context: InstallContext): Promise<{
    status: "installed" | "already_installed" | "cancelled";
    record?: InstallRecord;
    paths: RuntimePaths;
}>;
interface BrowserProbe {
    pinned: string;
    installed: string;
    ego: string;
    /** Camoufox's own cache directory ("" without the camoufox package). */
    cache: string;
}
/**
 * After a PaperSearch upgrade: the backend and its dependencies from the new
 * package, the paired Camoufox build when the pin moved, and the handshake.
 * The school, logins and ego lite are left alone; an older Camoufox build stays
 * in the shared cache, where other programs may use it.
 */
export declare function updateCarsi(host: InstallerHost, options: {
    force: boolean;
}, context: InstallContext): Promise<{
    status: "updated" | "up_to_date";
    record: InstallRecord;
    paths: RuntimePaths;
}>;
export interface UninstallOptions {
    /** Do not ask; keep the shared Camoufox browser and the user's data unless told to remove them. */
    yes: boolean;
    removeBrowser: boolean;
    removeData: boolean;
}
/**
 * Remove the runtime and turn the integration off. The Camoufox build this
 * extension installed and the user's data (school, logins) are kept unless the
 * user chooses to remove them; ego lite is the user's own and never touched.
 */
export declare function uninstallCarsi(host: InstallerHost, options: UninstallOptions, context: InstallContext): Promise<{
    status: "uninstalled" | "cancelled" | "not_installed";
    removed: string[];
    kept: string[];
}>;
export interface CarsiStatus {
    installed: boolean;
    complete: boolean;
    root: string;
    record?: InstallRecord;
    executable: string;
    executableExists: boolean;
    enabled: boolean;
    configuredExecutable: string;
    usesThisInstall: boolean;
    paperSearchVersion: string;
    upToDate: boolean;
    versions?: BrowserProbe;
    runtimeBytes: number;
    notes: string[];
}
export declare function carsiStatus(host: InstallerHost, context: InstallContext): Promise<CarsiStatus>;
export declare function renderStatusText(status: CarsiStatus): string;
export {};
//# sourceMappingURL=installer.d.ts.map