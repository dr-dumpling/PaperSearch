/**
 * GoogleScholarSearcher Platform Tests
 */

import axios from 'axios';
import { mkdtempSync, rmSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
import { ApiError } from '../../src/infrastructure/http/ErrorHandler.js';
import { GoogleScholarSearcher } from '../../src/platforms/GoogleScholarSearcher.js';

const SCHOLAR_RESULTS_HTML = `
  <div class="gs_ri">
    <h3 class="gs_rt"><a href="https://example.org/one">First test paper</a></h3>
    <div class="gs_a">Jane Doe, John Roe - Journal of Tests, 2024</div>
    <div class="gs_rs">First abstract.</div>
    <div class="gs_fl"><a href="/scholar?cites=1">Cited by 12</a></div>
  </div>
  <div class="gs_ri">
    <h3 class="gs_rt"><a href="https://example.org/two">Second test paper</a></h3>
    <div class="gs_a">Alex Smith - Another Journal, 2023</div>
    <div class="gs_rs">Second abstract.</div>
    <div class="gs_fl"><a href="/scholar?cites=2">Cited by 3</a></div>
  </div>
`;

const SCHOLAR_RICH_RESULT_HTML = `
  <div class="gs_r gs_or gs_scl">
    <div class="gs_ri">
      <h3 class="gs_rt"><a href="https://example.org/rich">Rich result</a></h3>
      <div class="gs_a">Researcher One, Researcher Two - Journal of Rich Results, 2025</div>
      <div class="gs_rs">Rich abstract.</div>
      <div class="gs_fl">
        <a href="/scholar?cites=9">Cited by 1,234</a>
        <a href="/scholar?cluster=9">All 7 versions</a>
      </div>
    </div>
    <div class="gs_or_ggsm"><a href="https://example.org/rich.pdf">[PDF]</a></div>
  </div>
`;

describe('GoogleScholarSearcher', () => {
  let searcher: GoogleScholarSearcher;
  let originalScholarProxy: string | undefined;
  let originalScholarRate: string | undefined;
  let originalScholarRetries: string | undefined;
  let originalScholarTimeout: string | undefined;
  let originalCacheDir: string | undefined;
  let tempCacheDir: string | undefined;

  beforeEach(() => {
    originalScholarProxy = process.env.GOOGLE_SCHOLAR_PROXY_URL;
    originalScholarRate = process.env.SCHOLAR_RATE_LIMIT_RPS;
    originalScholarRetries = process.env.SCHOLAR_MAX_RETRIES;
    originalScholarTimeout = process.env.SCHOLAR_TIMEOUT_MS;
    originalCacheDir = process.env.PAPER_SEARCH_CACHE_DIR;
    delete process.env.GOOGLE_SCHOLAR_PROXY_URL;
    delete process.env.SCHOLAR_RATE_LIMIT_RPS;
    delete process.env.SCHOLAR_MAX_RETRIES;
    delete process.env.SCHOLAR_TIMEOUT_MS;
    delete process.env.PAPER_SEARCH_CACHE_DIR;
    searcher = new GoogleScholarSearcher();

    // Keep unit tests deterministic and independent of the real request delay.
    (searcher as any).randomDelay = async () => undefined;
  });

  afterEach(() => {
    if (originalScholarProxy === undefined) delete process.env.GOOGLE_SCHOLAR_PROXY_URL;
    else process.env.GOOGLE_SCHOLAR_PROXY_URL = originalScholarProxy;
    if (originalScholarRate === undefined) delete process.env.SCHOLAR_RATE_LIMIT_RPS;
    else process.env.SCHOLAR_RATE_LIMIT_RPS = originalScholarRate;
    if (originalScholarRetries === undefined) delete process.env.SCHOLAR_MAX_RETRIES;
    else process.env.SCHOLAR_MAX_RETRIES = originalScholarRetries;
    if (originalScholarTimeout === undefined) delete process.env.SCHOLAR_TIMEOUT_MS;
    else process.env.SCHOLAR_TIMEOUT_MS = originalScholarTimeout;
    if (originalCacheDir === undefined) delete process.env.PAPER_SEARCH_CACHE_DIR;
    else process.env.PAPER_SEARCH_CACHE_DIR = originalCacheDir;
    if (tempCacheDir) rmSync(tempCacheDir, { recursive: true, force: true });
    searcher.dispose();
    jest.restoreAllMocks();
  });

  describe('getCapabilities', () => {
    it('should return correct capabilities', () => {
      const caps = searcher.getCapabilities();
      expect(caps.search).toBe(true);
      expect(caps.download).toBe(false);
      expect(caps.citations).toBe(true);
      expect(caps.requiresApiKey).toBe(false);
    });
  });

  it('parses academic results and sends a bounded result-page size', async () => {
    const axiosGet = jest.spyOn(axios, 'get').mockResolvedValue({
      status: 200,
      data: SCHOLAR_RESULTS_HTML
    } as any);

    const papers = await searcher.search('test query', {
      maxResults: 2,
      yearLow: 2020,
      yearHigh: 2024,
      author: 'Jane Doe'
    });

    expect(papers).toHaveLength(2);
    expect(papers[0]).toEqual(expect.objectContaining({
      title: 'First test paper',
      authors: ['Jane Doe', 'John Roe'],
      year: 2024,
      citationCount: 12,
      source: 'googlescholar'
    }));
    expect((axiosGet.mock.calls[0]?.[1] as any).params).toEqual(expect.objectContaining({
      q: 'test query',
      start: 0,
      num: 2,
      as_ylo: 2020,
      as_yhi: 2024,
      as_sauthors: 'Jane Doe'
    }));
  });

  it('retries one 429 response and honors Retry-After', async () => {
    const rateLimitError = {
      response: {
        status: 429,
        headers: { 'retry-after': '0' },
        data: 'Too Many Requests'
      },
      config: { url: 'https://scholar.google.com/scholar' }
    };
    const axiosGet = jest.spyOn(axios, 'get')
      .mockRejectedValueOnce(rateLimitError)
      .mockResolvedValueOnce({ status: 200, data: SCHOLAR_RESULTS_HTML } as any);

    const papers = await searcher.search('retry query', { maxResults: 1 });

    expect(papers).toHaveLength(1);
    expect(axiosGet).toHaveBeenCalledTimes(2);
  });

  it('uses the upstream low-volume retry budget for transient 503 responses', async () => {
    const axiosGet = jest.spyOn(axios, 'get')
      .mockResolvedValueOnce({ status: 503, data: 'temporarily unavailable' } as any)
      .mockResolvedValueOnce({ status: 503, data: 'temporarily unavailable' } as any)
      .mockResolvedValueOnce({ status: 200, data: SCHOLAR_RESULTS_HTML } as any);
    (searcher as any).waitBeforeRetry = async () => undefined;

    const papers = await searcher.search('transient query', { maxResults: 1 });

    expect(papers).toHaveLength(1);
    expect(axiosGet).toHaveBeenCalledTimes(3);
  });

  it('caches successful queries and allows an explicit refresh', async () => {
    const axiosGet = jest.spyOn(axios, 'get').mockResolvedValue({
      status: 200,
      data: SCHOLAR_RESULTS_HTML
    } as any);

    await searcher.search('cached query', { maxResults: 1 });
    await searcher.search('cached query', { maxResults: 1 });
    await searcher.search('cached query', { maxResults: 1, forceRefresh: true });

    expect(axiosGet).toHaveBeenCalledTimes(2);
    expect(searcher.getCacheStats().size).toBe(1);
  });

  it('extracts PDF, citation, and version signals from the upstream result shape', async () => {
    jest.spyOn(axios, 'get').mockResolvedValue({
      status: 200,
      data: SCHOLAR_RICH_RESULT_HTML
    } as any);

    const papers = await searcher.search('rich query', { maxResults: 1 });

    expect(papers[0]).toEqual(expect.objectContaining({
      title: 'Rich result',
      citationCount: 1234,
      pdfUrl: 'https://example.org/rich.pdf'
    }));
    expect(papers[0]?.extra).toEqual(expect.objectContaining({ versionCount: 7 }));
  });

  it('returns an actionable ApiError for a CAPTCHA or unusual-traffic page', async () => {
    const axiosGet = jest.spyOn(axios, 'get').mockResolvedValue({
      status: 200,
      data: '<html><body><h1>Our systems have detected unusual traffic from your computer network.</h1></body></html>'
    } as any);

    await expect(searcher.search('blocked query', { maxResults: 1 })).rejects.toEqual(
      expect.objectContaining({
        name: 'ApiError',
        status: 429,
        message: expect.stringContaining('anti-bot challenge')
      })
    );
    expect(axiosGet).toHaveBeenCalledTimes(1);
  });

  it('detects a challenge body even when Scholar responds with 403', async () => {
    const challengeError = {
      response: {
        status: 403,
        data: '<html><body><div class="g-recaptcha">not a robot</div></body></html>'
      },
      config: { url: 'https://scholar.google.com/scholar' }
    };
    jest.spyOn(axios, 'get').mockRejectedValue(challengeError);

    await expect(searcher.search('blocked query', { maxResults: 1 })).rejects.toEqual(
      expect.objectContaining({
        name: 'ApiError',
        status: 429,
        message: expect.stringContaining('GOOGLE_SCHOLAR_PROXY_URL')
      })
    );
  });

  it('stops immediately on a /sorry challenge redirect instead of retrying it', async () => {
    const axiosGet = jest.spyOn(axios, 'get').mockResolvedValue({
      status: 302,
      data: '<a href="/sorry/index?continue=abc">continue</a>',
      request: { res: { responseUrl: 'https://scholar.google.com/sorry/index?continue=abc' } }
    } as any);

    await expect(searcher.search('redirect challenge', { maxResults: 1 })).rejects.toEqual(
      expect.objectContaining({
        name: 'ApiError',
        status: 429,
        message: expect.stringContaining('anti-bot challenge')
      })
    );
    expect(axiosGet).toHaveBeenCalledTimes(1);
  });

  it('keeps a normal empty page as an empty result rather than a transport error', async () => {
    jest.spyOn(axios, 'get').mockResolvedValue({
      status: 200,
      data: '<html><body><p>No matching results</p></body></html>'
    } as any);

    await expect(searcher.search('no results', { maxResults: 1 })).resolves.toEqual([]);
  });

  it('does not cache an unrecognized HTML stub as a successful empty result', async () => {
    jest.spyOn(axios, 'get').mockResolvedValue({
      status: 200,
      data: '<html><body><div>temporary page</div></body></html>'
    } as any);

    await expect(searcher.search('layout drift', { maxResults: 1 })).rejects.toEqual(
      expect.objectContaining({
        name: 'ApiError',
        status: 502,
        message: expect.stringContaining('unrecognized HTML page')
      })
    );
    expect(searcher.getCacheStats().size).toBe(0);
  });

  it('uses an explicit SOCKS proxy without exposing its value in request logs', async () => {
    const proxySearcher = new GoogleScholarSearcher('socks5://127.0.0.1:1080');
    (proxySearcher as any).randomDelay = async () => undefined;
    const axiosGet = jest.spyOn(axios, 'get').mockResolvedValue({
      status: 200,
      data: SCHOLAR_RESULTS_HTML
    } as any);

    await proxySearcher.search('proxy query', { maxResults: 1 });

    const requestConfig = axiosGet.mock.calls[0]?.[1] as any;
    expect(requestConfig.proxy).toBe(false);
    expect(requestConfig.httpAgent).toBeDefined();
    expect(requestConfig.httpsAgent).toBeDefined();
  });

  it('reports an invalid Scholar proxy as a configuration error', async () => {
    const invalidProxySearcher = new GoogleScholarSearcher('ftp://127.0.0.1:1080');
    (invalidProxySearcher as any).randomDelay = async () => undefined;

    await expect(invalidProxySearcher.search('proxy query', { maxResults: 1 })).rejects.toEqual(
      expect.objectContaining({
        name: 'ApiError',
        message: expect.stringContaining('GOOGLE_SCHOLAR_PROXY_URL')
      })
    );
  });

  it('keeps ApiError instances intact for callers and diagnostics', async () => {
    const blocked = new ApiError({
      message: 'Google Scholar returned an anti-bot challenge.',
      status: 400,
      platform: 'google_scholar',
      operation: 'search'
    });
    jest.spyOn(axios, 'get').mockRejectedValue(blocked);

    await expect(searcher.search('blocked query', { maxResults: 1 })).rejects.toBe(blocked);
  });

  it('defaults to the upstream 0.5 requests-per-second limiter', () => {
    expect(searcher.getRateLimiterStatus().requestsPerSecond).toBe(0.5);
  });

  it('reads the bounded Scholar tuning values from the environment', () => {
    process.env.SCHOLAR_RATE_LIMIT_RPS = '1';
    process.env.SCHOLAR_MAX_RETRIES = '0';
    process.env.SCHOLAR_TIMEOUT_MS = '9000';
    const configured = new GoogleScholarSearcher();

    expect(configured.getRateLimiterStatus().requestsPerSecond).toBe(1);
    expect((configured as any).maxRetries).toBe(0);
    expect((configured as any).requestTimeoutMs).toBe(9000);
    configured.dispose();
  });

  it('coordinates the request interval across CLI processes through the cache directory', async () => {
    tempCacheDir = mkdtempSync(join(tmpdir(), 'paper-search-scholar-rate-'));
    process.env.PAPER_SEARCH_CACHE_DIR = tempCacheDir;
    const first = new GoogleScholarSearcher(undefined, { rateLimitRps: 2, maxRetries: 0 });
    const second = new GoogleScholarSearcher(undefined, { rateLimitRps: 2, maxRetries: 0 });
    const secondSleep = jest.spyOn(second as any, 'sleep').mockResolvedValue(undefined);

    await (first as any).randomDelay();
    await (second as any).randomDelay();

    expect(secondSleep).toHaveBeenCalledWith(expect.any(Number));
    expect(secondSleep.mock.calls[0][0]).toBeGreaterThan(0);
    first.dispose();
    second.dispose();
  });
});
