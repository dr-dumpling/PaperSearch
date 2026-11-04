/**
 * ArxivSearcher Platform Tests
 */

import axios from 'axios';
import { describe, it, expect, beforeEach, afterEach, jest } from '@jest/globals';
import { ArxivSearcher } from '../../src/platforms/ArxivSearcher.js';

describe('ArxivSearcher', () => {
  let searcher: ArxivSearcher;

  beforeEach(() => {
    searcher = new ArxivSearcher();
  });

  describe('getCapabilities', () => {
    it('should return correct capabilities', () => {
      const caps = searcher.getCapabilities();
      expect(caps.search).toBe(true);
      expect(caps.download).toBe(true);
      expect(caps.fullText).toBe(false);
      expect(caps.requiresApiKey).toBe(false);
    });
  });

  describe('search', () => {
    it('includes category and author filters in the API query', () => {
      const query = (searcher as any).buildSearchQuery('transformer', {category: 'cs.CL', author: 'Vaswani'});
      expect(query).toContain('cat:cs.CL'); expect(query).toContain('au:"Vaswani"');
    });



    it('should normalize plain language queries to arXiv field syntax', () => {
      const normalized = (searcher as any).normalizeSearchQuery('llm large language model');

      expect(normalized).toBe('all:llm AND all:large AND all:language AND all:model');
    });

    it('should preserve advanced arXiv query syntax', () => {
      const advanced = 'ti:"large language model" AND cat:cs.CL';

      expect((searcher as any).normalizeSearchQuery(advanced)).toBe(advanced);
    });

    it('should cap arXiv result count to the API-safe limit', () => {
      expect((searcher as any).normalizeMaxResults(undefined)).toBe(10);
      expect((searcher as any).normalizeMaxResults(0)).toBe(1);
      expect((searcher as any).normalizeMaxResults(250)).toBe(25);
      expect((searcher as any).normalizeMaxResults(7.8)).toBe(7);
    });

    it('should identify arXiv timeout errors', () => {
      expect((searcher as any).isTimeoutError({ code: 'ECONNABORTED' })).toBe(true);
      expect((searcher as any).isTimeoutError({ code: 'ETIMEDOUT' })).toBe(true);
      expect((searcher as any).isTimeoutError(new Error('timeout of 30000ms exceeded'))).toBe(true);
      expect((searcher as any).isTimeoutError(new Error('bad request'))).toBe(false);
    });

    it('should fall back on arXiv rate limits and timeout-like errors', () => {
      expect((searcher as any).shouldUseWebFallback({ response: { status: 429 } })).toBe(true);
      expect((searcher as any).shouldUseWebFallback({ response: { status: 503 } })).toBe(true);
      expect((searcher as any).shouldUseWebFallback(new Error('timed out'))).toBe(true);
      expect((searcher as any).shouldUseWebFallback({ response: { status: 400 } })).toBe(false);
    });

    it('should fall back while the arXiv Export API is cooling down', () => {
      const error = (searcher as any).createArxivCooldownError(30000);

      expect((error as any).status).toBe(429);
      expect((searcher as any).shouldUseWebFallback(error)).toBe(true);
    });

    it('should parse arXiv web search fallback results', () => {
      const html = `
        <li class="arxiv-result">
          <p class="list-title is-inline-block">
            <a href="https://arxiv.org/abs/2605.08083">arXiv:2605.08083</a>
            <span>[<a href="https://arxiv.org/pdf/2605.08083">pdf</a>]</span>
          </p>
          <div class="tags"><span class="tag">cs.CL</span></div>
          <p class="title is-5 mathjax">LLMs Improving LLMs</p>
          <p class="authors">
            <span>Authors:</span>
            <a>Tong Zheng</a>, <a>Haolin Liu</a>
          </p>
          <p class="abstract mathjax">
            <span class="abstract-full">A fallback abstract. <a>Less</a></span>
          </p>
          <p class="is-size-7"><span>Submitted</span> 8 May, 2026;</p>
        </li>
      `;

      const results = (searcher as any).parseWebSearchResponse(html);

      expect(results).toHaveLength(1);
      expect(results[0].paperId).toBe('2605.08083');
      expect(results[0].title).toBe('LLMs Improving LLMs');
      expect(results[0].authors).toEqual(['Tong Zheng', 'Haolin Liu']);
      expect(results[0].abstract).toBe('A fallback abstract.');
      expect(results[0].pdfUrl).toBe('https://arxiv.org/pdf/2605.08083');
      expect(results[0].categories).toEqual(['cs.CL']);
      expect(results[0].extra.fallback).toBe('arxiv_web_search');
    });
  });

});

