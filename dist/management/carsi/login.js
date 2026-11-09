import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { hasScreen } from "./runtime.js";
export const LOGIN_UNAVAILABLE = "登录学校要用学校订阅下载：先运行 paper-search carsi install。";
export const LOGIN_NO_SCREEN = "登录学校要在看得见的浏览器里完成，这台电脑没有图形界面。";
/** The backend, its progress lines on this process's stderr, its reply collected. */
const runBackend = (file, args, env) => new Promise((resolve) => {
    const child = spawn(file, args, { env, stdio: ["ignore", "pipe", "inherit"], windowsHide: true });
    let stdout = "";
    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.on("error", () => resolve({ stdout, code: 1 }));
    child.on("close", (code) => resolve({ stdout, code: code ?? 1 }));
});
/**
 * Sign in to the school the way a download does, without its PDF (the
 * backend's `login`): the download browser opens the article's page, gets past
 * the site's verification, picks the school and waits on its login page for
 * the user. Success only once the school's login is confirmed and the article
 * opens in full; the session stays for the downloads that follow.
 */
export async function carsiLogin(options) {
    const exists = options.exists ?? existsSync;
    if (!options.executable || !exists(options.executable)) {
        return { ok: false, success: false, error: LOGIN_UNAVAILABLE, exitCode: 1 };
    }
    if (!hasScreen(options.platform ?? process.platform, options.env)) {
        return { ok: false, success: false, error: LOGIN_NO_SCREEN, exitCode: 1 };
    }
    const doi = options.doi.trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "");
    if (!/^10\.\d{4,9}\/\S+$/.test(doi)) {
        return { ok: false, success: false, exitCode: 2,
            error: "需要一篇学校订阅的文章的 DOI：paper-search carsi login --doi <DOI>" };
    }
    const args = ["login", "--doi", doi, ...(options.maxWait ? ["--max-wait", String(options.maxWait)] : [])];
    const { stdout, code } = await (options.run ?? runBackend)(options.executable, args, options.env);
    let reply;
    try {
        reply = JSON.parse(stdout.trim().split("\n").pop() || "");
    }
    catch {
        reply = { success: false, error: "学校订阅下载没有回应；运行 paper-search carsi status 检查" };
    }
    const ok = code === 0 && reply.success === true;
    return { ...reply, ok, ...(ok ? {} : { exitCode: code || 1 }) };
}
//# sourceMappingURL=login.js.map