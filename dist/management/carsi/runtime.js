import { homedir } from "node:os";
import { join, resolve } from "node:path";
/**
 * Where the institutional extension is installed (ADR 0013): uv when the
 * machine has none, a managed Python, the virtual environment with the backend,
 * the install record and log. The user's data (school, logins) stays in the
 * backend's data directory, and the Camoufox browser in Camoufox's own cache.
 */
export const UV_VERSION = "0.13.6";
/** uv's release archives and their SHA-256 (the release's .sha256 files, 2026-11-01). */
export const UV_ARCHIVES = {
    "darwin-arm64": {
        file: "uv-aarch64-apple-darwin.tar.gz",
        sha256: "60fbd5c8a1ed681845eea28d9d622fcde03c51e91a43465b64a1e17db1ed3472",
    },
    "darwin-x64": {
        file: "uv-x86_64-apple-darwin.tar.gz",
        sha256: "63ba17fdda55ad1a230d4b37fc6017ffa10c23688c83818bd3bfdf914c652a02",
    },
    "win32-x64": {
        file: "uv-x86_64-pc-windows-msvc.zip",
        sha256: "a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f",
    },
    "win32-arm64": {
        file: "uv-aarch64-pc-windows-msvc.zip",
        sha256: "c2426c0c8e28b53d8c440e47a18d96ad4db51e159866c0e81435b196d7f0081c",
    },
    "linux-x64": {
        file: "uv-x86_64-unknown-linux-gnu.tar.gz",
        sha256: "f29c3e94ffabd7e6f3ba521dba169a9b7ec12100bf3257087f0f24f6123f3645",
    },
    "linux-arm64": {
        file: "uv-aarch64-unknown-linux-gnu.tar.gz",
        sha256: "229e194255c7958d86d56e8790d969a6f74736592133f0dfd0076f754c642c1d",
    },
};
export const PYTHON_VERSION = "3.12";
export function uvArchiveUrl(file) {
    return `https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${file}`;
}
/** `${XDG_DATA_HOME:-~/.local/share}/paper-search-cli/carsi-runtime`, beside the backend's data directory. */
export function runtimeRoot(env = process.env, home = homedir()) {
    const base = env.XDG_DATA_HOME ? resolve(env.XDG_DATA_HOME) : join(home, ".local", "share");
    return join(base, "paper-search-cli", "carsi-runtime");
}
export function runtimePaths(root, platform) {
    const windows = platform === "win32";
    const venv = join(root, "venv");
    const scripts = join(venv, windows ? "Scripts" : "bin");
    return {
        root,
        bin: join(root, "bin"),
        python: join(root, "python"),
        venv,
        src: join(root, "src"),
        venvPython: join(scripts, windows ? "python.exe" : "python"),
        // pip writes this launcher from pyproject's [project.scripts]; on Windows an .exe.
        executable: join(scripts, windows ? "paper-search-carsi.exe" : "paper-search-carsi"),
        installFile: join(root, "install.json"),
        logFile: join(root, "install.log"),
    };
}
/** ego lite, the user's own browser; only looked for on macOS (ADR 0013). */
export function egoAppCandidates(home = homedir()) {
    return [join(home, "Applications", "ego lite.app"), "/Applications/ego lite.app"];
}
//# sourceMappingURL=runtime.js.map