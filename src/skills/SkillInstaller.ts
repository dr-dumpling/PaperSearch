import { createHash } from 'crypto';
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, renameSync, statSync, unlinkSync, writeFileSync } from 'fs';
import { homedir } from 'os';
import { dirname, join, relative, resolve, sep } from 'path';

export const SKILL_NAME = 'paper-search';

/**
 * Beside each installed copy: the files it was last given. A later version that no longer ships
 * one of them moves it away on update (to the backup folder), while files the user added, never
 * in the list, stay (user, 2026-11-18: old files were left behind after files were renamed).
 */
export const SKILL_MANIFEST = '.paper-search-files.json';

/** Files earlier versions shipped before the list above was kept; a copy holding them got them from PaperSearch. */
export const RETIRED_SKILL_FILES = ['references/institutional-setup.md', 'references/carsi-setup.md'];

/** Raised when the way copies are kept changes, so that each copy is checked once more though the Skill did not. */
export const SKILL_LAYOUT = 2;

/** `${XDG_DATA_HOME:-~/.local/share}/paper-search-cli` */
export function paperSearchDataRoot(env: NodeJS.ProcessEnv = process.env, home = homedir()): string {
  const base = env.XDG_DATA_HOME ? resolve(env.XDG_DATA_HOME) : join(home, '.local', 'share');
  return join(base, 'paper-search-cli');
}

