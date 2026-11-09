/**
 * Where the institutional extension is installed (ADR 0013): uv when the
 * machine has none, a managed Python, the virtual environment with the backend,
 * the install record and log. The user's data (school, logins) stays in the
 * backend's data directory. The browser is the user's own Google Chrome (ADR 0016).
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
    /** uv's download cache, kept here so uninstalling removes it too. */
    uvCache: string;
    venv: string;
    src: string;
    venvPython: string;
    executable: string;
    installFile: string;
    logFile: string;
}
export declare function runtimePaths(root: string, platform: NodeJS.Platform): RuntimePaths;
/**
 * Whether this computer can show windows. School subscription downloads need a
 * visible browser for the school login: on Linux an X or Wayland display (a
 * server has neither); macOS and Windows always have one.
 */
export declare function hasScreen(platform: NodeJS.Platform, env: Record<string, string | undefined>): boolean;
export declare const NO_SCREEN: string;
/** ego lite, the user's own browser; only looked for on macOS (ADR 0013). */
export declare function egoAppCandidates(home?: string): string[];
export declare const CHROME_DOWNLOAD_URL = "https://www.google.com/chrome/";
/**
 * Where Google Chrome installs itself, as the backend looks for it
 * (browser/backend.py find_chrome); on Linux the backend searches PATH itself.
 */
export declare function chromeCandidates(platform: NodeJS.Platform, home?: string, env?: Record<string, string | undefined>): string[];
/**
 * Where an install from before Chrome had its Camoufox browser build:
 * Camoufox's own cache (platformdirs' user cache directory for "camoufox").
 */
export declare function camoufoxBuildDir(platform: NodeJS.Platform, build: string, home?: string, env?: Record<string, string | undefined>): string;
//# sourceMappingURL=runtime.d.ts.map