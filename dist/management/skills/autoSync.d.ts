import { type SkillTargetStatus } from '../../skills/SkillInstaller.js';
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
/** `${XDG_DATA_HOME:-~/.local/share}/paper-search-cli` */
export declare function paperSearchDataRoot(env?: NodeJS.ProcessEnv, home?: string): string;
/** The Skill's installed copies, one per directory; targets without it are left out. */
export declare function skillLocations(options?: {
    skillsRoot?: string;
    sourceRoot?: string;
}): SkillLocation[];
/**
 * Once per bundled Skill (the first run after an install or upgrade): bring every
 * copy the user installed up to it, backing up the files it replaces; never
 * installs where there is none, and keeps the user's own files. With no copy
 * anywhere it returns a one-time hint. A failed update is retried on the next run.
 */
export declare function autoSyncSkill(options?: SkillAutoSyncOptions): SkillAutoSyncResult;
//# sourceMappingURL=autoSync.d.ts.map