/**
 * Where Pro's releases are published. For now the private repository's releases, which only a
 * computer signed in to its GitHub account can download (user, 2026-11-18: testing the 安装 with a
 * private PaperSearch); a public address replaces it before Pro is offered to others.
 */
export declare const PRO_RELEASE_URL = "github:dr-dumpling/PaperSearch-Pro";
export interface ProManifest {
    version: string;
    bytes?: number;
    sha256?: string;
}
export type ProInstallResult = {
    ok: true;
    version: string;
    path: string;
} | {
    ok: false;
    code: string;
    message: string;
};
/** Where an install puts Pro: PaperSearch's data, where the command line loads it from by default. */
export declare function proInstallDir(env?: Record<string, string | undefined>): string;
/** Whether Pro is there, where the command line loads it from, and its version. */
export declare function proStatus(env?: Record<string, string | undefined>): {
    installed: boolean;
    version: string;
    path: string;
};
/** "0.1.10" is newer than "0.1.9"; a pre-release ("0.2.0-beta.1") is older than its release. */
export declare function newerVersion(candidate: string, current: string): boolean;
export type ProCheckResult = {
    ok: true;
    installed: boolean;
    version: string;
    latest: string;
    update: boolean;
} | {
    ok: false;
    code: string;
    message: string;
};
/** The newest Pro released, beside the one installed: the settings window's 检查更新 (user, 2026-11-19). */
export declare function checkPro(options?: {
    from?: string;
    env?: Record<string, string | undefined>;
    timeoutMs?: number;
    githubToken?: string;
}): Promise<ProCheckResult>;
/** Installs Pro into PaperSearch's data, replacing the one there only once the new one is whole and checked. */
export declare function installPro(options?: {
    from?: string;
    env?: Record<string, string | undefined>;
    onProgress?: (done: number, total: number) => void;
    timeoutMs?: number;
    /** The GitHub login for a GitHub release ("" for none); else this computer's. */
    githubToken?: string;
}): Promise<ProInstallResult>;
//# sourceMappingURL=install.d.ts.map