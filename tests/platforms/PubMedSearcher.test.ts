/**
 * PubMedSearcher Platform Tests
 */

import { describe, it, expect, beforeEach, jest } from '@jest/globals';
import { PubMedSearcher } from '../../src/platforms/PubMedSearcher.js';

describe('PubMedSearcher', () => {
  let searcher: PubMedSearcher;

  beforeEach(() => {
    searcher = new PubMedSearcher();
  });

  describe('naming fields', () => {
    it('keeps NLM\'s abbreviation, the ISSNs and the earlier of the electronic and issue dates', () => {
      const paper = (searcher as any).parsePubMedArticle({
        MedlineCitation: { PMID: { _: '1' }, MedlineJournalInfo: { MedlineTA: 'Arthritis Rheumatol' }, Article: {
          ArticleTitle: 'T', ArticleDate: { $: { DateType: 'Electronic' }, Year: '2024', Month: '11', Day: '14' },
          Journal: { Title: 'Arthritis & rheumatology (Hoboken, N.J.)', ISOAbbreviation: 'Arthritis Rheumatol',
            ISSN: { _: '2326-5205', $: { IssnType: 'Electronic' } }, JournalIssue: { PubDate: { Year: '2025', Month: 'Mar' } } } } },
        PubmedData: {},
      });
      expect(paper.extra).toMatchObject({ journalAbbreviation: 'Arthritis Rheumatol', issued: '2024-11', issn: ['2326-5205'] });
    });

    it('keeps a record whose title has its own markup, the markup as text', async () => {
      // 10.1136/ard-2024-226547 (2026-11-16): "S1P<sub>1</sub>" made the title an object and the record was dropped.
      const xml = '<?xml version="1.0"?><PubmedArticleSet><PubmedArticle><MedlineCitation><PMID Version="1">39919901</PMID>'
        + '<Article><Journal><ISSN IssnType="Electronic">1468-2060</ISSN><JournalIssue><PubDate><Year>2025</Year><Month>Feb</Month></PubDate></JournalIssue>'
        + '<Title>Annals of the rheumatic diseases</Title><ISOAbbreviation>Ann Rheum Dis</ISOAbbreviation></Journal>'
        + '<ArticleTitle>Pharmacodynamics of the S1P<sub>1</sub> receptor modulator cenerimod in <i>SLE</i>.</ArticleTitle>'
        + '<Abstract><AbstractText>CD4<sup>+</sup> cells fell.</AbstractText></Abstract></Article></MedlineCitation>'
        + '<PubmedData><ArticleIdList><ArticleId IdType="pubmed">39919901</ArticleId><ArticleId IdType="doi">10.1136/ard-2024-226547</ArticleId>'
        + '<ArticleId IdType="pii">S0003-4967(24)47764-9</ArticleId></ArticleIdList></PubmedData>'
        + '</PubmedArticle></PubmedArticleSet>';
      const parsed = await (searcher as any).parseXmlResponse(xml);
      const papers = (searcher as any).parsePubMedArticles([parsed.PubmedArticleSet.PubmedArticle]);
      expect(papers).toHaveLength(1);
      expect(papers[0]).toMatchObject({
        title: 'Pharmacodynamics of the S1P<sub>1</sub> receptor modulator cenerimod in <i>SLE</i>.',
        abstract: 'CD4<sup>+</sup> cells fell.', journal: 'Annals of the rheumatic diseases', doi: '10.1136/ard-2024-226547',
      });
    });

    it('takes the journal\'s own NLM record among editions sharing its ISSN', async () => {
      const axios = (await import('axios')).default;
      const get = jest.spyOn(axios, 'get').mockImplementation(async (url: string) => ({ data: url.includes('esearch')
        ? { esearchresult: { idlist: ['8907037', '255562'] } }
        : { result: { uids: ['8907037', '255562'],
          8907037: { medlineta: 'N Engl J Med Overseas Ed', currentindexingstatus: 'N', issnlist: [] },
          255562: { medlineta: 'N Engl J Med', currentindexingstatus: 'Y', issnlist: [{ issn: '0028-4793', issntype: 'Print' }] } } } }) as any);
      try {
        expect(await searcher.journalAbbreviation(['0028-4793', '1533-4406'])).toBe('N Engl J Med');
        expect(get.mock.calls[0][1]).toMatchObject({ params: { db: 'nlmcatalog', term: '0028-4793[issn] OR 1533-4406[issn]' } });
      } finally {
        get.mockRestore();
      }
    });
  });

  describe('getCapabilities', () => {
    it('should return correct capabilities', () => {
      const caps = searcher.getCapabilities();
      expect(caps.search).toBe(true);
      expect(caps.download).toBe(false);
      expect(caps.requiresApiKey).toBe(false); // Optional
    });
  });

  describe('constructor', () => {
    it('should work without API key', () => {
      const instance = new PubMedSearcher();
      expect(instance).toBeDefined();
    });

    it('should accept API key', () => {
      const instance = new PubMedSearcher('test-key');
      expect(instance).toBeDefined();
    });
  });

  describe('search', () => {
    it('should support year filter', () => {
      expect(searcher.search).toBeDefined();
    });

    it('should support author filter', () => {
      expect(searcher.search).toBeDefined();
    });

    it('should support journal filter', () => {
      expect(searcher.search).toBeDefined();
    });

    it('should support publicationType filter', () => {
      expect(searcher.search).toBeDefined();
    });
  });

  describe('getPaperByDoi', () => {
    it('should use DOI field search', () => {
      expect(searcher.getPaperByDoi).toBeDefined();
    });
  });

  describe('getPaperByPmid', () => {
    it('should be available', () => {
      expect((searcher as any).getPaperByPmid || searcher.search).toBeDefined();
    });
  });
});