describe('arXiv publication metadata', () => {
  afterEach(() => { jest.restoreAllMocks(); });
  const atom = (id: string, doi: string) => `<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"><entry><id>http://arxiv.org/abs/${id}</id><title>Example publication</title><summary>Abstract</summary><author><name>A Author</name></author><published>2020-01-01T00:00:00Z</published><updated>2021-01-01T00:00:00Z</updated><arxiv:doi>${doi}</arxiv:doi><arxiv:journal_ref>Journal 1 (2021)</arxiv:journal_ref></entry></feed>`;
  it('matches publication DOI exactly, not a search hit mentioning another article', async () => {
    const a = new ArxivSearcher() as any;
    jest.spyOn(a.rateLimiter, 'waitForPermission').mockResolvedValue(undefined);
    jest.spyOn(a, 'waitForGlobalExportApiSlot').mockResolvedValue(undefined);
    jest.spyOn(a.cache, 'get').mockReturnValue(undefined);
    const get = jest.spyOn(axios, 'get').mockResolvedValue({data: atom('1706.03762v7', '10.1000/other')});
    expect(await a.getPaperByDoi('10.1000/requested')).toBeNull();
    get.mockResolvedValue({data: atom('1706.03762v7', '10.1000/requested')});
    expect(await a.getPaperByDoi('10.1000/requested')).toMatchObject({doi: '10.1000/requested'});
    expect(get.mock.calls.at(-1)![1]?.params).toEqual({search_query: 'all:"10.1000/requested"', max_results: 10});
  });
  it('preserves DOI spelling for the API while matching returned DOI case-insensitively', async () => {
    const a = new ArxivSearcher() as any;
    jest.spyOn(a.rateLimiter, 'waitForPermission').mockResolvedValue(undefined);
    jest.spyOn(a, 'waitForGlobalExportApiSlot').mockResolvedValue(undefined);
    const get = jest.spyOn(axios, 'get').mockResolvedValue({data: atom('1602.03837v1', '10.1103/PhysRevLett.116.061102')});
    expect(await a.getPaperByDoi('https://doi.org/10.1103/PhysRevLett.116.061102')).toMatchObject({paperId: '1602.03837v1'});
    expect(get.mock.calls[0][1]?.params.search_query).toBe('all:"10.1103/PhysRevLett.116.061102"');
  });
  it('keeps the old ID category and linked publication DOI distinct from version', async () => {
    const result = await (new ArxivSearcher() as any).parseSearchResponse(atom('hep-th/9901001v2', '10.1000/formal'));
    expect(result[0]).toMatchObject({paperId: 'hep-th/9901001v2', doi: '10.1000/formal', pdfUrl: 'https://arxiv.org/pdf/hep-th/9901001v2', extra: {version: 'preprint', publishedDoi: '10.1000/formal', journalRef: 'Journal 1 (2021)'}});
  });
  it('does not treat an arXiv DOI as evidence of publication', async () => {
    const result = await (new ArxivSearcher() as any).parseSearchResponse(atom('1706.03762v7', '10.48550/arXiv.1706.03762'));
    expect(result[0].doi).toBe(''); expect(result[0].extra.publishedDoi).toBeUndefined();
  });
  it('distinguishes a valid empty result from malformed upstream data', async () => {
    const searcher = new ArxivSearcher() as any;
    expect(await searcher.parseSearchResponse('<feed xmlns="http://www.w3.org/2005/Atom"/>')).toEqual([]);
    await expect(searcher.parseSearchResponse('<html>broken')).rejects.toThrow('Invalid arXiv response');
  });
  it('extracts a publication DOI from the HTML search fallback', () => {
    const result = (new ArxivSearcher() as any).parseWebSearchResponse('<li class="arxiv-result"><p class="list-title"><a href="https://arxiv.org/abs/1706.03762">ID</a></p><p class="title">Title</p><p class="journal-ref">Journal</p><a href="https://doi.org/10.1000/formal">DOI</a></li>');
    expect(result[0]).toMatchObject({doi: '10.1000/formal', extra: {version: 'preprint', publishedDoi: '10.1000/formal'}});
  });
});
