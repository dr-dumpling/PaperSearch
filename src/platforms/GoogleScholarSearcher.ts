/**
 * Google Scholar搜索器 - 网页抓取实现
 * 基于HTML解析，包含低频请求与挑战页识别
 */

import axios, { type AxiosRequestConfig, type AxiosResponse } from 'axios';
import * as cheerio from 'cheerio';
import * as fs from 'fs';
import * as https from 'https';
import * as os from 'os';
import * as path from 'path';
import { HttpsProxyAgent } from 'https-proxy-agent';
import { SocksProxyAgent } from 'socks-proxy-agent';
import { Paper, PaperFactory } from '../models/Paper.js';
import { PaperSource, SearchOptions, DownloadOptions, PlatformCapabilities } from './PaperSource.js';
import { TIMEOUTS } from '../config/constants.js';
import { logDebug } from '../utils/Logger.js';
import { ApiError, ErrorHandler } from '../infrastructure/http/ErrorHandler.js';
import { RateLimiter } from '../infrastructure/rate-limit/RateLimiter.js';
import { RequestCache } from '../infrastructure/cache/RequestCache.js';

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

const SCHOLAR_REQUEST_TIMEOUT_MS = 15000;
const SCHOLAR_DEFAULT_RATE_LIMIT_RPS = 0.5;
const SCHOLAR_DEFAULT_MAX_RETRIES = 2;
const SCHOLAR_RETRY_BASE_DELAY_MS = 300;
const SCHOLAR_RETRY_JITTER_MS = 250;
const SCHOLAR_MAX_RETRY_DELAY_MS = 15000;
const SCHOLAR_CACHE_TTL_MS = 3_600_000;
const SCHOLAR_RATE_LIMIT_LOCK_STALE_MS = 10_000;
const SCHOLAR_RATE_LIMIT_LOCK_POLL_MS = 100;
const SCHOLAR_DEFAULT_USER_AGENT =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36';
const SCHOLAR_DEFAULT_ACCEPT_LANGUAGE = 'en-US,en;q=0.9';

type ScholarProxyConfig = Pick<AxiosRequestConfig, 'httpAgent' | 'httpsAgent' | 'proxy'>;

interface ScholarRateLimitState {
  lastRequestAt?: number;
}

const SCHOLAR_CHALLENGE_PATTERNS = [
  /our systems have detected unusual traffic/i,
  /unusual traffic from your computer network/i,
  /automated queries/i,
  /not a robot/i,
  /(?:g-recaptcha|hcaptcha|gs_captcha|captcha-form)/i,
  /\/sorry(?:\/|\?)/i
];

const SCHOLAR_BLOCKED_MESSAGE =
  'Google Scholar returned an anti-bot challenge (CAPTCHA or unusual-traffic page). ' +
  'Wait before retrying or configure GOOGLE_SCHOLAR_PROXY_URL with an authorized proxy.';

const SCHOLAR_RATE_LIMIT_MESSAGE =
  'Google Scholar rate-limited the request (HTTP 429). Wait before retrying; ' +
  'if it persists, use another source or an authorized separate egress.';

export class GoogleScholarSearcher extends PaperSource {
  private readonly scholarUrl = 'https://scholar.google.com/scholar';
  private readonly scholarProxyUrl?: string;
  private readonly rateLimiter: RateLimiter;
  private readonly cache: RequestCache<Paper[]>;
  private readonly rateLimitRps: number;
  private readonly maxRetries: number;
  private readonly requestTimeoutMs: number;
  private readonly userAgent: string;
  private readonly acceptLanguage: string;
  private readonly keepAliveAgent: https.Agent;
  private cachedProxyConfig?: ScholarProxyConfig;

