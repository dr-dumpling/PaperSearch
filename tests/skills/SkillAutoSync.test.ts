import { spawnSync } from 'child_process';
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync
} from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { afterEach, beforeEach, describe, expect, it } from '@jest/globals';
import { autoSyncSkill, skillLocations } from '../../src/management/skills/index.js';

describe('Skill auto-sync after an upgrade', () => {
  let temp: string;
  let source: string;
  let home: string;
  let data: string;

  const installed = (...parts: string[]) => join(home, '.agents', 'skills', 'paper-search', ...parts);
  const sync = () => autoSyncSkill({ skillsRoot: home, sourceRoot: source, dataRoot: data, version: '9.9.9' });

  beforeEach(() => {
    temp = mkdtempSync(join(tmpdir(), 'paper-search-skill-sync-'));
    source = join(temp, 'bundled');
    home = join(temp, 'home');
    data = join(temp, 'data');
    mkdirSync(join(source, 'references'), { recursive: true });
    writeFileSync(join(source, 'SKILL.md'), 'new skill\n');
    writeFileSync(join(source, 'references', 'a.md'), 'new reference\n');
    mkdirSync(home, { recursive: true });
  });

  afterEach(() => {
    rmSync(temp, { recursive: true, force: true });
  });

  it('hints once when no AI tool has the Skill, and installs nothing', () => {
    const first = sync();
    expect(first.action).toBe('not_installed');
    expect(first.notice).toContain('还没有给 AI 工具安装');
    expect(existsSync(installed())).toBe(false);

    expect(sync()).toEqual({ action: 'unchanged' });
    writeFileSync(join(source, 'SKILL.md'), 'newer skill\n');
    expect(sync()).toEqual({ action: 'not_installed' });
  });

  it('updates the copies the user installed once, keeps their own files and backs up the replaced ones', () => {
    mkdirSync(installed(), { recursive: true });
    writeFileSync(installed('SKILL.md'), 'old skill\n');
    writeFileSync(installed('NOTES.md'), 'my notes\n');
    mkdirSync(join(home, '.claude'), { recursive: true });
    symlinkSync(join(home, '.agents', 'skills'), join(home, '.claude', 'skills'));

    const result = sync();
    expect(result.action).toBe('updated');
    expect(result.updated?.map(location => location.targets)).toEqual([['agents', 'claude']]);
    expect(result.notice).toContain('已把 AI 工具里的 paper-search Skill 更新到当前版本 9.9.9');
    expect(readFileSync(installed('SKILL.md'), 'utf8')).toBe('new skill\n');
    expect(readFileSync(installed('references', 'a.md'), 'utf8')).toBe('new reference\n');
    expect(readFileSync(installed('NOTES.md'), 'utf8')).toBe('my notes\n');
    expect(readFileSync(join(String(result.backupDir), 'agents', 'SKILL.md'), 'utf8')).toBe('old skill\n');
    expect(existsSync(join(home, '.codex', 'skills', 'paper-search'))).toBe(false);

    expect(sync()).toEqual({ action: 'unchanged' });
  });

  it('only records the version when the copies are already current', () => {
    mkdirSync(join(installed(), 'references'), { recursive: true });
    writeFileSync(installed('SKILL.md'), 'new skill\n');
    writeFileSync(installed('references', 'a.md'), 'new reference\n');

    expect(sync()).toEqual({ action: 'up_to_date' });
    expect(existsSync(join(data, 'skill-backups'))).toBe(false);
    expect(sync()).toEqual({ action: 'unchanged' });
  });

  it('reports a copy it cannot update and tries again next time', () => {
    mkdirSync(join(home, '.agents', 'skills'), { recursive: true });
    writeFileSync(installed(), 'not a directory\n');

    const result = sync();
    expect(result.action).toBe('failed');
    expect(result.notice).toContain('Skill 自动更新没有完成');
    expect(result.notice).toContain('paper-search skills update --targets agents');
    expect(sync().action).toBe('failed');
  });

  it('lists each installed directory once for doctor', () => {
    mkdirSync(installed(), { recursive: true });
    writeFileSync(installed('SKILL.md'), 'old skill\n');
    mkdirSync(join(home, '.codex'), { recursive: true });
    symlinkSync(join(home, '.agents', 'skills'), join(home, '.codex', 'skills'));

    const locations = skillLocations({ skillsRoot: home, sourceRoot: source });
    expect(locations).toHaveLength(1);
    expect(locations[0].targets).toEqual(['agents', 'codex']);
    expect(locations[0].status).toBe('stale');
    expect(locations[0].missingFiles).toEqual(['references/a.md']);
  });
});

describe('the CLI syncs the installed Skill on its first run after an upgrade', () => {
  let temp: string;

  beforeEach(() => {
    temp = mkdtempSync(join(tmpdir(), 'paper-search-skill-sync-cli-'));
  });

  afterEach(() => {
    rmSync(temp, { recursive: true, force: true });
  });

  function runCli(args: string[], autoUpdate?: string) {
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      HOME: temp,
      XDG_DATA_HOME: join(temp, 'data'),
      PAPER_SEARCH_CONFIG_FILE: join(temp, 'config.json'),
      PAPER_SEARCH_HIDE_SETUP_HINT: '1'
    };
    delete env.PAPER_SEARCH_SKILL_AUTO_UPDATE;
    if (autoUpdate !== undefined) env.PAPER_SEARCH_SKILL_AUTO_UPDATE = autoUpdate;
    return spawnSync(process.execPath, [join(process.cwd(), 'node_modules/.bin/tsx'), 'src/cli.ts', ...args], {
      cwd: process.cwd(),
      env,
      encoding: 'utf8',
      timeout: 60_000
    });
  }

  function installOldSkill(): string {
    const dir = join(temp, '.agents', 'skills', 'paper-search');
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, 'SKILL.md'), 'an old Skill\n');
    return dir;
  }

  it('updates an old copy before the command runs and reports it on stderr', () => {
    const dir = installOldSkill();
    const result = runCli(['tools']);
    expect(result.status).toBe(0);
    expect(result.stderr).toContain('已把 AI 工具里的 paper-search Skill 更新到当前版本');
    expect(JSON.parse(result.stdout).ok).toBe(true);
    expect(readFileSync(join(dir, 'SKILL.md'), 'utf8')).toBe(
      readFileSync(join(process.cwd(), 'skills', 'paper-search', 'SKILL.md'), 'utf8')
    );
    expect(readdirSync(join(dir, 'references'))).toContain('publisher-support.md');

    const again = runCli(['tools']);
    expect(again.stderr).not.toContain('Skill');

    const doctor = JSON.parse(runCli(['doctor']).stdout);
    expect(doctor.skills.autoUpdate).toBe(true);
    expect(doctor.skills.locations).toEqual([
      expect.objectContaining({ targets: ['agents'], status: 'up_to_date' })
    ]);
  });

  it('leaves the copy alone when the user turned auto-update off', () => {
    const dir = installOldSkill();
    const result = runCli(['tools'], 'false');
    expect(result.status).toBe(0);
    expect(result.stderr).not.toContain('Skill');
    expect(readFileSync(join(dir, 'SKILL.md'), 'utf8')).toBe('an old Skill\n');

    const doctor = runCli(['doctor', '--format', 'text'], 'false');
    expect(doctor.stdout).toContain('自动更新：已关闭');
    expect(doctor.stdout).toContain('不是最新');
  });
});
