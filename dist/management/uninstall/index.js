import { existsSync, lstatSync, readdirSync, readFileSync, realpathSync, rmdirSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, relative, resolve } from "node:path";
import { paperSearchDataRoot } from "../skills/autoSync.js";
import { resolveRunLogRoot } from "../../infrastructure/runlog/RunLedger.js";
import { SKILL_NAME } from "../../skills/SkillInstaller.js";
/**
 * `paper-search uninstall` (user, 2026-11-11): everything PaperSearch keeps on the
 * computer, removed in one go once the user agrees. Downloaded papers, Chrome and
 * Node.js stay; the npm package itself is removed last by the user with
 * `npm uninstall -g papersearch` (a running program cannot reliably remove itself
 * on Windows).
 */
export const NPM_UNINSTALL = "npm uninstall -g papersearch";
const DATA_PARTS = [
    ["school-runtime", "学校订阅下载程序"],
    ["school", "学校设置和登录状态"],
    // Their names before 0.6.1, while not yet taken over.
    ["carsi-runtime", "学校订阅下载程序"],
    ["carsi", "学校设置和登录状态"],
    ["runs", "运行记录"],
    ["skill-backups", "Skill 备份"],
];
/** What `paper-search uninstall` removes and keeps, read from the disk; nothing is changed. */
export function uninstallPlan(env = process.env, home = homedir(), options = {}) {
    const items = [];
    const dataRoot = paperSearchDataRoot(env, home);
    if (existsSync(dataRoot)) {
        const parts = [...new Set(DATA_PARTS.filter(([name]) => existsSync(join(dataRoot, name))).map(([, label]) => label))];
        items.push({ label: `数据（${[...parts, "其他记录"].join("、")}）`, path: dataRoot, kind: "folder", bytes: bytesOf(dataRoot) });
    }
    const runs = resolveRunLogRoot(env, home);
    if (runs && existsSync(runs) && !inside(runs, dataRoot)) {
        items.push({ label: "运行记录", path: runs, kind: "folder", bytes: bytesOf(runs) });
    }
    items.push(...configItems(env, home));
    items.push(...skillItems(home));
    const lock = join(home, ".agents", ".skill-lock.json");
    if (lockHasSkill(lock)) {
        items.push({ label: "npx skills 安装记录里的 paper-search 一项", path: lock, kind: "entry", bytes: 0 });
    }
    const kept = [
        ...(options.downloads ? [`下载的论文：${options.downloads}`] : []),
        "Google Chrome、Node.js",
        `命令本身：最后运行 ${NPM_UNINSTALL}`,
    ];
    return { items, kept };
}
/** Remove what the plan lists; what could not be removed is reported, the rest still goes. */
export function runUninstall(plan) {
    const result = { removed: [], failed: [] };
    for (const item of plan.items) {
        try {
            if (item.kind === "entry")
                removeLockEntry(item.path);
            else if (item.kind === "link")
                removeLink(item.path);
            // Node removes links inside a folder without following them (Windows junctions too).
            else
                rmSync(item.path, { recursive: true, force: true });
            result.removed.push(item.path);
        }
        catch (error) {
            result.failed.push({ path: item.path, error: String(error?.code || error?.message || error) });
        }
    }
    return result;
}
export function renderUninstallPlan(plan) {
    return [
        "将要删除 PaperSearch 的以下内容：",
        ...plan.items.map((item) => `  ${item.label}：${item.path}${item.kind === "link" ? "（链接）" : ""}${item.bytes >= 1024 * 1024 ? `（${(item.bytes / 1024 / 1024).toFixed(0)} MB）` : ""}`),
        "保留：",
        ...plan.kept.map((line) => `  ${line}`),
    ];
}
/** The config file; its own folder only where PaperSearch chose it. */
function configItems(env, home) {
    const label = "配置（API key、下载文件夹等设置）";
    if (env.PAPER_SEARCH_CONFIG_FILE) {
        const file = resolve(env.PAPER_SEARCH_CONFIG_FILE);
        return existsSync(file) ? [{ label, path: file, kind: "file", bytes: bytesOf(file) }] : [];
    }
    if (env.PAPER_SEARCH_CONFIG_DIR) {
        const file = join(resolve(env.PAPER_SEARCH_CONFIG_DIR), "config.json");
        return existsSync(file) ? [{ label, path: file, kind: "file", bytes: bytesOf(file) }] : [];
    }
    const folder = join(home, ".config", "paper-search-cli");
    return existsSync(folder) ? [{ label, path: folder, kind: "folder", bytes: bytesOf(folder) }] : [];
}
/**
 * Every copy of this Skill in the AI tools' skill folders under the home folder
 * (`~/.<tool>/skills`, `~/.<tool>/<part>/skills`): the folders whose SKILL.md is
 * named paper-search, once each however they are reached, and the links to it.
 */
