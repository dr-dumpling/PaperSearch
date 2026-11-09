/**
 * Semantic Scholar API集成模块
 * 支持免费API和付费API密钥
 */
import { Paper } from '../models/Paper.js';
import { PaperSource, SearchOptions, DownloadOptions, PlatformCapabilities } from './PaperSource.js';
interface SemanticSearchOptions extends SearchOptions {
    /** 发表年份范围 */
    year?: string;
    /** 研究领域过滤 */
    fieldsOfStudy?: string[];
}
interface SemanticSnippetSearchOptions {
    query: string;
    limit?: number;
    year?: string;
    fieldsOfStudy?: string[] | string;
    paperIds?: string[] | string;
    authors?: string[] | string;
    venue?: string[] | string;
    minCitationCount?: number;
    publicationDateOrYear?: string;
    fields?: string[] | string;
}
export interface SemanticSnippetResult {
    score: number | null;
    paper: {
        corpusId: string;
        title: string;
        authors: string[];
        openAccessInfo: Record<string, unknown>;
        url: string;
        doi: string | null;
        pmid: string | null;
        year: number | null;
        journal: string | null;
        /** found: DOI, year and journal looked up; not_found: Semantic Scholar has no record; lookup_failed: the lookup itself failed */
        metadataStatus: 'found' | 'not_found' | 'lookup_failed';
    };
    snippet: {
        text: string;
        snippetKind: string;
        section: string;
        snippetOffset: Record<string, unknown>;
        annotations: Record<string, unknown>;
    };
    text: string;
    /** One line to cite under the quoted sentence: first author et al., year, journal · section · DOI · licence */
    source: string;
}
export declare class SemanticScholarSearcher extends PaperSource {
    private readonly rateLimiter;
    private readonly cache;
    private readonly baseApiUrl;
    constructor(apiKey?: string);
    getCapabilities(): PlatformCapabilities;
    /**
     * 搜索Semantic Scholar论文
     */
    search(query: string, options?: SemanticSearchOptions): Promise<Paper[]>;
    /**
     * 获取论文详细信息
     */
    getPaperDetails(paperId: string): Promise<Paper | null>;
    searchSnippets(options: SemanticSnippetSearchOptions): Promise<SemanticSnippetResult[]>;
    /**
     * The snippet endpoint gives only the title, authors and licence. DOI, PMID, year and journal come
     * from one batch lookup of the matched papers; a failed lookup is marked on each result, not hidden.
     */
    private addSnippetPaperMetadata;
    /**
     * 下载PDF文件
     */
    downloadPdf(paperId: string, options?: DownloadOptions): Promise<string>;
    /**
     * 读取论文全文内容
     */
    readPaper(paperId: string, options?: DownloadOptions): Promise<string>;
    /**
     * 根据DOI获取论文信息
     */
    getPaperByDoi(doi: string): Promise<Paper | null>;
    /**
     * 解析搜索响应
     */
    private parseSearchResponse;
    /**
     * 解析单个Semantic Scholar论文
     */
    private parseSemanticPaper;
    private normalizePdfUrl;
    private parseSnippet;
    private listParam;
    /**
     * 获取速率限制器状态
     */
    getRateLimiterStatus(): {
        availableTokens: number;
        maxTokens: number;
        requestsPerSecond: number;
        pendingRequests: number;
    };
    /**
     * 验证API密钥（如果提供）
     */
    validateApiKey(): Promise<boolean>;
}
export {};
//# sourceMappingURL=SemanticScholarSearcher.d.ts.map