  constructor(
    scholarProxyUrl = process.env.GOOGLE_SCHOLAR_PROXY_URL,
    runtimeOptions: GoogleScholarRuntimeOptions = {}
  ) {
    super('google_scholar', 'https://scholar.google.com');
    this.scholarProxyUrl = scholarProxyUrl?.trim() || undefined;

    const configuredRate = runtimeOptions.rateLimitRps ?? this.readPositiveNumber(
      process.env.SCHOLAR_RATE_LIMIT_RPS,
      SCHOLAR_DEFAULT_RATE_LIMIT_RPS
    );
    const configuredRetries = runtimeOptions.maxRetries ?? this.readNonNegativeInteger(
      process.env.SCHOLAR_MAX_RETRIES,
      SCHOLAR_DEFAULT_MAX_RETRIES
    );
    const configuredTimeout = runtimeOptions.timeoutMs ?? this.readPositiveNumber(
      process.env.SCHOLAR_TIMEOUT_MS,
      SCHOLAR_REQUEST_TIMEOUT_MS
    );

    this.rateLimiter = new RateLimiter({
      requestsPerSecond: configuredRate,
      burstCapacity: 1,
      debug: process.env.NODE_ENV === 'development'
    });
    this.rateLimitRps = configuredRate;
    this.cache = new RequestCache<Paper[]>({
      maxSize: 100,
      ttlMs: runtimeOptions.cacheTtlMs ?? SCHOLAR_CACHE_TTL_MS
    });
    this.maxRetries = configuredRetries;
    this.requestTimeoutMs = Math.min(configuredTimeout, TIMEOUTS.DEFAULT);
    this.userAgent = runtimeOptions.userAgent || SCHOLAR_DEFAULT_USER_AGENT;
    this.acceptLanguage = runtimeOptions.acceptLanguage || SCHOLAR_DEFAULT_ACCEPT_LANGUAGE;
    this.keepAliveAgent = new https.Agent({ keepAlive: true, maxSockets: 1 });
  }

  getCapabilities(): PlatformCapabilities {
    return {
      search: true,
      download: false, // Google Scholar不提供直接下载
      fullText: false, // 只有元数据和摘要
      citations: true, // 可以获取引用次数
      requiresApiKey: false, // 不需要API密钥，但可能被限制
      supportedOptions: ['maxResults', 'year', 'author']
    };
  }

  /**
   * 搜索Google Scholar论文
   */
  async search(query: string, options: GoogleScholarOptions = {}): Promise<Paper[]> {
    logDebug(`Google Scholar Search: query="${query}"`);
    
    try {
      const forceRefresh = options.forceRefresh === true;
      const cacheOptions = { ...options };
      delete cacheOptions.forceRefresh;
      const cacheKey = this.cache.generateKey('googlescholar', query, cacheOptions);

      if (!forceRefresh) {
        const cached = this.cache.get(cacheKey);
        if (cached) {
          logDebug(`Google Scholar: cache hit for query="${query}"`);
          return cached;
        }
      }

      const papers: Paper[] = [];
      let start = 0;
      const maxResults = options.maxResults || 10;

      while (papers.length < maxResults) {
        // The upstream bingshuoguo client uses a single low-volume limiter
        // instead of opening a burst of requests from concurrent callers.
        await this.randomDelay();
        
        const params = this.buildSearchParams(query, start, options);
        const response = await this.makeScholarRequest(params);

        if (this.isChallengePage(response.data)) {
          throw this.createBlockedError();
        }

        const $ = cheerio.load(response.data);
        const results = this.findResultContainers($); // 搜索结果容器

        if (results.length === 0) {
          if (!this.isRecognizedEmptyPage(response.data)) {
            throw this.createParseError();
          }
          logDebug('Google Scholar: No more results found');
          break;
        }

        logDebug(`Google Scholar: Found ${results.length} results on page`);

        // 解析每个结果
        results.each((index, element) => {
          if (papers.length >= maxResults) return false; // 停止遍历
          
          const paper = this.parseScholarResult($, $(element));
          if (paper) {
            papers.push(paper);
          }
        });

        // Advance by the number of raw result blocks returned. Scholar may
        // honor `num` (up to 20) or silently fall back to its default page
        // size; using the observed count avoids overlapping pages either way.
        start += results.length;
      }

      logDebug(`Google Scholar Results: Found ${papers.length} papers`);
      this.cache.set(cacheKey, papers);
      return papers;
      
    } catch (error: any) {
      if (error instanceof ApiError) {
        throw error;
      }

      // A challenge can arrive as a 403/429 response body instead of a 200
      // interstitial page. Report the same actionable error in both cases.
      if (this.isChallengePage(error?.response?.data)) {
        throw this.createBlockedError();
      }

      this.handleHttpError(error, 'search');
    }
  }

  /**
   * Google Scholar不支持直接PDF下载
   */
  async downloadPdf(paperId: string, options?: DownloadOptions): Promise<string> {
    throw new Error('Google Scholar does not support direct PDF download. Please use the paper URL to access the publisher.');
  }