function skillItems(home) {
    const candidates = [];
    for (const dot of entries(home).filter((name) => name.startsWith("."))) {
        candidates.push(join(home, dot, "skills", SKILL_NAME));
        for (const part of entries(join(home, dot)))
            candidates.push(join(home, dot, part, "skills", SKILL_NAME));
    }
    const items = [];
    const folders = new Set();
    for (const path of candidates) {
        let stat;
        try {
            stat = lstatSync(path);
        }
        catch {
            continue;
        }
        const tool = relative(home, path).split(/[\\/]/)[0].replace(/^\./, "");
        if (stat.isSymbolicLink()) {
            // A link left without its folder (the folder removed by another tool) goes too.
            if (!existsSync(path) || isThisSkill(path)) {
                items.push({ label: `Skill（${tool}）`, path, kind: "link", bytes: 0 });
            }
            continue;
        }
        if (!stat.isDirectory() || !isThisSkill(path))
            continue;
        const real = realpathSync(path);
        if (folders.has(real))
            continue; // the same folder through a linked parent (Windows: .claude\skills)
        folders.add(real);
        items.push({ label: `Skill（${tool}）`, path, kind: "folder", bytes: bytesOf(path) });
    }
    return items;
}
function isThisSkill(folder) {
    try {
        return /^name:\s*paper-search\s*$/m.test(readFileSync(join(folder, "SKILL.md"), "utf8"));
    }
    catch {
        return false;
    }
}
function lockHasSkill(file) {
    try {
        return Boolean(JSON.parse(readFileSync(file, "utf8"))?.skills?.[SKILL_NAME]);
    }
    catch {
        return false;
    }
}
/** `npx skills` keeps one lock for all its skills: only this Skill's entry goes. */
function removeLockEntry(file) {
    const lock = JSON.parse(readFileSync(file, "utf8"));
    delete lock.skills[SKILL_NAME];
    writeFileSync(file, `${JSON.stringify(lock, null, 2)}\n`);
}
function removeLink(path) {
    try {
        unlinkSync(path);
    }
    catch (error) {
        // A directory link on Windows (a junction) is removed as an empty directory.
        if (error?.code !== "EPERM" && error?.code !== "EISDIR")
            throw error;
        rmdirSync(path);
    }
}
function entries(folder) {
    try {
        return readdirSync(folder);
    }
    catch {
        return [];
    }
}
function inside(path, folder) {
    const rel = relative(resolve(folder), resolve(path));
    return rel === "" || (!rel.startsWith("..") && !/^[a-zA-Z]:/.test(rel));
}
function bytesOf(path) {
    let stat;
    try {
        stat = lstatSync(path);
    }
    catch {
        return 0;
    }
    if (!stat.isDirectory())
        return stat.size;
    let total = 0;
    for (const name of entries(path))
        total += bytesOf(join(path, name));
    return total;
}
//# sourceMappingURL=index.js.map