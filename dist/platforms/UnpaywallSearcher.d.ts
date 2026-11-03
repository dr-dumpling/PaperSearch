import { Paper } from '../models/Paper.js';
import { PaperSource, SearchOptions, DownloadOptions, PlatformCapabilities } from './PaperSource.js';
export interface UnpaywallPdfCandidate {
    url: string;
    hostType: string;
    version: string;
}
export declare class UnpaywallSearcher extends PaperSource {
    private readonly client;
    private readonly email;
    constructor(email?: string);
    getCapabilities(): PlatformCapabilities;
    hasApiKey(): boolean;
    search(query: string, _options?: SearchOptions): Promise<Paper[]>;
    getPaperByDoi(doi: string): Promise<Paper | null>;
    /**
     * Every OA location's PDF URL, published version first, then accepted and
     * submitted; within a version, repositories before the publisher. Unpaywall's
     * own best location prefers publisher copies, which often refuse plain HTTP.
     */
    resolvePdfCandidates(doi: string): Promise<UnpaywallPdfCandidate[]>;
    private fetchRecord;
    downloadPdf(_paperId: string, _options?: DownloadOptions): Promise<string>;
    readPaper(_paperId: string, _options?: DownloadOptions): Promise<string>;
    private parseRecord;
    private firstLocationUrl;
    private extractDoi;
}
//# sourceMappingURL=UnpaywallSearcher.d.ts.map