  /**
   * Google Scholar不提供全文内容
   */
  async readPaper(paperId: string, options?: DownloadOptions): Promise<string> {
    throw new Error('Google Scholar does not provide full-text content. Please use the paper URL to access the full text.');
  }

  /**
   * 构建搜索参数
   */
  private buildSearchParams(query: string, start: number, options: GoogleScholarOptions): Record<string, any> {
    const params: Record<string, any> = {
      q: query,
      start: start,
      num: Math.min(options.maxResults || 10, 20),
      hl: options.language || 'en',
      as_sdt: '0,5', // 包括文章和引用
      as_vis: '1' // 排除引用，只显示学术论文
    };

    // 添加年份过滤
    if (options.yearLow || options.yearHigh) {
      params.as_ylo = options.yearLow || '';
      params.as_yhi = options.yearHigh || '';
    }

    // 添加作者过滤
    if (options.author) {
      params.as_sauthors = options.author;
    }

    return params;
  }

  /**
   * 发起Scholar请求
   */
  private async makeScholarRequest(params: Record<string, any>): Promise<AxiosResponse<string>> {
    const config: AxiosRequestConfig = {
      params,
      headers: {
        'User-Agent': this.userAgent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': this.acceptLanguage,
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
      },
      timeout: this.requestTimeoutMs,
      maxRedirects: 5,
      // Inspect 3xx/4xx bodies ourselves so `/sorry/` and CAPTCHA pages are
      // classified as blocked rather than silently becoming empty results.
      validateStatus: () => true,
      httpsAgent: this.keepAliveAgent,
      ...this.getProxyConfig()
    };

    logDebug(`Google Scholar Request: GET ${this.scholarUrl}`);
    logDebug('Scholar params:', params);

    let lastError: unknown;
    for (let attempt = 0; attempt <= this.maxRetries; attempt += 1) {
      try {
        const response = await axios.get<string>(this.scholarUrl, config);

        if (this.isChallengeResponse(response)) {
          throw this.createBlockedError();
        }

        if (response.status === 200) {
          return response;
        }

        if (response.status === 429) {
          if (attempt < this.maxRetries) {
            await this.waitBeforeRetry({ response }, attempt);
            continue;
          }
          throw this.createRateLimitError();
        }

        if (this.isRetryableStatus(response.status) && attempt < this.maxRetries) {
          await this.waitBeforeRetry({ response }, attempt);
          continue;
        }

        this.handleHttpError({ response, config }, 'search');
      } catch (error: any) {
        if (error instanceof ApiError) {
          throw error;
        }

        if (this.isChallengeResponse(error)) {
          throw this.createBlockedError();
        }

        const status = error?.response?.status;
        if (status === 429 && attempt < this.maxRetries) {
          await this.waitBeforeRetry(error, attempt);
          continue;
        }

        if ((this.isRetryableStatus(status) || this.isNetworkError(error)) && attempt < this.maxRetries) {
          await this.waitBeforeRetry(error, attempt);
          continue;
        }

        if (status === 429) {
          throw this.createRateLimitError();
        }

        lastError = error;
        break;
      }
    }

    if (lastError) {
      throw lastError;
    }

    throw new Error('Google Scholar request retries exhausted.');
  }

  /**
   * Build a dedicated proxy agent for Scholar when explicitly configured.
   * Generic HTTP_PROXY/HTTPS_PROXY handling remains available through Axios
   * defaults; this setting lets callers isolate Scholar traffic if needed.
   */
  private getProxyConfig(): ScholarProxyConfig {
    if (this.cachedProxyConfig) return this.cachedProxyConfig;
    if (!this.scholarProxyUrl) {
      this.cachedProxyConfig = {};
      return this.cachedProxyConfig;
    }

    let proxyUrl: URL;
    try {
      proxyUrl = new URL(this.scholarProxyUrl);
    } catch {
      throw this.createProxyConfigError('GOOGLE_SCHOLAR_PROXY_URL must be a valid HTTP(S) or SOCKS proxy URL.');
    }

    if (proxyUrl.protocol === 'http:' || proxyUrl.protocol === 'https:') {
      this.cachedProxyConfig = {
        httpsAgent: new HttpsProxyAgent(this.scholarProxyUrl),
        proxy: false
      };
      return this.cachedProxyConfig;
    }

    if (['socks4:', 'socks4a:', 'socks5:', 'socks5h:'].includes(proxyUrl.protocol)) {
      const agent = new SocksProxyAgent(this.scholarProxyUrl);
      this.cachedProxyConfig = {
        httpAgent: agent,
        httpsAgent: agent,
        proxy: false
      };
      return this.cachedProxyConfig;
    }

    throw this.createProxyConfigError(
      'GOOGLE_SCHOLAR_PROXY_URL must use http:, https:, socks4:, socks4a:, socks5:, or socks5h:.'
    );
  }

