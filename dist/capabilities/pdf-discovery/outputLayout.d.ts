import type { Searchers } from '../../core/searchers.js';
import type { Paper } from '../../models/Paper.js';
export type OutputMetadata = Partial<Pick<Paper, 'title' | 'journal' | 'year' | 'publishedDate'>>;
/**
 * Where one paper's files go (user, 2026-11-11): main texts only lie side by side in the
 * download folder; with supplementary files each paper has a folder of its own there. A paper
 * is downloaded in its own folder either way (``paperDir``), the backend writing its packet into
 * ``workDiagnosticsDir``; the diagnostics then go to the run's folder in PaperSearch's own data,
 * kept 30 days, never beside the papers (``diagnosticsDir``).
 */
export interface OutputLayout {
    /** The paper's own folder: where it is downloaded, and with supplementary files where it stays. */
    paperDir: string;
    /** Where its main text ends up: the download folder itself (main texts only) or ``paperDir``. */
    fileDir: string;
    /** Where the backend writes its diagnostic packet while downloading, inside ``paperDir``. */
    workDiagnosticsDir: string;
    /** Where the diagnostics end up. */
    diagnosticsDir: string;
    name: string;
    metadata: OutputMetadata & {
        identity: string;
    };
}
export interface OutputPlacement {
    /** Main texts only: the main text lies in the download folder, not in a folder of its own. */
    flat?: boolean;
    /** The run's diagnostics folder (RunLedger.diagnostics); else the download folder's diagnostics/. */
    diagnosticsDir?: string;
}
/**
 * Diagnostics keep full addresses and may carry login tokens (unmasked by the
 * user's choice, 2026-10-29); the guide and the Skill say not to pass them on.
 */
export declare const DIAGNOSTICS_FOLDER = "diagnostics";
export declare function safeComponent(value: string, limit: number): string;
export declare function lookupOutputMetadata(searchers: Searchers, source: string, id: string): Promise<OutputMetadata>;
export declare function createOutputLayout(root: string, identity: string, metadata: OutputMetadata, preprint?: boolean, placement?: OutputPlacement): OutputLayout;
/** The layout with another folder for the paper (an existing download's, its supplementary files beside its main text). */
export declare function inPaperDir(layout: OutputLayout, paperDir: string): OutputLayout;
/** Main texts only: the paper's working folder, emptied into the download folder, is not left behind. */
export declare function removeWorkFolder(layout: OutputLayout): void;
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
 * The main text goes to ``fileDir``, the supplementary files to the paper's
 * folder; what there is to look at goes to the diagnostics folder under the
 * paper's own name: the backend's record or diagnostic packet with its
 * screenshots, a PDF left for review, the supplementary files' manifest. A
 * paper that went fine (saved, every supplementary file too) keeps them in
 * ``recordsDir`` instead (user, 2026-11-10).
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