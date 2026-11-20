/**
 * PaperSearch Pro on this computer: whether it is installed,
 * and installing it. A release is two files: `index.js`, and `pro.json` with its version, size and
 * SHA-256 (pro/build.mjs). They come from a folder (`--from <folder>`), a web address, or a GitHub
 * release (`github:<owner>/<repo>`, its newest `pro-v*` release; a private repository is read with
 * this computer's GitHub login, `gh auth token`); the file is checked against its SHA-256, and the
 * install replaces the old one only once whole.
 * The settings window's 安装 runs `paper-search pro install --progress`, reading its progress lines.
 */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import axios from "axios";
import { USER_AGENT } from "../../config/constants.js";
import { markdownProEntry, paperSearchDataHome } from "../../infrastructure/school/index.js";
/**
 * Where Pro's releases are published. For now the private repository's releases, which only a
 * computer signed in to its GitHub account can download (user, 2026-11-18: testing the 安装 with a
 * private PaperSearch); a public address replaces it before Pro is offered to others.
 */
export const PRO_RELEASE_URL = "github:dr-dumpling/PaperSearch-Pro";
/** Where an install puts Pro: PaperSearch's data, where the command line loads it from by default. */
export function proInstallDir(env = process.env) {
    return join(paperSearchDataHome(env), "pro");
}
/** Whether Pro is there, where the command line loads it from, and its version. */
export function proStatus(env = process.env) {
    const path = markdownProEntry(env);
    if (!existsSync(path))
        return { installed: false, version: "", path };
    try {
        const manifest = JSON.parse(readFileSync(join(dirname(path), "pro.json"), "utf8"));
        return { installed: true, version: typeof manifest.version === "string" ? manifest.version : "", path };
    }
    catch {
        return { installed: true, version: "", path };
    }
}
/** A failure with its own code and words, rather than pro_install_failed's. */
class ProInstallError extends Error {
    code;
    constructor(code, message) {
        super(message);
        this.code = code;
    }
}
function folderSource(folder) {
    return {
        manifest: async () => JSON.parse(readFileSync(join(folder, "pro.json"), "utf8")),
        bundle: async (onProgress) => {
            const data = readFileSync(join(folder, "index.js"));
            onProgress(data.length, data.length);
            return data;
        },
    };
}
function webSource(address, timeoutMs) {
    const base = address.replace(/\/+$/, "");
    const headers = { "User-Agent": USER_AGENT };
    return {
        manifest: async () => (await axios.get(`${base}/pro.json`, { timeout: timeoutMs, headers, responseType: "json" })).data,
        bundle: async (onProgress) => {
            const response = await axios.get(`${base}/index.js`, { timeout: timeoutMs, headers, responseType: "stream" });
            const total = Number(response.headers["content-length"]) || 0;
            const chunks = [];
            let done = 0;
            for await (const chunk of response.data) {
                chunks.push(chunk);
                done += chunk.length;
                onProgress(done, total);
            }
            return Buffer.concat(chunks);
        },
    };
}
/** This computer's GitHub login: GH_TOKEN or GITHUB_TOKEN, else what `gh auth token` gives; never shown or kept. */
function githubToken(env) {
    const given = (env.GH_TOKEN || env.GITHUB_TOKEN || "").trim();
    if (given)
        return given;
    // The settings window may not have the shell's PATH: gh's usual places too.
    for (const gh of ["gh", "/opt/homebrew/bin/gh", "/usr/local/bin/gh", "C:\\Program Files\\GitHub CLI\\gh.exe"]) {
        try {
            const token = execFileSync(gh, ["auth", "token"], { encoding: "utf8", timeout: 10_000, windowsHide: true,
                stdio: ["ignore", "pipe", "ignore"] }).trim();
            if (token)
                return token;
        }
        catch {
            // not there, or not signed in
        }
    }
    return "";
}
function githubSource(owner, repo, token, timeoutMs) {
    const headers = { "User-Agent": USER_AGENT, "X-GitHub-Api-Version": "2022-11-28",
        ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    let assets;
    const release = () => assets ??= (async () => {
        try {
            const listed = (await axios.get(`https://api.github.com/repos/${owner}/${repo}/releases?per_page=30`, { timeout: timeoutMs, headers: { ...headers, Accept: "application/vnd.github+json" } })).data;
            // Newest first: the first published Pro release.
            const found = listed.find((item) => !item.draft && item.tag_name.startsWith("pro-v"));
            if (!found)
                throw new ProInstallError("pro_release_not_found", "GitHub 上没找到 Pro 安装包");
            return found.assets;
        }
        catch (error) {
            // A private repository answers 404 to whoever is not signed in to an account that may read it.
            if (axios.isAxiosError(error) && [401, 403, 404].includes(error.response?.status ?? 0)) {
                throw token ? new ProInstallError("pro_release_not_found", "GitHub 上没找到 Pro 安装包")
                    : new ProInstallError("pro_github_login_required", "请先在终端运行 gh auth login 登录 GitHub");
            }
            throw error;
        }
    })();
    const asset = async (name) => {
        const found = (await release()).find((item) => item.name === name);
        if (!found)
            throw new ProInstallError("pro_release_invalid", "安装包不全");
        return found;
    };
    // An asset's address answers with the file (by way of GitHub's storage, which gets no login).
    const download = { headers: { ...headers, Accept: "application/octet-stream" }, timeout: timeoutMs };
    return {
        manifest: async () => {
            const response = await axios.get((await asset("pro.json")).url, { ...download, responseType: "arraybuffer" });
            return JSON.parse(Buffer.from(response.data).toString("utf8"));
        },
        bundle: async (onProgress) => {
            const found = await asset("index.js");
            const response = await axios.get(found.url, { ...download, responseType: "stream" });
            const chunks = [];
            let done = 0;
            for await (const chunk of response.data) {
                chunks.push(chunk);
                done += chunk.length;
                onProgress(done, found.size);
            }
            return Buffer.concat(chunks);
        },
    };
}
function sourceOf(from, env, timeoutMs, token) {
    const given = (from ?? env.PAPER_SEARCH_PRO_RELEASE_URL ?? PRO_RELEASE_URL).trim();
    if (!given)
        return undefined;
    const github = /^github:([\w.-]+)\/([\w.-]+)$/i.exec(given);
    if (github)
        return githubSource(github[1], github[2], token ?? githubToken(env), timeoutMs);
    return /^https?:\/\//i.test(given) ? webSource(given, timeoutMs) : folderSource(given);
}
/** "0.1.10" is newer than "0.1.9"; a pre-release ("0.2.0-beta.1") is older than its release. */
export function newerVersion(candidate, current) {
    const parse = (value) => {
        const [main, pre = ""] = value.trim().replace(/^v/, "").split("-", 2);
        return { parts: main.split(".").map((part) => Number.parseInt(part, 10) || 0), pre };
    };
    const a = parse(candidate), b = parse(current);
    for (let i = 0; i < Math.max(a.parts.length, b.parts.length); i += 1) {
        const diff = (a.parts[i] ?? 0) - (b.parts[i] ?? 0);
        if (diff)
            return diff > 0;
    }
    if (!a.pre !== !b.pre)
        return !a.pre;
    return a.pre.localeCompare(b.pre, "en", { numeric: true }) > 0;
}
/** The newest Pro released, beside the one installed: the settings window's 检查更新 (user, 2026-11-19). */
export async function checkPro(options = {}) {
    const env = options.env ?? process.env;
    const source = sourceOf(options.from, env, options.timeoutMs ?? 30_000, options.githubToken);
    if (!source)
        return { ok: false, code: "pro_release_unavailable", message: "PaperSearch Pro 的下载地址还没开放" };
    try {
        const manifest = await source.manifest();
        if (!manifest || typeof manifest.version !== "string" || !manifest.version) {
            return { ok: false, code: "pro_release_invalid", message: "安装包的说明文件不对" };
        }
        const installed = proStatus(env);
        return { ok: true, installed: installed.installed, version: installed.version, latest: manifest.version,
            update: installed.installed && (!installed.version || newerVersion(manifest.version, installed.version)) };
    }
    catch (error) {
        if (error instanceof ProInstallError)
            return { ok: false, code: error.code, message: error.message };
        return { ok: false, code: "pro_check_failed", message: axios.isAxiosError(error) && !error.response ? "网络连接中断" : "检查更新出错" };
    }
}
/** Installs Pro into PaperSearch's data, replacing the one there only once the new one is whole and checked. */
export async function installPro(options = {}) {
    const env = options.env ?? process.env;
    const source = sourceOf(options.from, env, options.timeoutMs ?? 60_000, options.githubToken);
    if (!source)
        return { ok: false, code: "pro_release_unavailable", message: "PaperSearch Pro 的下载地址还没开放" };
    const target = proInstallDir(env);
    const staging = `${target}.installing-${process.pid}`;
    try {
        const manifest = await source.manifest();
        if (!manifest || typeof manifest.version !== "string" || !manifest.version) {
            return { ok: false, code: "pro_release_invalid", message: "安装包的说明文件不对" };
        }
        const bundle = await source.bundle((done, total) => options.onProgress?.(done, total || manifest.bytes || 0));
        if (manifest.sha256 && createHash("sha256").update(bundle).digest("hex") !== manifest.sha256.toLowerCase()) {
            return { ok: false, code: "pro_checksum_mismatch", message: "安装包不完整或被改动过" };
        }
        rmSync(staging, { recursive: true, force: true });
        mkdirSync(staging, { recursive: true });
        writeFileSync(join(staging, "index.js"), bundle);
        writeFileSync(join(staging, "pro.json"), `${JSON.stringify(manifest, null, 2)}\n`);
        // Pro's own records beside it (access.json, the Markdown counted) stay through an update.
        if (existsSync(target)) {
            for (const name of readdirSync(target)) {
                if (name !== "index.js" && name !== "pro.json")
                    cpSync(join(target, name), join(staging, name), { recursive: true });
            }
        }
        const old = `${target}.old-${process.pid}`;
        if (existsSync(target))
            renameSync(target, old);
        renameSync(staging, target);
        rmSync(old, { recursive: true, force: true });
        return { ok: true, version: manifest.version, path: join(target, "index.js") };
    }
    catch (error) {
        rmSync(staging, { recursive: true, force: true });
        if (error instanceof ProInstallError)
            return { ok: false, code: error.code, message: error.message };
        const reason = axios.isAxiosError(error) ? (error.response ? "服务器没有给出安装文件" : "网络连接中断")
            : error?.code === "ENOENT" ? "找不到安装文件" : "安装出错";
        return { ok: false, code: "pro_install_failed", message: reason };
    }
}
//# sourceMappingURL=install.js.map