  /**
   * Detect Scholar's anti-bot interstitial without treating a normal empty
   * result page as a transport failure.
   */
  private isChallengePage(data: unknown): boolean {
    if (typeof data !== 'string' || data.length === 0) return false;

    const document = cheerio.load(data);
    if (document('#gs_captcha_ccl, form#captcha-form').length > 0) return true;

    const bodyText = document('body').text().replace(/\s+/g, ' ').trim();
    return SCHOLAR_CHALLENGE_PATTERNS.some(pattern => pattern.test(bodyText) || pattern.test(data));
  }

  private isChallengeResponse(value: any): boolean {
    const response = value?.response || value;
    const body = response?.data;
    const responseUrl =
      response?.request?.res?.responseUrl ||
      response?.request?.responseURL ||
      response?.config?.url ||
      value?.config?.url ||
      '';

    return this.isChallengePage(body) || /\/sorry(?:\/|\?)/i.test(String(responseUrl));
  }

  private isRetryableStatus(status: unknown): boolean {
    return typeof status === 'number' && [408, 429, 500, 502, 503, 504].includes(status);
  }

  private isNetworkError(error: any): boolean {
    return !error?.response && ['ECONNABORTED', 'ETIMEDOUT', 'ECONNRESET', 'ENOTFOUND'].includes(error?.code);
  }

  private async waitBeforeRetry(error: any, attempt: number): Promise<void> {
    const headers = error?.response?.headers;
    const hasRetryAfter = headers && (
      headers['retry-after'] !== undefined ||
      headers['Retry-After'] !== undefined ||
      typeof headers.get === 'function' && headers.get('retry-after') !== undefined
    );
    const retryAfter = hasRetryAfter ? ErrorHandler.getRetryDelay(error, attempt + 1) : undefined;
    const baseDelay = retryAfter === undefined
      ? SCHOLAR_RETRY_BASE_DELAY_MS * (attempt + 1)
      : retryAfter;
    const boundedDelay = Math.min(
      SCHOLAR_MAX_RETRY_DELAY_MS,
      Math.max(SCHOLAR_RETRY_BASE_DELAY_MS, baseDelay)
    );
    const jitter = Math.floor(Math.random() * SCHOLAR_RETRY_JITTER_MS);
    const delay = boundedDelay + jitter;

    logDebug(`Google Scholar retry ${attempt + 1}/${this.maxRetries} in ${delay}ms`);
    await this.sleep(delay);
  }

  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  private readPositiveNumber(value: string | undefined, fallback: number): number {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  }

  private readNonNegativeInteger(value: string | undefined, fallback: number): number {
    const parsed = Number(value);
    return Number.isInteger(parsed) && parsed >= 0 ? parsed : fallback;
  }

  private async waitForGlobalRequestSlot(): Promise<void> {
    await this.withRateLimitLock(async () => {
      const paths = this.getRateLimitPaths();
      const state = this.readRateLimitState(paths.statePath);
      const intervalMs = 1000 / this.rateLimitRps;
      const waitMs = Math.max(0, (state.lastRequestAt || 0) + intervalMs - Date.now());

      if (waitMs > 0) {
        await this.sleep(waitMs);
      }

      this.writeRateLimitState(paths.statePath, { lastRequestAt: Date.now() });
    });
  }

  private async withRateLimitLock<T>(operation: () => Promise<T>): Promise<T> {
    const paths = this.getRateLimitPaths();
    fs.mkdirSync(paths.dir, { recursive: true });
    const fd = await this.acquireRateLimitLock(paths.lockPath);

    try {
      return await operation();
    } finally {
      fs.closeSync(fd);
      fs.rmSync(paths.lockPath, { force: true });
    }
  }

