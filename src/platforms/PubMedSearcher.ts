/**
 * PubMed E-utilities API集成模块
 * 支持无API密钥的免费使用（3 req/s）和有API密钥的增强使用（10 req/s）
 */

import axios from 'axios';
import * as xml2js from 'xml2js';
import { Paper, PaperFactory } from '../models/Paper.js';
import { PaperSource, SearchOptions, DownloadOptions, PlatformCapabilities } from './PaperSource.js';
import { RateLimiter } from '../infrastructure/rate-limit/RateLimiter.js';
import { ErrorHandler } from '../infrastructure/http/ErrorHandler.js';
import { TIMEOUTS, USER_AGENT } from '../config/constants.js';
import { logDebug } from '../utils/Logger.js';

interface PubMedSearchOptions extends SearchOptions {
  /** 搜索字段 */
  field?: string;
  /** 出版状态 */
  pubStatus?: string;
  /** 文献类型 */
  publicationType?: string[];
}

interface ESearchResponse {
  eSearchResult: {
    Count: string;
    IdList: {
      Id: string | string[];
    };
    TranslationSet?: any;
    QueryTranslation?: string;
  };
}

interface ESummaryResponse {
  result: {
    uids: string[];
    [pmid: string]: PubMedArticleSummary | string[];
  };
}

interface PubMedArticleSummary {
  uid: string;
  pubdate: string;
  epubdate: string;
  source: string;
  title: string;
  authors: Array<{
    name: string;
    authtype: string;
  }>;
  lastauthor: string;
  volume: string;
  issue: string;
  pages: string;
  articleids: Array<{
    idtype: string;
    value: string;
  }>;
  fulljournalname: string;
  elocationid: string;
  doctype: string;
  pubstatus: string;
  sortpubdate: string;
}

interface EFetchResponse {
  PubmedArticleSet: {
    PubmedArticle: PubMedArticleDetail[];
  };
}

interface PubMedArticleDetail {
  MedlineCitation: {
    PMID: {
      _: string;
    };
    Article: {
      ArticleTitle: string;
      Abstract?: {
        AbstractText: string | string[];
      };
      AuthorList?: {
        Author: Array<{
          LastName?: string;
          ForeName?: string;
          Initials?: string;
          CollectiveName?: string;
        }>;
      };
      Journal: {
        Title: string;
        ISOAbbreviation: string;
        JournalIssue: {
          Volume?: string;
          Issue?: string;
          PubDate: {
            Year?: string;
            Month?: string;
            Day?: string;
          };
        };
      };
      Pagination?: {
        MedlinePgn: string;
      };
      ArticleIdList?: {
        ArticleId: Array<{
          _: string;
          $: {
            IdType: string;
          };
        }>;
      };
    };
  };
  PubmedData: {
    ArticleIdList?: {
      ArticleId: Array<{
        _: string;
        $: {
          IdType: string;
        };
      }>;
    };
  };
}

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
const listOf = <T>(value: T | T[] | undefined): T[] => (value === undefined ? [] : Array.isArray(value) ? value : [value]);
const textOf = (value: unknown): string => (typeof value === 'string' ? value : typeof (value as { _?: unknown })?._ === 'string' ? (value as { _: string })._ : '').trim();

/** "2024-11" from a PubMed date ("Nov" or "11"), "2024" without a month. */
function pubmedMonth(date: { Year?: unknown; Month?: unknown } | undefined): string | undefined {
  const year = textOf(date?.Year);
  if (!/^\d{4}$/.test(year)) return undefined;
  const month = textOf(date?.Month).toLowerCase();
  const number = /^\d{1,2}$/.test(month) ? Number(month) : MONTHS.indexOf(month.slice(0, 3)) + 1;
  return number >= 1 && number <= 12 ? `${year}-${String(number).padStart(2, '0')}` : year;
}

/** When the paper first came out: the earlier of its electronic date and its issue's (a paper's file name). */
function pubmedIssued(articleData: any): string | undefined {
  const dates = [...listOf(articleData?.ArticleDate), articleData?.Journal?.JournalIssue?.PubDate]
    .map((date) => pubmedMonth(date)).filter((date): date is string => !!date);
  // A month known beats a year alone of the same year; otherwise the earliest.
  return dates.sort((a, b) => a.slice(0, 4).localeCompare(b.slice(0, 4)) || b.length - a.length || a.localeCompare(b))[0];
}

