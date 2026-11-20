export declare const SKILL_NAME = "paper-search";
/**
 * Beside each installed copy: the files it was last given. A later version that no longer ships
 * one of them moves it away on update (to the backup folder), while files the user added, never
 * in the list, stay (user, 2026-11-18: old files were left behind after files were renamed).
 */
export declare const SKILL_MANIFEST = ".paper-search-files.json";
/** Files earlier versions shipped before the list above was kept; a copy holding them got them from PaperSearch. */
export declare const RETIRED_SKILL_FILES: string[];
/** Raised when the way copies are kept changes, so that each copy is checked once more though the Skill did not. */
export declare const SKILL_LAYOUT = 2;
/** `${XDG_DATA_HOME:-~/.local/share}/paper-search-cli` */
export declare function paperSearchDataRoot(env?: NodeJS.ProcessEnv, home?: string): string;
/** A backup folder's time stamp: 20261118-143000. */
export declare function backupStamp(date: Date): string;
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
    installed: Array<{
        target: string;
        label: string;
        path: string;
        files: number;
        retired: string[];
    }>;
    /** Where the files an earlier version left were moved, when there were any. */
    backupDir?: string;
    failed: Array<{
        target: string;
        label: string;
        path: string;
        error: string;
    }>;
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
export declare const SKILL_TARGETS: SkillTarget[];
/** The targets used when none are named (setup's default, `skills status/update/diff`): the Skill's
 * installed copies, one target per directory, so an update never adds a copy next to one installed
 * another way (`npx skills add -g` keeps it in ~/.agents/skills and links ~/.claude/skills to it).
 * With no copy anywhere: ~/.agents/skills when it exists, else codex, claude and cursor. */
export declare function defaultSkillTargetIds(root?: string): string[];
export declare function parseSkillTargets(raw: string, root?: string): string[];
export declare function describeSkillTargets(targetIds: string[], root?: string): Array<{
    target: string;
    label: string;
    path: string;
}>;
export declare function statusSkillTargets(targetIds: string[], options?: {
    skillsRoot?: string;
    sourceRoot?: string;
}): SkillStatusResult;
/** Digest of the bundled Skill's files, the `bundledHash` of a status. */
export declare function bundledSkillHash(sourceRoot?: string): string;
/**
 * Writes the bundled Skill into each target, moves the files an earlier version left there and
 * this one no longer has into ``backupDir/<target>/`` (by default a new ``skill-backups`` folder
 * in PaperSearch's data), and records the files it wrote; files the user added stay.
 */
export declare function installSkillTargets(targetIds: string[], options?: {
    skillsRoot?: string;
    sourceRoot?: string;
    backupDir?: string;
}): SkillInstallResult;
export declare function diffSkillTargets(targetIds: string[], options?: {
    skillsRoot?: string;
    sourceRoot?: string;
}): SkillDiffResult;
//# sourceMappingURL=SkillInstaller.d.ts.map