  private async acquireRateLimitLock(lockPath: string): Promise<number> {
    while (true) {
      try {
        return fs.openSync(lockPath, 'wx');
      } catch (error: any) {
        if (error?.code !== 'EEXIST') {
          throw error;
        }

        this.removeStaleRateLimitLock(lockPath);
        await this.sleep(SCHOLAR_RATE_LIMIT_LOCK_POLL_MS);
      }
    }
  }

  private removeStaleRateLimitLock(lockPath: string): void {
    try {
      const stats = fs.statSync(lockPath);
      if (Date.now() - stats.mtimeMs > SCHOLAR_RATE_LIMIT_LOCK_STALE_MS) {
        fs.rmSync(lockPath, { force: true });
      }
    } catch {
      // Another process may have released the lock between stat and remove.
    }
  }

  private getRateLimitPaths(): { dir: string; statePath: string; lockPath: string } {
    const dir = process.env.PAPER_SEARCH_CACHE_DIR || path.join(os.homedir(), '.cache', 'paper-search');
    return {
      dir,
      statePath: path.join(dir, 'google-scholar-rate-limit.json'),
      lockPath: path.join(dir, 'google-scholar-rate-limit.lock')
    };
  }

  private readRateLimitState(statePath: string): ScholarRateLimitState {
    try {
      if (!fs.existsSync(statePath)) return {};
      const parsed = JSON.parse(fs.readFileSync(statePath, 'utf8')) as ScholarRateLimitState;
      return {
        lastRequestAt: typeof parsed.lastRequestAt === 'number' ? parsed.lastRequestAt : undefined
      };
    } catch {
      return {};
    }
  }

  private writeRateLimitState(statePath: string, state: ScholarRateLimitState): void {
    fs.writeFileSync(statePath, `${JSON.stringify(state, null, 2)}\n`);
  }

  private createBlockedError(): ApiError {
    return new ApiError({
      message: SCHOLAR_BLOCKED_MESSAGE,
      status: 429,
      platform: 'google_scholar',
      operation: 'search',
      details: { reason: 'anti_bot_challenge' }
    });
  }

  private createRateLimitError(): ApiError {
    return new ApiError({
      message: SCHOLAR_RATE_LIMIT_MESSAGE,
      status: 429,
      platform: 'google_scholar',
      operation: 'search',
      details: { reason: 'rate_limited' }
    });
  }

  private createParseError(): ApiError {
    return new ApiError({
      message: 'Google Scholar returned an unrecognized HTML page; the result layout may have changed.',
      status: 502,
      platform: 'google_scholar',
      operation: 'search',
      details: { reason: 'parse_failed' }
    });
  }

  private createProxyConfigError(message: string): ApiError {
    return new ApiError({
      message,
      status: 400,
      platform: 'google_scholar',
      operation: 'search',
      details: { reason: 'invalid_proxy_configuration' }
    });
  }

  private findResultContainers($: cheerio.CheerioAPI): cheerio.Cheerio<any> {
    let results: cheerio.Cheerio<any> = $('.gs_r.gs_or.gs_scl') as cheerio.Cheerio<any>;
    if (results.length === 0) {
      results = $('.gs_ri').closest('.gs_r');
    }
    if (results.length === 0) {
      results = $('.gs_ri');
    }
    return results;
  }

  private isRecognizedEmptyPage(data: unknown): boolean {
    if (typeof data !== 'string' || data.length === 0) return false;
    const document = cheerio.load(data);
    if (document('#gs_res_ccl_mid, .gs_med').length > 0) return true;
    return /no (?:matching )?results|did not match any articles/i.test(document('body').text());
  }

