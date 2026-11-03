import { copyFileSync, existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from 'fs';
import { homedir } from 'os';
import { dirname, join, resolve } from 'path';
import { SKILL_TARGETS, bundledSkillHash, installSkillTargets, statusSkillTargets } from '../../skills/SkillInstaller.js';
const INSTALL_HINT = [
    'paper-search：还没有给 AI 工具安装 paper-search 的 Skill，AI 工具因此不知道怎么调用 paper-search。',
    '运行 paper-search setup 选择要装到哪些工具，或运行 paper-search skills update --targets claude（换成你用的工具：codex、cursor 等）。（这条提示只出现一次）'
].join('\n');
/** `${XDG_DATA_HOME:-~/.local/share}/paper-search-cli` */
export function paperSearchDataRoot(env = process.env, home = homedir()) {
    const base = env.XDG_DATA_HOME ? resolve(env.XDG_DATA_HOME) : join(home, '.local', 'share');
    return join(base, 'paper-search-cli');
}
/** The Skill's installed copies, one per directory; targets without it are left out. */
export function skillLocations(options = {}) {
    const status = statusSkillTargets(SKILL_TARGETS.map(target => target.id), options);
    const byDirectory = new Map();
    for (const target of status.targets) {
        if (target.status === 'missing')
            continue;
        const directory = realDirectory(target.path);
        const known = byDirectory.get(directory);
        if (known) {
            known.targets.push(target.target);
            continue;
        }
        byDirectory.set(directory, {
            targets: [target.target],
            path: target.path,
            status: target.status,
            staleFiles: target.staleFiles,
            missingFiles: target.missingFiles,
            extraFiles: target.extraFiles,
            ...(target.error ? { error: target.error } : {})
        });
    }
    return [...byDirectory.values()];
}
/**
 * Once per bundled Skill (the first run after an install or upgrade): bring every
 * copy the user installed up to it, backing up the files it replaces; never
 * installs where there is none, and keeps the user's own files. With no copy
 * anywhere it returns a one-time hint. A failed update is retried on the next run.
 */
export function autoSyncSkill(options = {}) {
    const dataRoot = options.dataRoot ?? paperSearchDataRoot();
    const statePath = join(dataRoot, 'skill-sync.json');
    const state = readState(statePath);
    const bundledHash = bundledSkillHash(options.sourceRoot);
    if (state.bundledHash === bundledHash)
        return { action: 'unchanged' };
    const locations = skillLocations(options);
    if (locations.length === 0) {
        writeState(statePath, { bundledHash, installHintShown: true });
        return state.installHintShown ? { action: 'not_installed' } : { action: 'not_installed', notice: INSTALL_HINT };
    }
    const stale = locations.filter(location => location.status === 'stale');
    const failures = locations
        .filter(location => location.status === 'error')
        .map(location => `${location.path}：${location.error}`);
    if (stale.length === 0 && failures.length === 0) {
        writeState(statePath, { ...state, bundledHash });
        return { action: 'up_to_date' };
    }
    const backupDir = join(dataRoot, 'skill-backups', `${stamp(options.now ?? new Date())}-auto`);
    let backedUp = 0;
    const updated = [];
    for (const location of stale) {
        try {
            backedUp += backUp(location, join(backupDir, location.targets[0]));
            const result = installSkillTargets([location.targets[0]], options);
            if (result.failed.length > 0) {
                failures.push(`${location.path}：${result.failed[0].error}`);
                continue;
            }
            updated.push(location);
        }
        catch (error) {
            failures.push(`${location.path}：${error?.message || String(error)}`);
        }
    }
    const backup = backedUp > 0 ? { backupDir } : {};
    if (failures.length > 0) {
        const targets = [...stale, ...locations.filter(location => location.status === 'error')]
            .map(location => location.targets[0]);
        return {
            action: 'failed',
            updated,
            ...backup,
            notice: `paper-search：Skill 自动更新没有完成（${failures.join('；')}）。` +
                `可运行 paper-search skills update --targets ${targets.join(',')} 手动更新。`
        };
    }
    writeState(statePath, { ...state, bundledHash });
    const version = options.version ? ` ${options.version}` : '';
    return {
        action: 'updated',
        updated,
        ...backup,
        notice: `paper-search：已把 AI 工具里的 paper-search Skill 更新到当前版本${version}（${updated.map(location => location.path).join('、')}）` +
            (backedUp > 0 ? `；替换下来的旧文件在 ${backupDir}` : '') +
            '。新开的 AI 会话会读到新版本。'
    };
}
function backUp(location, directory) {
    for (const relPath of location.staleFiles) {
        const to = join(directory, relPath);
        mkdirSync(dirname(to), { recursive: true });
        copyFileSync(join(location.path, relPath), to);
    }
    return location.staleFiles.length;
}
function readState(path) {
    if (!existsSync(path))
        return {};
    try {
        const parsed = JSON.parse(readFileSync(path, 'utf8'));
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    }
    catch {
        // Only this module writes the file; an unreadable one is checked afresh and rewritten.
        return {};
    }
}
function writeState(path, state) {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, `${JSON.stringify(state, null, 2)}\n`);
}
function realDirectory(path) {
    try {
        return realpathSync(path);
    }
    catch {
        return path;
    }
}
function stamp(date) {
    const pad = (value) => String(value).padStart(2, '0');
    return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-` +
        `${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}
//# sourceMappingURL=autoSync.js.map