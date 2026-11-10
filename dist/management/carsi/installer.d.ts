import { type RuntimePaths } from "./runtime.js";
/**
 * `paper-search carsi install / status` (ADR 0013, plan in
 * docs/history/institutional-installer-2026-11-03.zh.md). Every step is recorded in
 * install.json as it completes; running install again continues from the
 * step that failed. Everything outside the process goes through the host, so
 * tests run the steps without network, downloads or windows.
 */
export type InstallBrowser = "chrome" | "ego";
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
    getConfig(key: "PAPER_SEARCH_CARSI_ENABLED" | "PAPER_SEARCH_CARSI_EXECUTABLE" | "PAPER_SEARCH_CARSI_AUTO_UPDATE"): string;
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
    /** "camoufox" in installs from before Chrome (ADR 0016); install and update move them to "chrome". */
    browser: InstallBrowser | "camoufox";
    startedAt: string;
    finishedAt?: string;
    steps: Partial<Record<InstallStep, string>>;
    uv?: string;
    python?: string;
    backend?: string;
    executable?: string;
    /** The user's Google Chrome as the browser step found it. */
    chrome?: {
        path: string;
        version: string;
    };
    /** Installs from before Chrome: the Camoufox build they downloaded (left for the user to delete). */
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
    /** The Chrome the backend would run ("" browser when none) and its version against the tested one. */
    chrome: {
        browser: string;
        path: string;
        version: string;
        tested: string;
        outdated: boolean;
        driver: string;
    };
    ego: string;
}
/**
 * After a PaperSearch upgrade: the backend and its dependencies from the new
 * package, the browser check, and the handshake. The school, logins, Chrome and
 * ego lite are left alone. An install from before Chrome gets a new Python
 * environment first (its Camoufox build stays where it is, named for the user).
 */
export declare function updateCarsi(host: InstallerHost, options: {
    force: boolean;
}, context: InstallContext): Promise<{
    status: "updated" | "up_to_date";
    record: InstallRecord;
    paths: RuntimePaths;
}>;
export interface UninstallOptions {
    /** Do not ask; keep the user's data unless told to remove it. */
    yes: boolean;
    removeData: boolean;
}
/**
 * Remove the runtime and turn the integration off. The user's data (school,
 * logins) is kept unless the user chooses to remove it; Chrome and ego lite are
 * the user's own and never touched. A Camoufox build left by an install from
 * before Chrome is named for the user, never deleted here.
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
    /** The backend's current school (set during or after the install); absent when it could not be read. */
    access?: {
        configured: boolean;
        school: string;
    };
    runtimeBytes: number;
    notes: string[];
}
export declare function carsiStatus(host: InstallerHost, context: InstallContext): Promise<CarsiStatus>;
export declare function renderStatusText(status: CarsiStatus): string;
export {};
//# sourceMappingURL=installer.d.ts.map