/** NLM's abbreviation of the journal ("Sci Transl Med"). */
function nlmAbbreviation(medlineCitation: any, articleData: any): string | undefined {
  return textOf(medlineCitation?.MedlineJournalInfo?.MedlineTA) || textOf(articleData?.Journal?.ISOAbbreviation) || undefined;
}

function pubmedIssns(articleData: any): string[] {
  return listOf(articleData?.Journal?.ISSN).map(textOf).filter((issn) => /^\d{4}-\d{3}[\dX]$/i.test(issn));
}

export class PubMedSearcher extends PaperSource {
  private readonly baseApiUrl: string;
  private readonly rateLimiter: RateLimiter;
  private readonly retMax: number = 20; // 每次批量获取的最大数量

  constructor(apiKey?: string) {
    super('pubmed', 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils', apiKey);
    this.baseApiUrl = this.baseUrl;
    
    // 根据是否有API密钥设置不同的速率限制
    const requestsPerSecond = apiKey ? 10 : 3;
    this.rateLimiter = new RateLimiter({
      requestsPerSecond,
      burstCapacity: requestsPerSecond,
      debug: process.env.NODE_ENV === 'development'
    });
  }

  getCapabilities(): PlatformCapabilities {
    return {
      search: true,
      download: false, // PubMed不提供直接PDF下载
      fullText: false, // 只有摘要，不是全文
      citations: false, // 基础版本不提供被引统计
      requiresApiKey: false, // 无API密钥也可以使用，但有限制
      supportedOptions: ['maxResults', 'year', 'author', 'journal', 'sortBy']
    };
  }

  /**
   * 搜索PubMed文献
   */
  async search(query: string, options: PubMedSearchOptions = {}): Promise<Paper[]> {
    try {
      logDebug(`PubMed Search Starting: query="${query}"`, options);
      
      // 第一步：使用ESearch获取PMID列表
      const pmids = await this.searchPMIDs(query, options);
      
      if (pmids.length === 0) {
        return [];
      }

      // 第二步：批量获取详细信息
      const papers: Paper[] = [];
      for (let i = 0; i < pmids.length; i += this.retMax) {
        const batch = pmids.slice(i, i + this.retMax);
        const batchPapers = await this.fetchPaperDetails(batch);
        papers.push(...batchPapers);
      }

      return papers;
    } catch (error: any) {
      logDebug('PubMed Search Error:', error.message);
      this.handleHttpError(error, 'search');
    }
  }

  /**
   * 搜索获取PMID列表
   */
  private async searchPMIDs(query: string, options: PubMedSearchOptions): Promise<string[]> {
    await this.rateLimiter.waitForPermission();

    const searchQuery = this.buildSearchQuery(query, options);
    const params: Record<string, string> = {
      db: 'pubmed',
      term: searchQuery,
      retmax: (options.maxResults || 10).toString(),
      retmode: 'xml',
      sort: this.mapSortField(options.sortBy || 'relevance')
    };

    // 添加API密钥（如果有）
    if (this.apiKey) {
      params.api_key = this.apiKey;
    }

    const url = `${this.baseApiUrl}/esearch.fcgi`;
    
    logDebug(`PubMed ESearch Request: GET ${url}`);
    logDebug('PubMed ESearch params:', params);

    const response = await ErrorHandler.retryWithBackoff(
      () => axios.get(url, {
        params,
        timeout: TIMEOUTS.DEFAULT,
        headers: { 'User-Agent': USER_AGENT }
      }),
      { context: 'PubMed ESearch' }
    );
    
    logDebug(`PubMed ESearch Response: ${response.status} ${response.statusText}`);
    logDebug('PubMed ESearch Response data:', response.data.substring(0, 500));
    
    const result: ESearchResponse = await this.parseXmlResponse(response.data);
    let pmids = result.eSearchResult.IdList?.Id || [];
    
    // 处理单个ID vs ID数组
    if (typeof pmids === 'string') {
      pmids = [pmids];
    }
    
    logDebug(`PubMed Found ${pmids.length} PMIDs:`, pmids.slice(0, 5));
    
    return pmids;
  }

  /**
   * 获取论文详细信息
   */
  private async fetchPaperDetails(pmids: string[]): Promise<Paper[]> {
    await this.rateLimiter.waitForPermission();

    const params: Record<string, string> = {
      db: 'pubmed',
      id: pmids.join(','),
      retmode: 'xml'
    };

    // 添加API密钥（如果有）
    if (this.apiKey) {
      params.api_key = this.apiKey;
    }

    const url = `${this.baseApiUrl}/efetch.fcgi`;
    const response = await ErrorHandler.retryWithBackoff(
      () => axios.get(url, {
        params,
        timeout: TIMEOUTS.DEFAULT,
        headers: { 'User-Agent': USER_AGENT }
      }),
      { context: 'PubMed EFetch' }
    );
    
    const result: EFetchResponse = await this.parseXmlResponse(response.data);
    
    // 处理xml2js的单个元素vs数组问题
    let articles = result.PubmedArticleSet?.PubmedArticle || [];
    if (!Array.isArray(articles)) {
      articles = [articles]; // 将单个对象转换为数组
    }
    
    return this.parsePubMedArticles(articles);
  }

  /**
   * 构建搜索查询
   */
  private buildSearchQuery(query: string, options: PubMedSearchOptions): string {
    let searchQuery = query;

    // 添加作者过滤
    if (options.author) {
      searchQuery += ` AND ${options.author}[Author]`;
    }

    // 添加期刊过滤
    if (options.journal) {
      searchQuery += ` AND "${options.journal}"[Journal]`;
    }

    // 添加年份过滤
    if (options.year) {
      if (options.year.includes('-')) {
        const [startYear, endYear] = options.year.split('-');
        if (startYear && endYear) {
          searchQuery += ` AND ${startYear}:${endYear}[Publication Date]`;
        } else if (startYear) {
          searchQuery += ` AND ${startYear}:3000[Publication Date]`;
        } else if (endYear) {
          searchQuery += ` AND 1900:${endYear}[Publication Date]`;
        }
      } else {
        searchQuery += ` AND ${options.year}[Publication Date]`;
      }
    }

    // 添加文献类型过滤
    if (options.publicationType && options.publicationType.length > 0) {
      const typeQuery = options.publicationType
        .map(type => `"${type}"[Publication Type]`)
        .join(' OR ');
      searchQuery += ` AND (${typeQuery})`;
    }

    return searchQuery;
  }

  /**
   * 映射排序字段
   */
  private mapSortField(sortBy: string): string {
    const fieldMap: Record<string, string> = {
      'relevance': 'relevance',
      'date': 'pub+date',
      'citations': 'relevance' // PubMed不直接支持按被引排序
    };
    return fieldMap[sortBy] || 'relevance';
  }

  /**
   * 解析XML响应
   */
  private async parseXmlResponse<T>(xmlData: string): Promise<T> {
    const trimmed = (xmlData || '').trim();
    if (!trimmed) {
      throw new Error('Empty XML response received from PubMed');
    }
    if (!trimmed.startsWith('<')) {
      const preview = trimmed.slice(0, 120).replace(/\s+/g, ' ');
      throw new Error(`Invalid XML response received (expected markup, got: "${preview}...")`);
    }

    // A title or abstract's own markup (S1P<sub>1</sub>, CD4<sup>+</sup>, <i>gene</i>) stays its
    // text: parsed as elements it made the title an object, the record failed and was left out
    // of the results without a word (10.1136/ard-2024-226547, 2026-11-16). PubMed's own
    // elements are capitalised; these lower-case ones are only ever this markup.
    const text = trimmed.replace(/<(\/?)(b|i|u|sup|sub)>/g, '&lt;$1$2&gt;');
    const parser = new xml2js.Parser({
      explicitArray: false,  // 简化数组处理
      mergeAttrs: false,
      normalize: true,
      normalizeTags: false,
      trim: true
    });
    
    logDebug('PubMed XML Parsing - Data preview:', xmlData.substring(0, 200));
    const result = await parser.parseStringPromise(text);
    logDebug('PubMed XML Parsed result structure:', JSON.stringify(result, null, 2).substring(0, 1000));
    
    return result;
  }

  /**
   * 解析PubMed文章列表
   */
  private parsePubMedArticles(articles: PubMedArticleDetail[]): Paper[] {
    return articles.map(article => this.parsePubMedArticle(article))
      .filter(paper => paper !== null) as Paper[];
  }

  /**
   * 解析单个PubMed文章
   */
  private parsePubMedArticle(article: PubMedArticleDetail): Paper | null {
    try {
      const medlineCitation = article.MedlineCitation;
      const articleData = medlineCitation.Article;
      const pubmedData = article.PubmedData;

      // 提取PMID
      const pmid = medlineCitation.PMID._;

      // 提取标题
      const title = articleData.ArticleTitle || 'No title available';

      // 提取作者
      const authors = this.extractAuthors(articleData.AuthorList?.Author || []);

      // 提取摘要
      const abstract = this.extractAbstract(articleData.Abstract);

      // 提取期刊信息
      const journal = articleData.Journal.Title || articleData.Journal.ISOAbbreviation || '';

      // 提取发布日期
      const publishedDate = this.extractPublishedDate(articleData.Journal.JournalIssue.PubDate);

      // 提取DOI和其他ID
      const { doi, pmc } = this.extractArticleIds([
        ...(articleData.ArticleIdList?.ArticleId || []),
        ...(pubmedData.ArticleIdList?.ArticleId || [])
      ]);

      // 提取页码
      const pages = articleData.Pagination?.MedlinePgn || '';

      // 构建URL
      const url = `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`;
      const pdfUrl = pmc ? `https://www.ncbi.nlm.nih.gov/pmc/articles/${pmc}/pdf/` : '';

      return PaperFactory.create({
        paperId: pmid,
        title: this.cleanText(title),
        authors: authors,
        abstract: this.cleanText(abstract),
        doi: doi,
        publishedDate: publishedDate,
        pdfUrl: pdfUrl,
        url: url,
        source: 'pubmed',
        journal: journal,
        volume: articleData.Journal.JournalIssue.Volume || undefined,
        issue: articleData.Journal.JournalIssue.Issue || undefined,
        pages: pages || undefined,
        year: publishedDate?.getFullYear(),
        extra: {
          pmid: pmid,
          pmc: pmc || undefined,
          ...(nlmAbbreviation(medlineCitation, articleData) ? { journalAbbreviation: nlmAbbreviation(medlineCitation, articleData) } : {}),
          ...(pubmedIssued(articleData) ? { issued: pubmedIssued(articleData) } : {}),
          ...(pubmedIssns(articleData).length ? { issn: pubmedIssns(articleData) } : {}),
        }
      });
    } catch (error) {
      logDebug('Error parsing PubMed article:', error);
      return null;
    }
  }

  /**
   * 提取作者信息
   */
  private extractAuthors(authorList: any[]): string[] {
    if (!Array.isArray(authorList)) {
      return [];
    }

    return authorList.map(author => {
      if (author.CollectiveName) {
        return author.CollectiveName;
      }
      
      const lastName = author.LastName || '';
      const foreName = author.ForeName || author.Initials || '';
      
      if (lastName && foreName) {
        return `${lastName}, ${foreName}`;
      } else if (lastName) {
        return lastName;
      } else if (foreName) {
        return foreName;
      }
      
      return 'Unknown Author';
    }).filter(name => name && name !== 'Unknown Author');
  }

  /**
   * 提取摘要
   */
  private extractAbstract(abstractData: any): string {
    if (!abstractData) {
      return '';
    }

    if (typeof abstractData.AbstractText === 'string') {
      return abstractData.AbstractText;
    }

    if (Array.isArray(abstractData.AbstractText)) {
      return abstractData.AbstractText.join(' ');
    }

    return '';
  }

  /**
   * 提取发布日期
   */
  private extractPublishedDate(pubDate: any): Date | null {
    if (!pubDate) {
      return null;
    }

    const year = pubDate.Year;
    const month = pubDate.Month;
    const day = pubDate.Day;

    if (year) {
      const monthNum = month ? this.parseMonth(month) : 1;
      const dayNum = day ? parseInt(day, 10) : 1;
      
      return new Date(parseInt(year, 10), monthNum - 1, dayNum);
    }

    return null;
  }

  /**
   * 解析月份（支持英文和数字）
   */
  private parseMonth(month: string): number {
    const monthMap: Record<string, number> = {
      'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
      'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12,
      'January': 1, 'February': 2, 'March': 3, 'April': 4, 'June': 6,
      'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12
    };

    const mapped = monthMap[month];
    if (mapped) {
      return mapped;
    }

    const num = parseInt(month, 10);
    return (num >= 1 && num <= 12) ? num : 1;
  }

  /**
   * 提取文章ID（DOI、PMC等）
   */
  private extractArticleIds(articleIds: any[]): { doi: string; pmc: string } {
    let doi = '';
    let pmc = '';

    if (Array.isArray(articleIds)) {
      for (const id of articleIds) {
        const idType = id.$?.IdType?.toLowerCase();
        const value = id._;

        if (idType === 'doi' && !doi) {
          doi = value;
        } else if (idType === 'pmc' && !pmc) {
          pmc = value;
        }
      }
    }

    return { doi, pmc };
  }

  /**
   * PubMed通常不支持直接PDF下载
   */
  async downloadPdf(paperId: string, options?: DownloadOptions): Promise<string> {
    // 尝试获取PMC链接
    const paper = await this.getPaperByPmid(paperId);
    if (paper?.extra?.pmc) {
      const pmcUrl = `https://www.ncbi.nlm.nih.gov/pmc/articles/${paper.extra.pmc}/pdf/`;
      throw new Error(`PubMed paper may be available as PDF at PMC: ${pmcUrl}. Direct download not supported through this API.`);
    }
    
    throw new Error('PubMed does not support direct PDF download. Please access the paper through the publisher or PMC.');
  }

  /**
   * PubMed不提供全文内容
   */
  async readPaper(paperId: string, options?: DownloadOptions): Promise<string> {
    throw new Error('PubMed does not provide full-text content. Only abstracts and metadata are available.');
  }

  /**
   * 根据PMID获取论文信息
   */
  async getPaperByPmid(pmid: string): Promise<Paper | null> {
    try {
      const papers = await this.fetchPaperDetails([pmid]);
      return papers.length > 0 ? papers[0] : null;
    } catch (error) {
      logDebug('Error getting paper by PMID:', error);
      return null;
    }
  }

  /**
   * NLM's abbreviation of the journal with one of these ISSNs ("Sci Transl Med"), from the
   * NLM Catalog; ``undefined`` when it has none. Names downloaded files (outputLayout.ts).
   */
  async journalAbbreviation(issns: string[]): Promise<string | undefined> {
    const valid = issns.filter((issn) => /^\d{4}-\d{3}[\dX]$/i.test(issn)).slice(0, 4);
    if (!valid.length) return undefined;
    const key = this.apiKey ? { api_key: this.apiKey } : {};
    const ask = async (endpoint: string, params: Record<string, string>) => {
      await this.rateLimiter.waitForPermission();
      const response = await axios.get(`${this.baseApiUrl}/${endpoint}`, {
        params: { ...params, retmode: 'json', ...key }, timeout: TIMEOUTS.DEFAULT, headers: { 'User-Agent': USER_AGENT },
      });
      return response.data;
    };
    const found = await ask('esearch.fcgi', { db: 'nlmcatalog', term: valid.map((issn) => `${issn}[issn]`).join(' OR '), retmax: '5' });
    const ids: string[] = found?.esearchresult?.idlist ?? [];
    if (!ids.length) return undefined;
    const summary = (await ask('esummary.fcgi', { db: 'nlmcatalog', id: ids.join(',') }))?.result ?? {};
    // The journal's own record, among editions sharing its ISSN ("N Engl J Med Overseas Ed"):
    // the one listing the ISSN, indexed for MEDLINE now.
    const asked = new Set(valid.map((issn) => issn.toUpperCase()));
    const ranked = (summary.uids ?? ids).map((id: string) => summary[id] ?? {}).map((record: any) => ({
      abbreviation: textOf(record.medlineta) || textOf(record.isoabbreviation),
      rank: (listOf(record.issnlist).some((entry: any) => asked.has(textOf(entry?.issn).toUpperCase())) ? 2 : 0)
        + (textOf(record.currentindexingstatus) === 'Y' ? 1 : 0),
    })).filter((record: { abbreviation: string }) => record.abbreviation);
    ranked.sort((a: { rank: number }, b: { rank: number }) => b.rank - a.rank);
    return ranked[0]?.abbreviation || undefined;
  }

  /**
   * 根据DOI获取论文信息
   */
  async getPaperByDoi(doi: string): Promise<Paper | null> {
    try {
      const results = await this.search(`"${doi}"[DOI]`, { maxResults: 1 });
      return results.length > 0 ? results[0] : null;
    } catch (error) {
      logDebug('Error getting paper by DOI from PubMed:', error);
      return null;
    }
  }

  /**
   * 获取速率限制器状态
   */
  getRateLimiterStatus() {
    return this.rateLimiter.getStatus();
  }

  /**
   * 验证API密钥（如果提供）
   */
  async validateApiKey(): Promise<boolean> {
    if (!this.apiKey) {
      return true; // 无API密钥时总是有效（使用免费限制）
    }

    try {
      await this.search('test', { maxResults: 1 });
      return true;
    } catch (error: any) {
      // API密钥无效通常返回400或403错误
      if (error.response?.status === 400 || error.response?.status === 403) {
        return false;
      }
      // 其他错误可能是网络问题，认为密钥可能有效
      return true;
    }
  }
}