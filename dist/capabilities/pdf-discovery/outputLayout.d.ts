import type { Searchers } from '../../core/searchers.js';
import type { Paper } from '../../models/Paper.js';
export type OutputMetadata = Partial<Pick<Paper, 'title' | 'journal' | 'year' | 'publishedDate'>>;
/**
 * Where one paper's files go (user, 2026-11-11): main texts lie side by side in the download
 * folder; a paper with supplementary files saved has a folder of its own there, its main text
 * in it. A paper is downloaded in its own folder either way (``paperDir``), the backend writing
 * its packet into ``workDiagnosticsDir``; the diagnostics then go to the run's folder in
 * PaperSearch's own data, kept 30 days, never beside the papers (``diagnosticsDir``). With a
 * run's folder the packet is written there from the start: no diagnostics folder shows in the
 * download folder while a paper downloads either (user, 2026-11-11).
 */
export interface OutputLayout {
    /** The paper's own folder: where it is downloaded, and with supplementary files saved where it stays. */
    paperDir: string;
    /** Where its main text ends up without supplementary files: the download folder (flat) or ``paperDir``. */
    fileDir: string;
    /** Where the backend writes its diagnostic packet while downloading: beside the run's diagnostics, inside ``paperDir`` only without them. */
    workDiagnosticsDir: string;
    /** Where the diagnostics end up. */
    diagnosticsDir: string;
    name: string;
    metadata: OutputMetadata & {
        identity: string;
    };
}
export interface OutputPlacement {
    /** The main text lies in the download folder unless supplementary files were saved with it. */
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
/** The journal, year and title a download is named with; ``{}`` when no source answers in time. */
export declare function lookupOutputMetadata(searchers: Searchers, source: string, id: string): Promise<OutputMetadata>;
export declare function createOutputLayout(root: string, identity: string, metadata: OutputMetadata, preprint?: boolean, placement?: OutputPlacement): OutputLayout;
/** The layout with another folder for the paper (an existing download's, its supplementary files beside its main text). */
export declare function inPaperDir(layout: OutputLayout, paperDir: string): OutputLayout;
/** The paper's working folder is not left behind once nothing is in it (its main text lies in the download folder). */
export declare function removeWorkFolder(layout: OutputLayout): void;
/** A saved supplementary file came with this result: the paper keeps a folder of its own. */
export declare function savedSupplements(result: {
    supplements?: import('./types.js').SupplementFile[];
}): boolean;
/**
 * Move a main text that lies in the download folder into the paper's own folder, once
 * supplementary files were saved for it later (an open-access main text, its files
 * fetched from the article page after it). The moved file's path; the same one when
 * it is already in a folder of its own.
 */
export declare function moveIntoPaperDir(mainPath: string, layout: OutputLayout): string;
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