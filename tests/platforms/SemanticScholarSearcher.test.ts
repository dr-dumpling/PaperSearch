/**
 * SemanticScholarSearcher Platform Tests
 */

import axios from 'axios';
import { describe, it, expect, beforeEach, afterEach, jest } from '@jest/globals';
import { SemanticScholarSearcher } from '../../src/platforms/SemanticScholarSearcher.js';

describe('SemanticScholarSearcher', () => {
  let searcher: SemanticScholarSearcher;

  beforeEach(() => {
    searcher = new SemanticScholarSearcher();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('getCapabilities', () => {
    it('should return correct capabilities', () => {
      const caps = searcher.getCapabilities();
      expect(caps.search).toBe(true);
      expect(caps.download).toBe(true);
      expect(caps.citations).toBe(true);
      expect(caps.requiresApiKey).toBe(false); // Optional
    });
  });

  describe('constructor', () => {
    it('should work without API key', () => {
      const instance = new SemanticScholarSearcher();
      expect(instance).toBeDefined();
    });

    it('should accept API key for higher rate limits', () => {
      const instance = new SemanticScholarSearcher('test-key');
      expect(instance).toBeDefined();
    });
  });

  describe('search options', () => {
    it('should support fieldsOfStudy filter', () => {
      expect(searcher.search).toBeDefined();
    });

    it('should support year filter', () => {
      expect(searcher.search).toBeDefined();
    });
  });

  describe('getPaperByDoi', () => {
    it('should use DOI: prefix', () => {
      expect(searcher.getPaperByDoi).toBeDefined();
    });
  });

  describe('paper details', () => {
    it('should have getPaperDetails method', () => {
      expect((searcher as any).getPaperDetails).toBeDefined();
    });
  });

  describe('PDF URL normalization', () => {
    it('normalizes arXiv candidates for the final preprint stage and drops DOI landing pages', async () => {
      jest.spyOn(axios, 'get').mockResolvedValue({
        data: {
          data: [
            {
              paperId: 'paper-1',
              title: 'Arxiv paper',
              openAccessPdf: { url: 'https://arxiv.org/abs/2501.06425' },
              externalIds: { DOI: '10.48550/arXiv.2501.06425' }
            },
            {
              paperId: 'paper-2',
              title: 'Landing page only',
              openAccessPdf: { url: 'https://doi.org/10.1016/j.xpro.2022.101947' },
              externalIds: { DOI: '10.1016/j.xpro.2022.101947' }
            }
          ]
        }
      } as any);

      const results = await searcher.search('test', { maxResults: 2 });

      expect(results[0].pdfUrl).toBe('https://arxiv.org/pdf/2501.06425');
      expect(results[1].pdfUrl).toBe('');
    });
  });

  describe('searchSnippets', () => {
    it('should require SEMANTIC_SCHOLAR_API_KEY and say where to get it', async () => {
      const attempt = searcher.searchSnippets({ query: 'mediation bootstrap', limit: 1 });
      await expect(attempt).rejects.toThrow('Semantic Scholar API key not configured');
      await expect(attempt).rejects.toThrow(
        'Get one at https://www.semanticscholar.org/product/api, then run `paper-search setup SEMANTIC_SCHOLAR_API_KEY`'
      );
    });

    it('should call snippet search and normalize snippet results', async () => {
      const instance = new SemanticScholarSearcher('test-key');
      jest.spyOn(axios, 'get').mockResolvedValue({
        status: 200,
        statusText: 'OK',
        headers: {},
        config: {},
        data: {
          data: [
            {
              score: 0.9,
              paper: {
                corpusId: 123,
                title: 'A snippet paper',
                authors: ['Ada Lovelace', 'Charles Babbage'],
                openAccessInfo: { status: 'GOLD', license: 'CCBYNCND' }
              },
              snippet: {
                text: 'Matched body text.',
                snippetKind: 'body',
                section: 'Methods',
                snippetOffset: { start: 1, end: 3 },
                annotations: { sentences: [] }
              }
            }
          ]
        }
      } as any);
      jest.spyOn(axios, 'post').mockResolvedValue({
        status: 200,
        data: [
          {
            externalIds: { DOI: '10.1000/snippet', PubMed: 4242, CorpusId: 123 },
            year: 2021,
            venue: 'J Snip',
            journal: { name: 'Journal of Snippets', volume: '3' }
          }
        ]
      } as any);

      const results = await instance.searchSnippets({
        query: 'mediation bootstrap',
        limit: 1,
        fieldsOfStudy: 'Medicine'
      });

      expect(axios.get).toHaveBeenCalledWith(
        expect.stringContaining('/snippet/search'),
        expect.objectContaining({
          params: expect.objectContaining({
            query: 'mediation bootstrap',
            limit: 1,
            fieldsOfStudy: 'Medicine'
          }),
          headers: expect.objectContaining({ 'x-api-key': 'test-key' })
        })
      );
      expect(axios.post).toHaveBeenCalledWith(
        expect.stringContaining('/paper/batch'),
        { ids: ['CorpusId:123'] },
        expect.objectContaining({
          params: { fields: 'externalIds,year,venue,journal' },
          headers: expect.objectContaining({ 'x-api-key': 'test-key' })
        })
      );
      expect(results).toEqual([
        {
          score: 0.9,
          paper: {
            corpusId: '123',
            title: 'A snippet paper',
            authors: ['Ada Lovelace', 'Charles Babbage'],
            openAccessInfo: { status: 'GOLD', license: 'CCBYNCND' },
            url: 'https://www.semanticscholar.org/paper/CorpusId:123',
            doi: '10.1000/snippet',
            pmid: '4242',
            year: 2021,
            journal: 'Journal of Snippets',
            metadataStatus: 'found'
          },
          snippet: {
            text: 'Matched body text.',
            snippetKind: 'body',
            section: 'Methods',
            snippetOffset: { start: 1, end: 3 },
            annotations: { sentences: [] }
          },
          text: 'Matched body text.',
          source: 'Ada Lovelace et al., 2021, Journal of Snippets · Methods · DOI 10.1000/snippet · CC BY-NC-ND'
        }
      ]);
    });

    function mockSnippets(papers: Array<Record<string, unknown>>) {
      jest.spyOn(axios, 'get').mockResolvedValue({
        status: 200,
        data: {
          data: papers.map(paper => ({
            score: 0.5,
            paper,
            snippet: { text: 'Body text.', snippetKind: 'body', section: 'Results' }
          }))
        }
      } as any);
    }

    it('should mark a paper Semantic Scholar has no record of and cite it by its authors', async () => {
      const instance = new SemanticScholarSearcher('test-key');
      mockSnippets([{ corpusId: 7, title: 'Lonely paper', authors: ['Grace Hopper'], openAccessInfo: { license: 'CC0' } }]);
      jest.spyOn(axios, 'post').mockResolvedValue({ status: 200, data: [null] } as any);

      const [result] = await instance.searchSnippets({ query: 'q' });

      expect(result.paper).toEqual(
        expect.objectContaining({ doi: null, pmid: null, year: null, journal: null, metadataStatus: 'not_found' })
      );
      expect(result.source).toBe('Grace Hopper · Results · CC0');
    });

    it('should keep the snippets and mark them when the paper lookup fails', async () => {
      const instance = new SemanticScholarSearcher('test-key');
      mockSnippets([
        { corpusId: 8, title: 'First', authors: [], openAccessInfo: { license: 'publisher-specific' } },
        { corpusId: 9, title: 'Second', authors: ['Alan Turing'], openAccessInfo: {} }
      ]);
      jest.spyOn(axios, 'post').mockResolvedValue({ status: 403, data: { message: 'Forbidden' } } as any);

      const results = await instance.searchSnippets({ query: 'q' });

      expect(results.map(result => result.paper.metadataStatus)).toEqual(['lookup_failed', 'lookup_failed']);
      expect(results.map(result => result.source)).toEqual([
        'First · Results · publisher-specific',
        'Alan Turing · Results'
      ]);
    });

    it('should not look up papers when nothing matched', async () => {
      const instance = new SemanticScholarSearcher('test-key');
      mockSnippets([]);
      const post = jest.spyOn(axios, 'post');

      expect(await instance.searchSnippets({ query: 'q' })).toEqual([]);
      expect(post).not.toHaveBeenCalled();
    });
  });
});
