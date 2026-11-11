import { copyFileSync, existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from 'fs';
import { homedir } from 'os';
import { dirname, join, resolve } from 'path';
import {
  SKILL_TARGETS,
  bundledSkillHash,
  describeSkillTargets,
  installSkillTargets,
  statusSkillTargets,
  type SkillTargetStatus
} from '../../skills/SkillInstaller.js';

/** One installed copy of the Skill. Targets whose directories resolve to the same
 * place (a linked ~/.claude/skills sharing ~/.agents/skills) are one copy. */
export interface SkillLocation {
  targets: string[];
  path: string;
  status: SkillTargetStatus['status'];
  staleFiles: string[];
  missingFiles: string[];
  extraFiles: string[];
  error?: string;
  /** The PaperSearch version the copy's SKILL.md names (metadata.version), when it names one. */
  version?: string;
}

export interface SkillAutoSyncOptions {
  skillsRoot?: string;
  sourceRoot?: string;
  /** PaperSearch's data directory, where the sync state and backups go. */
  dataRoot?: string;
  version?: string;
  now?: Date;
}

export interface SkillAutoSyncResult {
  action: 'unchanged' | 'up_to_date' | 'updated' | 'not_installed' | 'failed';
  notice?: string;
  updated?: SkillLocation[];
  backupDir?: string;
}

interface SkillSyncState {
  bundledHash?: string;
  installHintShown?: boolean;
  /** When the user was last told the installed Skill is newer than this command (ms). */
  newerSkillNoticeAt?: number;
}

const DAY = 24 * 60 * 60 * 1000;

const INSTALL_HINT = [
  'paper-search：还没有给 AI 工具安装 paper-search 的 Skill，AI 工具因此不知道怎么调用 paper-search。',
  '运行 paper-search setup 选择要装到哪些工具，或运行 paper-search skills update --targets claude（换成你用的工具：codex、cursor 等）。（这条提示只出现一次）'
].join('\n');

/** `${XDG_DATA_HOME:-~/.local/share}/paper-search-cli` */
export function paperSearchDataRoot(env: NodeJS.ProcessEnv = process.env, home = homedir()): string {
  const base = env.XDG_DATA_HOME ? resolve(env.XDG_DATA_HOME) : join(home, '.local', 'share');
  return join(base, 'paper-search-cli');
}

/** The PaperSearch version a copy of the Skill names in its SKILL.md front matter (``metadata.version``). */
export function skillVersion(directory: string): string | undefined {
  let text: string;
  try {
    text = readFileSync(join(directory, 'SKILL.md'), 'utf8');
  } catch {
    return undefined;
  }
  const front = /^---\r?\n([\s\S]*?)\r?\n---/.exec(text)?.[1] ?? '';
  const metadata = /^metadata:[ \t]*\r?\n((?:[ \t]+.*(?:\r?\n|$))*)/m.exec(front)?.[1] ?? '';
  return /^[ \t]+version:[ \t]*["']?(\d+\.\d+\.\d+)["']?[ \t]*$/m.exec(metadata)?.[1];
}

/** ``a`` is a later X.Y.Z than ``b``; false when either is missing. */
export function isNewerVersion(a?: string, b?: string): boolean {
  const parts = (value?: string) => /^(\d+)\.(\d+)\.(\d+)/.exec(value ?? '')?.slice(1).map(Number);
  const x = parts(a);
  const y = parts(b);
  if (!x || !y) return false;
  for (let i = 0; i < 3; i += 1) if (x[i] !== y[i]) return x[i] > y[i];
  return false;
}

/** Installed copies naming a later PaperSearch than ``version``: read from SKILL.md alone, on every run. */
function newerCopies(version: string | undefined, skillsRoot?: string): Array<{ path: string; version: string }> {
  if (!version) return [];
  const seen = new Set<string>();
  const newer: Array<{ path: string; version: string }> = [];
  for (const target of describeSkillTargets(SKILL_TARGETS.map(item => item.id), skillsRoot)) {
    const directory = realDirectory(target.path);
    if (seen.has(directory)) continue;
    seen.add(directory);
    const found = skillVersion(target.path);
    if (found && isNewerVersion(found, version)) newer.push({ path: target.path, version: found });
  }
  return newer;
}

/** The Skill's installed copies, one per directory; targets without it are left out. */
export function skillLocations(options: { skillsRoot?: string; sourceRoot?: string } = {}): SkillLocation[] {
  const status = statusSkillTargets(SKILL_TARGETS.map(target => target.id), options);
  const byDirectory = new Map<string, SkillLocation>();
  for (const target of status.targets) {
    if (target.status === 'missing') continue;
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
      ...(target.error ? { error: target.error } : {}),
      ...(skillVersion(target.path) ? { version: skillVersion(target.path) } : {})
    });
  }
  return [...byDirectory.values()];
}

