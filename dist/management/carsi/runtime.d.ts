/**
 * Where the institutional extension is installed (ADR 0013): uv when the
 * machine has none, a managed Python, the virtual environment with the backend,
 * the install record and log. The user's data (school, logins) stays in the
 * backend's data directory, and the Camoufox browser in Camoufox's own cache.
 */
export declare const UV_VERSION = "0.13.6";
/** uv's release archives and their SHA-256 (the release's .sha256 files, 2026-11-01). */
export declare const UV_ARCHIVES: Readonly<Record<string, {
    file: string;
    sha256: string;
}>>;
export declare const PYTHON_VERSION = "3.12";
export declare function uvArchiveUrl(file: string): string;
/** `${XDG_DATA_HOME:-~/.local/share}/paper-search-cli/carsi-runtime`, beside the backend's data directory. */
export declare function runtimeRoot(env?: Record<string, string | undefined>, home?: string): string;
export interface RuntimePaths {
    root: string;
    bin: string;
    python: string;
    venv: string;
    src: string;
    venvPython: string;
    executable: string;
    installFile: string;
    logFile: string;
}
export declare function runtimePaths(root: string, platform: NodeJS.Platform): RuntimePaths;
/** ego lite, the user's own browser; only looked for on macOS (ADR 0013). */
export declare function egoAppCandidates(home?: string): string[];
//# sourceMappingURL=runtime.d.ts.map