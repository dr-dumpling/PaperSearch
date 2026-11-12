import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { getDefaultEnvironment } from "@modelcontextprotocol/sdk/client/stdio.js";
// The window needs its screen (Linux), to know it runs over SSH, and the proxy for its key tests.
const PASSED_THROUGH = ["DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "SSH_CONNECTION",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "no_proxy", "all_proxy"];
/**
 * The settings window's environment: the platform basics (as for the backend's
 * MCP process), its screen and proxy, and its paths; never PaperSearch's keys.
 */
export function settingsWindowEnv(paths, env = process.env) {
    const passed = Object.fromEntries(PASSED_THROUGH.filter((name) => env[name]).map((name) => [name, env[name]]));
    return { ...getDefaultEnvironment(), ...passed, SCHOOL_DATA_DIR: paths.dataDir, PAPER_SEARCH_CONFIG_FILE: paths.configFile,
        ...(paths.cli ? { PAPER_SEARCH_CLI: paths.cli } : {}) };
}
export const SETTINGS_WINDOW_UNAVAILABLE = "设置窗口随学校订阅下载一起安装：运行 paper-search school install。" +
    "不装也可以在你自己的终端运行 paper-search setup <KEY> 填写 API key。";
function runFile(file, args, env) {
    return new Promise((resolve) => {
        execFile(file, args, { env, timeout: 30_000, windowsHide: true }, (error, stdout) => {
            // A non-zero exit carries its code; a launcher that could not start (ENOENT) counts as 1.
            const code = !error ? 0 : typeof error.code === "number" ? error.code : 1;
            resolve({ stdout: String(stdout || ""), code });
        });
    });
}
/**
 * Open the settings (download folder, waits and reminders, API keys) in the
 * progress window: the open window switches to them, or one starts for them.
 * The window belongs to the school subscription download backend; without it
 * the answer says how to install it or use `paper-search setup` instead.
 */
export async function openSettingsWindow(options) {
    const exists = options.exists ?? existsSync;
    if (!options.executable || !exists(options.executable)) {
        return { ok: false, error: SETTINGS_WINDOW_UNAVAILABLE, exitCode: 1 };
    }
    if (options.target !== undefined && !/^[A-Za-z_]{1,64}$/.test(options.target)) {
        return { ok: false, error: `没有这一项设置：${options.target}`, exitCode: 2 };
    }
    const { stdout, code } = await (options.run ?? runFile)(options.executable, ["settings", ...(options.target ? [options.target] : [])], options.env);
    let reply;
    try {
        reply = JSON.parse(stdout.trim().split("\n").pop() || "");
    }
    catch {
        reply = { ok: false, error: "设置窗口没有回应；运行 paper-search school status 检查学校订阅下载" };
    }
    return code === 0 && reply.ok === true ? reply : { ...reply, ok: false, exitCode: code || 1 };
}
//# sourceMappingURL=settingsWindow.js.map