  /**
   * 解析单个Scholar搜索结果
   */
  private parseScholarResult($: cheerio.CheerioAPI, element: cheerio.Cheerio<any>): Paper | null {
    try {
      const nestedResult = element.find('div.gs_ri').first();
      const content = nestedResult.length > 0 ? nestedResult : element;
      const parentResult = element.closest('.gs_r').first();
      const root = parentResult.length > 0 ? parentResult : element;

      // 提取标题和链接
      const titleElement = content.find('h3.gs_rt').first();
      const titleLink = titleElement.find('a');
      const rawTitle = titleElement.text().trim();
      const title = rawTitle.replace(/^\s*\[(?:PDF|HTML|BOOK|B)\]\s*/i, '').trim();
      const url = this.normalizeScholarLink(titleLink.attr('href') || '');

      if (!title) {
        return null;
      }

      // 过滤掉书籍结果，优先学术论文
      const titleText = titleElement.text();
      if (titleText.includes('[BOOK]') || titleText.includes('[B]') || 
          url.includes('books.google.com')) {
        return null; // 跳过书籍结果
      }

      // 提取作者和出版信息
      const infoElement = content.find('div.gs_a').first();
      const infoText = infoElement.text();
      const authors = this.extractAuthors(infoText);
      const year = this.extractYear(infoText);

      // 提取摘要
      const abstractElement = content.find('div.gs_rs, div.gs_rs_w').first();
      const abstract = abstractElement.text() || '';

      // 提取引用次数
      const citationElement = root.find('div.gs_fl a').filter((i, el) => {
        return $(el).text().includes('Cited by');
      });
      const citationText = citationElement.text();
      const citationCount = this.extractCitationCount(citationText);
      const versionText = root.find('div.gs_fl a').filter((i, el) => {
        return /all \d+ versions/i.test($(el).text());
      }).first().text();
      const versionCount = this.extractVersionCount(versionText);
      const pdfUrl = this.normalizeScholarLink(root.find('div.gs_or_ggsm a').first().attr('href') || '');

      // 生成论文ID
      const paperId = this.generatePaperId(title, authors);

      return PaperFactory.create({
        paperId,
        title: this.cleanText(title),
        authors,
        abstract: this.cleanText(abstract),
        doi: '', // Google Scholar通常不直接提供DOI
        publishedDate: year ? new Date(year, 0, 1) : null,
        pdfUrl,
        url,
        source: 'googlescholar',
        categories: [],
        keywords: [],
        citationCount,
        journal: this.extractJournal(infoText),
        year,
        extra: {
          scholarId: paperId,
          infoText,
          versionCount
        }
      });
    } catch (error) {
      logDebug('Error parsing Google Scholar result:', error);
      return null;
    }
  }

  /**
   * 提取作者信息
   */
  private extractAuthors(infoText: string): string[] {
    const parts = infoText.split(' - ');
    if (parts.length > 0) {
      const authorPart = parts[0];
      return authorPart.split(',').map(author => author.trim()).filter(a => a.length > 0);
    }
    return [];
  }

  /**
   * 提取年份
   */
  private extractYear(text: string): number | undefined {
    const yearMatch = text.match(/\b(19|20)\d{2}\b/);
    return yearMatch ? parseInt(yearMatch[0], 10) : undefined;
  }

  /**
   * 提取期刊信息
   */
  private extractJournal(infoText: string): string {
    const parts = infoText.split(' - ');
    if (parts.length > 1) {
      // 通常期刊在第二部分
      return parts.slice(1).join(' - ').split(',')[0].trim();
    }
    return '';
  }

  /**
   * 提取引用次数
   */
  private extractCitationCount(citationText: string): number {
    const match = citationText.match(/Cited by ([\d,]+)/i);
    return match ? parseInt(match[1].replace(/,/g, ''), 10) : 0;
  }

  private extractVersionCount(versionText: string): number {
    const match = versionText.match(/All (\d+) versions/i);
    return match ? parseInt(match[1], 10) : 0;
  }

  private normalizeScholarLink(link: string): string {
    if (!link) return '';
    try {
      return new URL(link, this.scholarUrl).toString();
    } catch {
      return link;
    }
  }

  /**
   * 生成论文ID
   */
  private generatePaperId(title: string, authors: string[]): string {
    const titleHash = this.simpleHash(title);
    const authorHash = this.simpleHash(authors.join(''));
    return `gs_${titleHash}_${authorHash}`;
  }

  /**
   * 简单哈希函数
   */
  private simpleHash(str: string): string {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash; // 转换为32位整数
    }
    return Math.abs(hash).toString(36);
  }

  /**
   * 兼容旧方法名；现在由单一低频令牌桶负责请求间隔。
   */
  private async randomDelay(): Promise<void> {
    await this.rateLimiter.waitForPermission();
    await this.waitForGlobalRequestSlot();
  }

  /**
   * Expose status for diagnostics without exposing proxy or session data.
   */
  getRateLimiterStatus() {
    return this.rateLimiter.getStatus();
  }

  getCacheStats() {
    return this.cache.getStats();
  }

  dispose(): void {
    this.rateLimiter.dispose();
    this.keepAliveAgent.destroy();
  }
}