/**
 * Once per bundled Skill (the first run after an install or upgrade): bring every
 * copy the user installed up to it, backing up the files it replaces; never
 * installs where there is none, and keeps the user's own files. With no copy
 * anywhere it returns a one-time hint. A failed update is retried on the next run.
 *
 * A copy naming a later PaperSearch than this command (the Skill installed from
 * GitHub, the command older) is never replaced: on every run it is checked from its
 * SKILL.md, and the user is told to update the command, once a day (user, 2026-11-11;
 * an older command had put its own Skill back over a newer one).
 */
export function autoSyncSkill(options: SkillAutoSyncOptions = {}): SkillAutoSyncResult {
  const dataRoot = options.dataRoot ?? paperSearchDataRoot();
  const statePath = join(dataRoot, 'skill-sync.json');
  let state = readState(statePath);
  const now = options.now ?? new Date();
  const newer = newerCopies(options.version, options.skillsRoot);
  let newerNotice: string | undefined;
  if (newer.length && !(state.newerSkillNoticeAt && now.getTime() - state.newerSkillNoticeAt < DAY)) {
    const latest = newer.map(copy => copy.version).sort((a, b) => (isNewerVersion(a, b) ? -1 : 1))[0];
    // One version for the Skill and the command: a later Skill means a later PaperSearch (user, 2026-11-11).
    newerNotice = `paper-search：PaperSearch 有新版本 ${latest}，本机版本为 ${options.version}，请运行 npm install -g papersearch@latest 更新。`;
    state = { ...state, newerSkillNoticeAt: now.getTime() };
    writeState(statePath, state);
  }
  const withNotice = (result: SkillAutoSyncResult): SkillAutoSyncResult => {
    const notice = [result.notice, newerNotice].filter(Boolean).join('\n');
    return notice ? { ...result, notice } : result;
  };
  const bundledHash = bundledSkillHash(options.sourceRoot);
  if (state.bundledHash === bundledHash) return withNotice({ action: 'unchanged' });

  const locations = skillLocations(options);
  if (locations.length === 0) {
    writeState(statePath, { ...state, bundledHash, installHintShown: true });
    return state.installHintShown ? { action: 'not_installed' } : { action: 'not_installed', notice: INSTALL_HINT };
  }

  const stale = locations.filter(location => location.status === 'stale' && !isNewerVersion(location.version, options.version));
  const failures = locations
    .filter(location => location.status === 'error')
    .map(location => `${location.path}：${location.error}`);
  if (stale.length === 0 && failures.length === 0) {
    writeState(statePath, { ...state, bundledHash });
    return withNotice({ action: 'up_to_date' });
  }

  const backupDir = join(dataRoot, 'skill-backups', `${stamp(now)}-auto`);
  let backedUp = 0;
  const updated: SkillLocation[] = [];
  for (const location of stale) {
    try {
      backedUp += backUp(location, join(backupDir, location.targets[0]));
      const result = installSkillTargets([location.targets[0]], options);
      if (result.failed.length > 0) {
        failures.push(`${location.path}：${result.failed[0].error}`);
        continue;
      }
      updated.push(location);
    } catch (error: any) {
      failures.push(`${location.path}：${error?.message || String(error)}`);
    }
  }
  const backup = backedUp > 0 ? { backupDir } : {};

  if (failures.length > 0) {
    const targets = [...stale, ...locations.filter(location => location.status === 'error')]
      .map(location => location.targets[0]);
    return withNotice({
      action: 'failed',
      updated,
      ...backup,
      notice:
        `paper-search：Skill 自动更新没有完成（${failures.join('；')}）。` +
        `可运行 paper-search skills update --targets ${targets.join(',')} 手动更新。`
    });
  }

  writeState(statePath, { ...state, bundledHash });
  const version = options.version ? ` ${options.version}` : '';
  return withNotice({
    action: 'updated',
    updated,
    ...backup,
    notice:
      `paper-search：已把 AI 工具里的 paper-search Skill 更新到当前版本${version}（${updated.map(location => location.path).join('、')}）` +
      (backedUp > 0 ? `；替换下来的旧文件在 ${backupDir}` : '') +
      '。新开的 AI 会话会读到新版本。'
  });
}

function backUp(location: SkillLocation, directory: string): number {
  for (const relPath of location.staleFiles) {
    const to = join(directory, relPath);
    mkdirSync(dirname(to), { recursive: true });
    copyFileSync(join(location.path, relPath), to);
  }
  return location.staleFiles.length;
}

function readState(path: string): SkillSyncState {
  if (!existsSync(path)) return {};
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf8'));
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    // Only this module writes the file; an unreadable one is checked afresh and rewritten.
    return {};
  }
}

function writeState(path: string, state: SkillSyncState): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(state, null, 2)}\n`);
}

function realDirectory(path: string): string {
  try {
    return realpathSync(path);
  } catch {
    return path;
  }
}

function stamp(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-` +
    `${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}
