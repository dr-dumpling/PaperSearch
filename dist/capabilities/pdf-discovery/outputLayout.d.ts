import type { Searchers } from '../../core/searchers.js';
import type { Paper } from '../../models/Paper.js';
export type OutputMetadata = Partial<Pick<Paper, 'title' | 'journal' | 'year' | 'publishedDate'>>;
export interface OutputLayout {
    paperDir: string;
    diagnosticsDir: string;
    name: string;
    metadata: OutputMetadata & {
        identity: string;
    };
}
/**
 * Each paper's own diagnostics, inside its folder. They keep full addresses and
 * may carry login tokens (unmasked by the user's choice, 2026-10-29); the guide
 * and the Skill say not to pass them on. A plain name (user, 2026-11-10).
 */
export declare const DIAGNOSTICS_FOLDER = "diagnostics";
export declare function safeComponent(value: string, limit: number): string;
export declare function lookupOutputMetadata(searchers: Searchers, source: string, id: string): Promise<OutputMetadata>;
export declare function createOutputLayout(root: string, identity: string, metadata: OutputMetadata, preprint?: boolean): OutputLayout;
/** The layout with another folder for the paper (an existing download's), its diagnostics inside it. */
export declare function inPaperDir(layout: OutputLayout, paperDir: string): OutputLayout;
/**
 * A path with its links followed where it exists: the backend reports real paths
 * (macOS: /private/tmp), the caller may have named the same folder through a link (/tmp).
 */
export declare function realPath(path: string): string;
/** ``path`` lies under ``dir`` (not ``dir`` itself), links followed. */
export declare function isInside(path: string, dir: string): boolean;
/** Never overwrite an existing download, including a different revision of the same paper. */
export declare function placeFile(source: string, target: string, ownedDir: string): string;
/** Rewrite only known local record paths, never arbitrary page strings or URLs. */
export declare function updateRecordPaths(paths: unknown[], replacements: Map<string, string>): void;
/**
 * Finalize only files reported by this request, preserving unrelated files.
 * The paper's folder gets its PDF, its supplementary files, and, when there is
 * something to look at, a diagnostics folder whose files carry the paper's own
 * name: the backend's record or diagnostic packet with its screenshots, a PDF
 * left for review, the supplementary files' manifest. A paper that went fine
 * (saved, every supplementary file too) keeps them in ``recordsDir`` instead, its
 * run's folder: a diagnostics folder beside a good PDF read as a failure (user,
 * 2026-11-10).
 */
export declare function organizeFiles<T extends {
    status?: string;
    path?: string;
    format?: string;
    review?: {
        path: string;
    };
    supplements?: import('./types.js').SupplementFile[];
    trace?: Record<string, unknown>;
}>(result: T, paperLayout: OutputLayout, ownedDir: string, now?: Date, recordsDir?: string): T;
//# sourceMappingURL=outputLayout.d.ts.map