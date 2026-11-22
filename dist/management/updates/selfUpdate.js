/**
 * PaperSearch's own update, for the settings window's 更新 (user, 2026-11-21: one version, one button, Pro with it).
 * Where an install updates itself from is its package's `paperSearch.updateFrom`:
 * the private install says `github:<owner>/<repo>#<branch>` (written by maintainer/release-public.py), read with this
 * computer's GitHub login as Pro's releases are; any other install updates from npm's stable releases.
 * The install runs the npm that came with the node running PaperSearch, not whatever the window's PATH finds, and
 * puts the new version where this one is (its global prefix): a computer with two nodes (Homebrew's and fnm's on the
 * maintainer's Mac, 2026-11-21) ran this copy with the other node, whose npm would have made a second copy beside it.
 */
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import axios from "axios";
import { USER_AGENT } from "../../config/constants.js";
import { GITHUB_LOGIN_REQUIRED, githubLoginMissing, githubToken } from "../pro/install.js";
import { compareStableRelease, queryLatestStable, RELEASE_NOTES } from "./index.js";
/** The package's own update source: `github:<owner>/<repo>#<branch>`, else npm. */
export function updateSourceOf(pkg) {
    const given = String(pkg?.paperSearch?.updateFrom ?? "");
    const github = /^github:([\w.-]+)\/([\w.-]+)(?:#([\w./-]+))?$/.exec(given);
    return github ? { kind: "github", owner: github[1], repo: github[2], branch: github[3] || "main" } : { kind: "npm" };
}
/** -1, 0 or 1 by precedence (pre-release parts compared as numbers where they are: preview.10 after preview.9);
 *  undefined for what is no version. */
export function compareVersions(a, b) {
    const parse = (value) => /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/.exec(value.trim());
    const x = parse(a), y = parse(b);
    if (!x || !y)
        return undefined;
    for (let i = 1; i <= 3; i += 1) {
        const diff = Number(x[i]) - Number(y[i]);
        if (diff)
            return Math.sign(diff);
    }
    if (!x[4] !== !y[4])
        return x[4] ? -1 : 1;
    if (!x[4])
        return 0;
    const left = x[4].split("."), right = y[4].split(".");
    for (let i = 0; i < Math.max(left.length, right.length); i += 1) {
        if (left[i] === undefined)
            return -1;
        if (right[i] === undefined)
            return 1;
        const numeric = /^\d+$/.test(left[i]) && /^\d+$/.test(right[i]);
        const diff = numeric ? Number(left[i]) - Number(right[i]) : left[i].localeCompare(right[i]);
        if (diff)
            return Math.sign(diff);
    }
    return 0;
}
/** No login to read: none on this computer, or one gh has that cannot be read here (over SSH on macOS). */
function noLogin(ghStatus) {
    const missing = githubLoginMissing(ghStatus);
    return missing.unreadable ? { code: "github_login_unreadable", message: missing.message }
        : { code: "github_login_required", message: missing.message };
}
function githubHeaders(token, accept) {
    return { "User-Agent": USER_AGENT, "X-GitHub-Api-Version": "2022-11-28", Accept: accept, Authorization: `Bearer ${token}` };
}
/** The newest version where this install updates from, beside the one running. */
export async function checkSelf(options) {
    const { current, source } = options;
    const timeout = options.timeoutMs ?? 15_000;
    if (source.kind === "npm") {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeout);
        try {
            const latest = await (options.queryNpm ?? queryLatestStable)(controller.signal);
            const compared = compareStableRelease(current, latest);
            if (compared === undefined)
                return { ok: false, source: "npm", current, code: "update_check_failed", message: "检查更新出错" };
            return { ok: true, source: "npm", current, latest, update: compared > 0, releaseNotesUrl: RELEASE_NOTES };
        }
        catch {
            return { ok: false, source: "npm", current, code: "update_check_failed", message: "检查更新出错，请稍后再试" };
        }
        finally {
            clearTimeout(timer);
        }
    }
    const token = options.githubToken ?? githubToken(options.env ?? process.env);
    if (!token)
        return { ok: false, source: "github", current, ...noLogin(options.ghStatus) };
    try {
        const response = await (options.get ?? axios.get)(`https://api.github.com/repos/${source.owner}/${source.repo}/contents/package.json?ref=${encodeURIComponent(source.branch ?? "main")}`, { timeout, headers: githubHeaders(token, "application/vnd.github.raw"), responseType: "text", transformResponse: (data) => data });
        const latest = String(JSON.parse(String(response.data)).version ?? "");
        const compared = compareVersions(latest, current);
        if (compared === undefined)
            return { ok: false, source: "github", current, code: "update_check_failed", message: "检查更新出错" };
        return { ok: true, source: "github", current, latest, update: compared > 0,
            releaseNotesUrl: `https://github.com/${source.owner}/${source.repo}/blob/${source.branch ?? "main"}/CHANGELOG.md` };
    }
    catch (error) {
        const status = axios.isAxiosError(error) ? error.response?.status ?? 0 : 0;
        return status === 401 || status === 403 || status === 404
            ? { ok: false, source: "github", current, code: "github_login_required", message: GITHUB_LOGIN_REQUIRED }
            : { ok: false, source: "github", current, code: "update_check_failed", message: "检查更新出错，请稍后再试" };
    }
}
/**
 * The npm prefix a global install of PaperSearch sits in: `<prefix>/lib/node_modules/papersearch` with
 * `<prefix>/bin/paper-search`, or on Windows `<prefix>\node_modules\papersearch` with `<prefix>\paper-search.cmd`;
 * "" for anything else (a checkout, a project's own node_modules, npx).
 */
