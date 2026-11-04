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
export declare function safeComponent(value: string, limit: number): string;
export declare function lookupOutputMetadata(searchers: Searchers, source: string, id: string): Promise<OutputMetadata>;
export declare function createOutputLayout(root: string, identity: string, metadata: OutputMetadata, preprint?: boolean): OutputLayout;
/** Never overwrite an existing download, including a different revision of the same paper. */
export declare function placeFile(source: string, target: string, ownedDir: string): string;
/** Rewrite only known local record paths, never arbitrary page strings or URLs. */
export declare function updateRecordPaths(paths: unknown[], replacements: Map<string, string>): void;
/** Finalize only files reported by this request, preserving unrelated files. */
export declare function organizeFiles<T extends {
    path?: string;
    format?: string;
    review?: {
        path: string;
    };
    supplements?: import('./types.js').SupplementFile[];
    trace?: Record<string, unknown>;
}>(result: T, layout: OutputLayout, ownedDir: string): T;
//# sourceMappingURL=outputLayout.d.ts.map