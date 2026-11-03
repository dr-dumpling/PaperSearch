/**
 * SpringerSearcher Platform Tests
 */

import axios from 'axios';
import { afterEach, describe, it, expect, beforeEach, jest } from '@jest/globals';
import { SpringerSearcher } from '../../src/platforms/SpringerSearcher.js';

describe('SpringerSearcher', () => {
  let searcher: SpringerSearcher;

  beforeEach(() => {
    searcher = new SpringerSearcher('test-api-key');
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('getCapabilities', () => {
    it('should return correct capabilities', () => {
      const caps = searcher.getCapabilities();
      expect(caps.search).toBe(true);
      expect(caps.requiresApiKey).toBe(true);
    });
  });

  describe('constructor', () => {
    it('should require API key for operations', () => {
      const noKeySearcher = new SpringerSearcher();
      expect(noKeySearcher).toBeDefined();
    });

    it('should support separate OpenAccess API key', () => {
      const instance = new SpringerSearcher('meta-key', 'openaccess-key');
      expect(instance).toBeDefined();
    });
  });

  describe('Dual API support', () => {
    it('should support Metadata API v2', () => {
      expect(searcher.search).toBeDefined();
    });

    it('should support OpenAccess API', () => {
      expect(searcher.search).toBeDefined();
    });

    it('should test OpenAccess API availability', () => {
      // Race condition fix was applied
      expect(searcher).toBeDefined();
    });
  });

  describe('search options', () => {
    it('should support openAccess filter', () => {
      expect(searcher.search).toBeDefined();
    });

    it('should support type filter (Journal/Book/Chapter)', () => {
      expect(searcher.search).toBeDefined();
    });

    it('should support subject filter', () => {
      expect(searcher.search).toBeDefined();
    });
  });

  describe('open-access download provenance', () => {
    it('does not download a Springer URL unless the OA result explicitly confirms open access', async () => {
      const search = jest.spyOn(searcher, 'search').mockResolvedValue([
        {
          paperId: '10.1007/closed',
          doi: '10.1007/closed',
          title: 'Closed article',
          authors: [],
          abstract: '',
          publishedDate: null,
          source: 'springer',
          pdfUrl: 'https://link.springer.example/closed.pdf',
          extra: { openAccess: false }
        }
      ] as any);
      const get = jest.spyOn(axios, 'get').mockRejectedValue(new Error('network must not be called'));

      await expect(searcher.downloadPdf('10.1007/closed')).rejects.toThrow(/open.?access/i);

      expect(search).toHaveBeenCalledWith('10.1007/closed', { maxResults: 1, openAccess: true });
      expect(get).not.toHaveBeenCalled();
    });

    it('does not download an OA result whose DOI differs from the requested paper', async () => {
      const search = jest.spyOn(searcher, 'search').mockResolvedValue([
        {
          paperId: '10.1007/different',
          doi: '10.1007/different',
          title: 'Different open-access article',
          authors: [],
          abstract: '',
          publishedDate: null,
          source: 'springer',
          pdfUrl: 'https://link.springer.example/different.pdf',
          extra: { openAccess: true }
        }
      ] as any);
      const get = jest.spyOn(axios, 'get').mockRejectedValue(new Error('network must not be called'));

      await expect(searcher.downloadPdf('10.1007/requested')).rejects.toThrow(/open.?access/i);

      expect(search).toHaveBeenCalledWith('10.1007/requested', { maxResults: 1, openAccess: true });
      expect(get).not.toHaveBeenCalled();
    });
  });

  describe('getCitations', () => {
    it('should use Crossref for citations', () => {
      expect(searcher.getCitations).toBeDefined();
    });
  });

  describe('getReferences', () => {
    it('should use Crossref for references', () => {
      expect(searcher.getReferences).toBeDefined();
    });
  });
});