export function globalPrefixOf(packageRoot, platform = process.platform) {
    const modules = dirname(resolve(packageRoot));
    if (basename(modules) !== "node_modules")
        return "";
    const above = dirname(modules);
    if (platform === "win32")
        return existsSync(join(above, "paper-search.cmd")) ? above : "";
    return basename(above) === "lib" && existsSync(join(dirname(above), "bin", "paper-search")) ? dirname(above) : "";
}
/**
 * The PaperSearch copies the PATH finds, one per package (a command linked from two places counts once). Two on one
 * computer are updated apart, and the older one, run, takes the school extension back to its own version (the
 * maintainer's Mac, 2026-11-21: fnm's node had 0.7.1-preview.1 before Homebrew's 0.7.2-preview.5 in the PATH).
 */
export function installedCopies(pathEnv = process.env.PATH ?? "", platform = process.platform) {
    const found = new Map();
    for (const dir of pathEnv.split(platform === "win32" ? ";" : ":").filter(Boolean)) {
        const command = join(dir, platform === "win32" ? "paper-search.cmd" : "paper-search");
        let root;
        try {
            if (!existsSync(command))
                continue;
            root = platform === "win32" ? join(dir, "node_modules", "papersearch") : dirname(dirname(realpathSync(command)));
            root = realpathSync(root);
        }
        catch {
            continue;
        }
        if (found.has(root))
            continue;
        try {
            const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
            // PaperSearch's own command, not another program's of the same name.
            if (!pkg.bin || typeof pkg.bin !== "object" || !("paper-search" in pkg.bin))
                continue;
            found.set(root, { command, version: String(pkg.version ?? ""), root });
        }
        catch {
            // not a package
        }
    }
    return [...found.values()];
}
/** npm as the node running PaperSearch has it (its npm-cli.js beside it), else `npm` on the PATH. */
export function npmCommand(execPath = process.execPath, platform = process.platform) {
    const cli = platform === "win32" ? join(dirname(execPath), "node_modules", "npm", "bin", "npm-cli.js")
        : join(dirname(execPath), "..", "lib", "node_modules", "npm", "bin", "npm-cli.js");
    return existsSync(cli) ? [execPath, cli] : [platform === "win32" ? "npm.cmd" : "npm"];
}
/** The version ``checked`` found, installed over this one with npm (-g). */
export async function installSelf(checked, options) {
    const npm = options.npm ?? npmCommand();
    const run = options.run ?? ((argv) => {
        const done = spawnSync(argv[0], argv.slice(1), { encoding: "utf8", windowsHide: true, timeout: 600_000,
            shell: process.platform === "win32" && !argv[0].endsWith(".exe") && argv[0].endsWith(".cmd") });
        return { status: done.status, stderr: String(done.stderr ?? "") };
    });
    let target = `papersearch@${checked.latest}`;
    let folder = "";
    try {
        if (options.source.kind === "github") {
            // The repository's own tarball, read with the login (npm cannot send one), kept as a file npm installs.
            const token = options.githubToken ?? githubToken(options.env ?? process.env);
            if (!token)
                return { ok: false, ...noLogin(options.ghStatus) };
            const { owner, repo, branch } = options.source;
            const response = await (options.get ?? axios.get)(`https://api.github.com/repos/${owner}/${repo}/tarball/${encodeURIComponent(branch ?? "main")}`, { timeout: 300_000, responseType: "arraybuffer", maxRedirects: 5, headers: githubHeaders(token, "application/vnd.github+json") });
            folder = mkdtempSync(join(tmpdir(), "papersearch-update-"));
            target = join(folder, `papersearch-${checked.latest}.tgz`);
            writeFileSync(target, Buffer.from(response.data));
        }
        const done = run([...npm, "install", "-g", ...(options.prefix ? ["--prefix", options.prefix] : []), "--no-audit", "--no-fund", target]);
        if (done.status !== 0) {
            const denied = /EACCES|EPERM|permission denied/i.test(done.stderr);
            return { ok: false, code: denied ? "npm_permission_denied" : "npm_install_failed",
                message: denied ? "没有权限更新全局安装的 PaperSearch，请在终端运行更新命令" : "更新 PaperSearch 出错" };
        }
        return { ok: true, from: checked.current, to: checked.latest };
    }
    catch {
        return { ok: false, code: "update_download_failed", message: "下载新版本出错，请稍后再试" };
    }
    finally {
        if (folder)
            rmSync(folder, { recursive: true, force: true });
    }
}
//# sourceMappingURL=selfUpdate.js.map