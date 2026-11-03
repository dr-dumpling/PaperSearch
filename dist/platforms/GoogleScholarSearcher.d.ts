/**
 * Google Scholar搜索器 - 网页抓取实现
 * 基于HTML解析，包含低频请求与挑战页识别
 */
import { Paper } from '../models/Paper.js';
import { PaperSource, SearchOptions, DownloadOptions, PlatformCapabilities } from './PaperSource.js';
interface GoogleScholarOptions extends SearchOptions {
    /** 语言设置 */
    language?: string;
    /** 时间范围（年份） */
    yearLow?: number;
    yearHigh?: number;
    /** 强制忽略本地查询缓存 */
    forceRefresh?: boolean;
}
export interface GoogleScholarRuntimeOptions {
    /** Upstream request rate. The upstream project defaults to 0.5 RPS. */
    rateLimitRps?: number;
    /** Number of retries after the initial request. */
    maxRetries?: number;
    /** HTTP request timeout in milliseconds. */
    timeoutMs?: number;
    /** Stable User-Agent used by the long-lived HTTP client. */
    userAgent?: string;
    /** Accept-Language sent to Scholar. */
    acceptLanguage?: string;
    /** Successful result cache TTL in milliseconds. */
    cacheTtlMs?: number;
}
export declare class GoogleScholarSearcher extends PaperSource {
    private readonly scholarUrl;
    private readonly scholarProxyUrl?;
    private readonly rateLimiter;
    private readonly cache;
    private readonly rateLimitRps;
    private readonly maxRetries;
    private readonly requestTimeoutMs;
    private readonly userAgent;
    private readonly acceptLanguage;
    private readonly keepAliveAgent;
    private cachedProxyConfig?;
    constructor(scholarProxyUrl?: string | undefined, runtimeOptions?: GoogleScholarRuntimeOptions);
    getCapabilities(): PlatformCapabilities;
    /**
     * 搜索Google Scholar论文
     */
    search(query: string, options?: GoogleScholarOptions): Promise<Paper[]>;
    /**
     * Google Scholar不支持直接PDF下载
     */
    downloadPdf(paperId: string, options?: DownloadOptions): Promise<string>;
    /**
     * Google Scholar不提供全文内容
     */
    readPaper(paperId: string, options?: DownloadOptions): Promise<string>;
    /**
     * 构建搜索参数
     */
    private buildSearchParams;
    /**
     * 发起Scholar请求
     */
    private makeScholarRequest;
    /**
     * Build a dedicated proxy agent for Scholar when explicitly configured.
     * Generic HTTP_PROXY/HTTPS_PROXY handling remains available through Axios
     * defaults; this setting lets callers isolate Scholar traffic if needed.
     */
    private getProxyConfig;
    /**
     * Detect Scholar's anti-bot interstitial without treating a normal empty
     * result page as a transport failure.
     */
    private isChallengePage;
    private isChallengeResponse;
    private isRetryableStatus;
    private isNetworkError;
    private waitBeforeRetry;
    private sleep;
    private readPositiveNumber;
    private readNonNegativeInteger;
    private waitForGlobalRequestSlot;
    private withRateLimitLock;
    private acquireRateLimitLock;
    private removeStaleRateLimitLock;
    private getRateLimitPaths;
    private readRateLimitState;
    private writeRateLimitState;
    private createBlockedError;
    private createRateLimitError;
    private createParseError;
    private createProxyConfigError;
    private findResultContainers;
    private isRecognizedEmptyPage;
    /**
     * 解析单个Scholar搜索结果
     */
    private parseScholarResult;
    /**
     * 提取作者信息
     */
    private extractAuthors;
    /**
     * 提取年份
     */
    private extractYear;
    /**
     * 提取期刊信息
     */
    private extractJournal;
    /**
     * 提取引用次数
     */
    private extractCitationCount;
    private extractVersionCount;
    private normalizeScholarLink;
    /**
     * 生成论文ID
     */
    private generatePaperId;
    /**
     * 简单哈希函数
     */
    private simpleHash;
    /**
     * 兼容旧方法名；现在由单一低频令牌桶负责请求间隔。
     */
    private randomDelay;
    /**
     * Expose status for diagnostics without exposing proxy or session data.
     */
    getRateLimiterStatus(): {
        availableTokens: number;
        maxTokens: number;
        requestsPerSecond: number;
        pendingRequests: number;
    };
    getCacheStats(): import("../infrastructure/cache/RequestCache.js").CacheStats;
    dispose(): void;
}
export {};
//# sourceMappingURL=GoogleScholarSearcher.d.ts.map