/** A backup folder's time stamp: 20261118-143000. */
export function backupStamp(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-` +
    `${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

export interface SkillTarget {
  id: string;
  label: string;
  relativeRoot: string;
}

export interface SkillTargetStatus {
  target: string;
  label: string;
  path: string;
  status: 'missing' | 'up_to_date' | 'stale' | 'extra_files' | 'error';
  files: number;
  installedFiles: number;
  bundledHash: string;
  installedHash: string;
  hashMatch: boolean;
  managedHashMatch: boolean;
  extraFiles: string[];
  missingFiles: string[];
  staleFiles: string[];
  /** Files an earlier version gave this copy and this one no longer has: moved to the backup on update. */
  retiredFiles: string[];
  error?: string;
}

export interface SkillStatusResult {
  ok: boolean;
  root: string;
  skill: string;
  selected: string[];
  bundledFiles: number;
  bundledHash: string;
  targets: SkillTargetStatus[];
  statusCounts: Record<string, number>;
}

export interface SkillInstallResult {
  ok: boolean;
  root: string;
  skill: string;
  selected: string[];
  installed: Array<{ target: string; label: string; path: string; files: number; retired: string[] }>;
  /** Where the files an earlier version left were moved, when there were any. */
  backupDir?: string;
  failed: Array<{ target: string; label: string; path: string; error: string }>;
  installedCount: number;
  failedCount: number;
  status: SkillStatusResult;
}

export interface SkillManagedFileDiff {
  file: string;
  status: 'missing' | 'stale' | 'up_to_date';
  bundledHash: string;
  installedHash: string;
  diff?: string;
}

export interface SkillTargetDiff {
  target: string;
  label: string;
  path: string;
  status: SkillTargetStatus['status'];
  files: number;
  installedFiles: number;
  bundledHash: string;
  installedHash: string;
  hashMatch: boolean;
  managedHashMatch: boolean;
  managedFiles: SkillManagedFileDiff[];
  extraFiles: string[];
  missingFiles: string[];
  staleFiles: string[];
  retiredFiles: string[];
  error?: string;
}

export interface SkillDiffResult {
  ok: boolean;
  root: string;
  skill: string;
  selected: string[];
  bundledFiles: number;
  bundledHash: string;
  targets: SkillTargetDiff[];
  statusCounts: Record<string, number>;
}

type SkillFile = [relPath: string, content: Buffer];

export const SKILL_TARGETS: SkillTarget[] = [
  { id: 'agents', label: 'Agents shared skills', relativeRoot: '.agents/skills' },
  { id: 'codex', label: 'Codex', relativeRoot: '.codex/skills' },
  { id: 'claude', label: 'Claude Code', relativeRoot: '.claude/skills' },
  { id: 'cursor', label: 'Cursor', relativeRoot: '.cursor/skills' },
  { id: 'gemini', label: 'Gemini CLI', relativeRoot: '.gemini/skills' },
  { id: 'antigravity', label: 'Antigravity', relativeRoot: '.gemini/antigravity/skills' }
];

const TARGET_BY_ID = new Map(SKILL_TARGETS.map(target => [target.id, target]));
const TARGET_ALIASES = new Map<string, string>([
  ['agent', 'agents'],
  ['shared', 'agents'],
  ['agent-skills', 'agents'],
  ['claude-code', 'claude']
]);

/** The targets used when none are named (setup's default, `skills status/update/diff`): the Skill's
 * installed copies, one target per directory, so an update never adds a copy next to one installed
 * another way (`npx skills add -g` keeps it in ~/.agents/skills and links ~/.claude/skills to it).
 * With no copy anywhere: ~/.agents/skills when it exists, else codex, claude and cursor. */
export function defaultSkillTargetIds(root = homedir()): string[] {
  const base = resolve(root);
  const directories = new Set<string>();
  const installed: string[] = [];
  for (const target of SKILL_TARGETS) {
    const dest = skillDestination(target, base);
    if (!existsSync(dest)) continue;
    const directory = realpathSync(dest);
    if (directories.has(directory)) continue;
    directories.add(directory);
    installed.push(target.id);
  }
  if (installed.length > 0) return installed;
  return existsSync(join(base, '.agents', 'skills')) ? ['agents'] : ['codex', 'claude', 'cursor'];
}

export function parseSkillTargets(raw: string, root = homedir()): string[] {
  const text = raw.trim();
  if (!text) return defaultSkillTargetIds(root);

  const tokens = text
    .replace(/[;+]/g, ',')
    .split(',')
    .flatMap(part => part.trim().split(/\s+/))
    .map(part => part.trim().toLowerCase())
    .filter(Boolean);

  const selected: string[] = [];
  const invalid: string[] = [];
  for (const token of tokens) {
    if (['skip', 'none', 'no', 'n', '跳过', '无', '否'].includes(token)) return [];
    if (['all', '全部'].includes(token)) return SKILL_TARGETS.map(target => target.id);

    const targetId = TARGET_ALIASES.get(token) || token;
    if (!TARGET_BY_ID.has(targetId)) {
      invalid.push(token);
      continue;
    }
    if (!selected.includes(targetId)) selected.push(targetId);
  }

  if (invalid.length > 0) {
    throw new Error(`Unknown skill target(s): ${invalid.join(', ')}. Valid targets: ${SKILL_TARGETS.map(target => target.id).join(', ')}`);
  }
  return selected;
}

export function describeSkillTargets(targetIds: string[], root = homedir()): Array<{ target: string; label: string; path: string }> {
  const base = resolve(root);
  return targetIds.map(targetId => {
    const target = getSkillTarget(targetId);
    return {
      target: target.id,
      label: target.label,
      path: skillDestination(target, base)
    };
  });
}

export function statusSkillTargets(targetIds: string[], options: { skillsRoot?: string; sourceRoot?: string } = {}): SkillStatusResult {
  const root = resolve(options.skillsRoot || homedir());
  const files = loadSkillFiles(options.sourceRoot);
  const sourceByPath = new Map(files.map(([relPath, content]) => [relPath, content]));
  const bundledHash = skillDigest(files);
  const targets: SkillTargetStatus[] = [];

  for (const targetId of targetIds) {
    const target = getSkillTarget(targetId);
    const dest = skillDestination(target, root);
    const item: SkillTargetStatus = {
      target: target.id,
      label: target.label,
      path: dest,
      status: 'missing',
      files: files.length,
      installedFiles: 0,
      bundledHash,
      installedHash: '',
      hashMatch: false,
      managedHashMatch: false,
      extraFiles: [],
      missingFiles: [...sourceByPath.keys()].sort(),
      staleFiles: [],
      retiredFiles: []
    };

    try {
      if (!existsSync(dest)) {
        targets.push(item);
        continue;
      }
      if (!statSync(dest).isDirectory()) {
        item.status = 'error';
        item.error = 'Installed skill path exists but is not a directory.';
        targets.push(item);
        continue;
      }

      const installedFiles = iterFilesystemFiles(dest);
      const installedByPath = new Map(installedFiles.map(([relPath, content]) => [relPath, content]));
      const missingFiles = [...sourceByPath.keys()].filter(relPath => !installedByPath.has(relPath)).sort();
      const staleFiles = [...sourceByPath.entries()]
        .filter(([relPath, content]) => installedByPath.has(relPath) && !installedByPath.get(relPath)?.equals(content))
        .map(([relPath]) => relPath)
        .sort();
      const retiredFiles = retiredSkillFiles(dest, installedByPath.keys(), sourceByPath);
      const extraFiles = [...installedByPath.keys()].filter(relPath => !sourceByPath.has(relPath) && !retiredFiles.includes(relPath)).sort();
      const managedHashMatch = missingFiles.length === 0 && staleFiles.length === 0 && retiredFiles.length === 0;
      const hashMatch = managedHashMatch && extraFiles.length === 0;

      item.installedFiles = installedFiles.length;
      item.installedHash = installedFiles.length > 0 ? skillDigest(installedFiles) : '';
      item.retiredFiles = retiredFiles;
      item.missingFiles = missingFiles;
      item.staleFiles = staleFiles;
      item.extraFiles = extraFiles;
      item.managedHashMatch = managedHashMatch;
      item.hashMatch = hashMatch;
      item.status = missingFiles.length || staleFiles.length || retiredFiles.length ? 'stale' : extraFiles.length ? 'extra_files' : 'up_to_date';
    } catch (error: any) {
      item.status = 'error';
      item.error = error?.message || String(error);
    }
    targets.push(item);
  }

  const statusCounts: Record<string, number> = {};
  for (const target of targets) {
    statusCounts[target.status] = (statusCounts[target.status] || 0) + 1;
  }

  return {
    ok: targets.every(target => target.status !== 'error'),
    root,
    skill: SKILL_NAME,
    selected: targetIds,
    bundledFiles: files.length,
    bundledHash,
    targets,
    statusCounts
  };
}

/** Digest of the bundled Skill's files, the `bundledHash` of a status. */
export function bundledSkillHash(sourceRoot?: string): string {
  return skillDigest(loadSkillFiles(sourceRoot));
}

/**
 * Writes the bundled Skill into each target, moves the files an earlier version left there and
 * this one no longer has into ``backupDir/<target>/`` (by default a new ``skill-backups`` folder
 * in PaperSearch's data), and records the files it wrote; files the user added stay.
 */
export function installSkillTargets(
  targetIds: string[],
  options: { skillsRoot?: string; sourceRoot?: string; backupDir?: string } = {}
): SkillInstallResult {
  const root = resolve(options.skillsRoot || homedir());
  const files = loadSkillFiles(options.sourceRoot);
  const bundled = new Map(files.map(([relPath, content]) => [relPath, content]));
  const backupDir = options.backupDir ?? join(paperSearchDataRoot(), 'skill-backups', `${backupStamp(new Date())}-update`);
  const installed: SkillInstallResult['installed'] = [];
  const failed: SkillInstallResult['failed'] = [];
  let moved = 0;

  for (const targetId of targetIds) {
    const target = getSkillTarget(targetId);
    const dest = skillDestination(target, root);
    try {
      const before = existsSync(dest) && statSync(dest).isDirectory() ? iterFilesystemFiles(dest).map(([relPath]) => relPath) : [];
      const retired = retiredSkillFiles(dest, before, bundled);
      for (const [relPath, content] of files) {
        const filePath = join(dest, relPath);
        mkdirSync(dirname(filePath), { recursive: true });
        writeFileSync(filePath, content);
      }
      for (const relPath of retired) moveAside(join(dest, relPath), join(backupDir, target.id, relPath));
      moved += retired.length;
      writeFileSync(join(dest, SKILL_MANIFEST), `${JSON.stringify({ skill: SKILL_NAME, files: [...bundled.keys()].sort() }, null, 2)}\n`);
      installed.push({ target: target.id, label: target.label, path: dest, files: files.length, retired });
    } catch (error: any) {
      failed.push({ target: target.id, label: target.label, path: dest, error: error?.message || String(error) });
    }
  }

  const status = statusSkillTargets(targetIds, options);
  return {
    ok: failed.length === 0 && status.ok,
    root,
    skill: SKILL_NAME,
    selected: targetIds,
    ...(moved > 0 ? { backupDir } : {}),
    installed,
    failed,
    installedCount: installed.length,
    failedCount: failed.length,
    status
  };
}

export function diffSkillTargets(targetIds: string[], options: { skillsRoot?: string; sourceRoot?: string } = {}): SkillDiffResult {
  const root = resolve(options.skillsRoot || homedir());
  const files = loadSkillFiles(options.sourceRoot);
  const sourceByPath = new Map(files.map(([relPath, content]) => [relPath, content]));
  const bundledHash = skillDigest(files);
  const targets: SkillTargetDiff[] = [];

  for (const targetId of targetIds) {
    const target = getSkillTarget(targetId);
    const dest = skillDestination(target, root);
    const item: SkillTargetDiff = {
      target: target.id,
      label: target.label,
      path: dest,
      status: 'missing',
      files: files.length,
      installedFiles: 0,
      bundledHash,
      installedHash: '',
      hashMatch: false,
      managedHashMatch: false,
      managedFiles: [...sourceByPath.entries()].map(([relPath, content]) => ({
        file: relPath,
        status: 'missing',
        bundledHash: bufferDigest(content),
        installedHash: ''
      })),
      extraFiles: [],
      missingFiles: [...sourceByPath.keys()].sort(),
      staleFiles: [],
      retiredFiles: []
    };

    try {
      if (!existsSync(dest)) {
        targets.push(item);
        continue;
      }
      if (!statSync(dest).isDirectory()) {
        item.status = 'error';
        item.error = 'Installed skill path exists but is not a directory.';
        targets.push(item);
        continue;
      }

      const installedFiles = iterFilesystemFiles(dest);
      const installedByPath = new Map(installedFiles.map(([relPath, content]) => [relPath, content]));
      const managedFiles: SkillManagedFileDiff[] = [...sourceByPath.entries()].map(([relPath, bundled]) => {
        const installed = installedByPath.get(relPath);
        if (!installed) {
          return {
            file: relPath,
            status: 'missing',
            bundledHash: bufferDigest(bundled),
            installedHash: ''
          };
        }
        if (!installed.equals(bundled)) {
          return {
            file: relPath,
            status: 'stale',
            bundledHash: bufferDigest(bundled),
            installedHash: bufferDigest(installed),
            diff: unifiedManagedDiff(relPath, installed, bundled)
          };
        }
        return {
          file: relPath,
          status: 'up_to_date',
          bundledHash: bufferDigest(bundled),
          installedHash: bufferDigest(installed)
        };
      });
      const missingFiles = managedFiles.filter(file => file.status === 'missing').map(file => file.file).sort();
      const staleFiles = managedFiles.filter(file => file.status === 'stale').map(file => file.file).sort();
      const retiredFiles = retiredSkillFiles(dest, installedByPath.keys(), sourceByPath);
      const extraFiles = [...installedByPath.keys()].filter(relPath => !sourceByPath.has(relPath) && !retiredFiles.includes(relPath)).sort();
      const managedHashMatch = missingFiles.length === 0 && staleFiles.length === 0 && retiredFiles.length === 0;
      const hashMatch = managedHashMatch && extraFiles.length === 0;

      item.installedFiles = installedFiles.length;
      item.installedHash = installedFiles.length > 0 ? skillDigest(installedFiles) : '';
      item.retiredFiles = retiredFiles;
      item.managedFiles = managedFiles.sort((a, b) => a.file.localeCompare(b.file));
      item.missingFiles = missingFiles;
      item.staleFiles = staleFiles;
      item.extraFiles = extraFiles;
      item.managedHashMatch = managedHashMatch;
      item.hashMatch = hashMatch;
      item.status = missingFiles.length || staleFiles.length || retiredFiles.length ? 'stale' : extraFiles.length ? 'extra_files' : 'up_to_date';
    } catch (error: any) {
      item.status = 'error';
      item.error = error?.message || String(error);
    }
    targets.push(item);
  }

  const statusCounts: Record<string, number> = {};
  for (const target of targets) {
    statusCounts[target.status] = (statusCounts[target.status] || 0) + 1;
  }

  return {
    ok: targets.every(target => target.status !== 'error'),
    root,
    skill: SKILL_NAME,
    selected: targetIds,
    bundledFiles: files.length,
    bundledHash,
    targets,
    statusCounts
  };
}

function getSkillTarget(targetId: string): SkillTarget {
  const target = TARGET_BY_ID.get(targetId);
  if (!target) {
    throw new Error(`Unknown skill target: ${targetId}. Valid targets: ${SKILL_TARGETS.map(item => item.id).join(', ')}`);
  }
  return target;
}

function skillDestination(target: SkillTarget, root: string): string {
  return join(root, target.relativeRoot, SKILL_NAME);
}

function loadSkillFiles(sourceRoot?: string): SkillFile[] {
  const root = sourceRoot ? resolve(sourceRoot) : bundledSkillRoot();
  if (!existsSync(root) || !statSync(root).isDirectory()) {
    throw new Error(`Skill source directory not found: ${root}`);
  }
  const files = iterFilesystemFiles(root);
  if (files.length === 0) {
    throw new Error(`Skill source directory is empty: ${root}`);
  }
  return files;
}

function bundledSkillRoot(): string {
  const explicit = process.env.PAPER_SEARCH_SKILL_SOURCE_ROOT;
  const candidates = [
    explicit ? resolve(explicit) : '',
    resolve(process.cwd(), 'skills', SKILL_NAME),
    ...entrypointSkillCandidates()
  ].filter(Boolean);

  const found = candidates.find(candidate => existsSync(candidate) && statSync(candidate).isDirectory());
  if (!found) return candidates[0] || resolve(process.cwd(), 'skills', SKILL_NAME);
  return found;
}

function entrypointSkillCandidates(): string[] {
  const entry = process.argv[1];
  if (!entry) return [];
  const entryPath = existsSync(entry) ? realpathSync(entry) : resolve(entry);
  const entryDir = dirname(entryPath);
  return [
    resolve(entryDir, '..', 'skills', SKILL_NAME),
    resolve(entryDir, 'skills', SKILL_NAME)
  ];
}

/** Files this copy got from an earlier version (its list, or the known older files) that this version no longer has. */
function retiredSkillFiles(dest: string, installed: Iterable<string>, bundled: Map<string, unknown>): string[] {
  let listed: string[] = [];
  try {
    const parsed = JSON.parse(readFileSync(join(dest, SKILL_MANIFEST), 'utf8'));
    if (Array.isArray(parsed?.files)) listed = parsed.files.filter((file: unknown): file is string => typeof file === 'string');
  } catch {
    // No list yet (a copy from before 2026-11-18), or one that cannot be read: the known older files only.
  }
  const earlier = new Set([...listed, ...RETIRED_SKILL_FILES]);
  return [...installed].filter(relPath => earlier.has(relPath) && !bundled.has(relPath)).sort();
}

function moveAside(from: string, to: string): void {
  mkdirSync(dirname(to), { recursive: true });
  try {
    renameSync(from, to);
  } catch (error: any) {
    if (error?.code !== 'EXDEV') throw error;
    copyFileSync(from, to);
    unlinkSync(from);
  }
}

function iterFilesystemFiles(root: string): SkillFile[] {
  const files: SkillFile[] = [];

  function visit(dir: string) {
    for (const name of readdirSync(dir)) {
      if (dir === root && name === SKILL_MANIFEST) continue;
      const path = join(dir, name);
      const stats = statSync(path);
      if (stats.isDirectory()) {
        visit(path);
      } else if (stats.isFile()) {
        files.push([relative(root, path).split(sep).join('/'), readFileSync(path)]);
      }
    }
  }

  visit(root);
  return files.sort(([a], [b]) => a.localeCompare(b));
}

function skillDigest(files: SkillFile[]): string {
  const hash = createHash('sha256');
  for (const [relPath, content] of [...files].sort(([a], [b]) => a.localeCompare(b))) {
    hash.update(relPath);
    hash.update('\0');
    hash.update(content);
    hash.update('\0');
  }
  return hash.digest('hex');
}

function bufferDigest(content: Buffer): string {
  return createHash('sha256').update(content).digest('hex');
}

function unifiedManagedDiff(relPath: string, installed: Buffer, bundled: Buffer): string {
  if (hasBinaryByte(installed) || hasBinaryByte(bundled)) {
    return [
      `--- installed/${relPath}`,
      `+++ bundled/${relPath}`,
      '@@',
      '-[binary content differs]',
      '+[binary content differs]'
    ].join('\n');
  }

  const installedLines = splitLines(installed.toString('utf8'));
  const bundledLines = splitLines(bundled.toString('utf8'));
  const lines = [
    `--- installed/${relPath}`,
    `+++ bundled/${relPath}`,
    '@@'
  ];

  for (const line of installedLines) {
    lines.push(`-${line}`);
  }
  for (const line of bundledLines) {
    lines.push(`+${line}`);
  }
  return lines.join('\n');
}

function hasBinaryByte(content: Buffer): boolean {
  return content.includes(0);
}

function splitLines(text: string): string[] {
  if (!text) return [''];
  const lines = text.split(/\r?\n/);
  if (lines[lines.length - 1] === '') lines.pop();
  return lines;
}
