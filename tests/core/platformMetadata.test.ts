import { describe, expect, it } from '@jest/globals';
import {
  getCapabilityProfileConfigKeysBySource,
  getCapabilityProfileSources,
  getDefaultAllSources,
  getDoiLookupSources,
  getGenericPlatformToolDescriptors,
  getGenericSearchToolNames,
  getGenericSearchToolPlatform,
  getNoKeySources,
  getPlatformMetadata,
  getPlatformToolDescriptors,
  getRepositoryFallbackSources,
  isKnownSearchPlatform,
  resolvePlatformId
} from '../../src/registry/platformMetadata.js';

describe('platformMetadata', () => {
  it('resolves platform aliases without adding duplicate platform identities', () => {
    expect(resolvePlatformId('springerlink')).toBe('springer');
    expect(resolvePlatformId('google_scholar')).toBe('googlescholar');
    expect(resolvePlatformId('scholar')).toBe('googlescholar');
    expect(resolvePlatformId('wos')).toBe('webofscience');
    expect(resolvePlatformId('pubmed_central')).toBe('pmc');
    expect(resolvePlatformId('europe_pmc')).toBe('europepmc');
  });

  it('recognizes registered search platforms and excludes the removed Wiley downloader', () => {
    expect(isKnownSearchPlatform('dblp')).toBe(true);
    expect(isKnownSearchPlatform('ieee')).toBe(true);
    expect(isKnownSearchPlatform('acm')).toBe(true);
    expect(isKnownSearchPlatform('usenix')).toBe(true);
    expect(isKnownSearchPlatform('openreview')).toBe(true);
    expect(isKnownSearchPlatform('springerlink')).toBe(true);
    expect(isKnownSearchPlatform('wiley')).toBe(false);
    expect(getPlatformMetadata('wiley')).toBeUndefined();
  });

  it('maps generic direct search tools to platforms', () => {
    expect(getGenericSearchToolPlatform('search_dblp')).toBe('dblp');
    expect(getGenericSearchToolPlatform('search_ieee')).toBe('ieee');
    expect(getGenericSearchToolPlatform('search_acm')).toBe('acm');
    expect(getGenericSearchToolPlatform('search_usenix')).toBe('usenix');
    expect(getGenericSearchToolPlatform('search_openreview')).toBe('openreview');
    expect(getGenericSearchToolPlatform('search_springerlink')).toBe('springerlink');
  });

  it('keeps aliases and removed download-only adapters out of default all sources', () => {
    expect(getDefaultAllSources()).not.toEqual(
      expect.arrayContaining([
        'wos',
        'scholar',
        'google_scholar',
        'springerlink',
        'pubmed_central',
        'europe_pmc',
        'wiley'
      ])
    );
    expect(getDefaultAllSources()).not.toContain('googlescholar');
    expect(getDefaultAllSources()).not.toContain('wiley');
  });

  it('defines a bounded no-key metadata bundle', () => {
    expect(getNoKeySources()).toEqual([
      'crossref',
      'pubmed',
      'europepmc',
      'arxiv',
      'openreview'
    ]);
    expect(getNoKeySources()).not.toContain('googlescholar');
    expect(getNoKeySources()).not.toContain('semantic');
    expect(getNoKeySources()).not.toContain('openalex');
  });

  it('keeps Google Scholar explicitly searchable while excluding it from high-frequency all-source runs', () => {
    expect(getPlatformMetadata('googlescholar')).toEqual(
      expect.objectContaining({
        id: 'googlescholar',
        defaultInAll: false,
        optionalConfigKeys: expect.arrayContaining([
          ['GOOGLE_SCHOLAR_PROXY_URL'],
          ['SCHOLAR_RATE_LIMIT_RPS'],
          ['SCHOLAR_MAX_RETRIES'],
          ['SCHOLAR_TIMEOUT_MS']
        ])
      })
    );
    expect(getDefaultAllSources()).not.toContain('googlescholar');
  });

  it('derives repository fallback sources without changing order or tier boundaries', () => {
    expect(getRepositoryFallbackSources()).toEqual(['pmc', 'europepmc', 'core', 'openaire']);
    expect(getRepositoryFallbackSources()).not.toEqual(expect.arrayContaining(['unpaywall', 'scihub']));
  });

  it('derives DOI lookup sources without silently adding unsupported platforms', () => {
    expect(getDoiLookupSources()).toEqual([
      'crossref',
      'openalex',
      'unpaywall',
      'pubmed',
      'pmc',
      'europepmc',
      'core',
      'webofscience',
      'arxiv'
    ]);
    expect(getDoiLookupSources()).not.toEqual(expect.arrayContaining(['semantic', 'wiley']));
  });

  it('derives metadata and open-access profile groups without local authorized sources', () => {
    expect(getCapabilityProfileSources('metadata_free')).toEqual([
      'crossref',
      'openalex',
      'pubmed',
      'pmc',
      'europepmc',
      'arxiv',
      'biorxiv',
      'medrxiv',
      'semantic',
      'iacr',
      'core',
      'openaire',
      'googlescholar',
      'dblp',
      'acm',
      'usenix',
      'openreview'
    ]);
    expect(getCapabilityProfileSources('metadata_entitled')).toEqual([
      'webofscience',
      'sciencedirect',
      'springer',
      'scopus',
      'ieee'
    ]);
    expect(getCapabilityProfileSources('pdf_open_access')).toEqual([
      'arxiv',
      'biorxiv',
      'medrxiv',
      'pmc',
      'europepmc',
      'core',
      'openaire',
      'unpaywall',
      'openalex_oa_metadata',
      'semantic_open_access_pdf',
      'springer_open_access',
      'sciencedirect_open_access',
      'scopus_open_access_metadata',
      'iacr'
    ]);
    expect(getCapabilityProfileSources('pdf_scihub')).toEqual(['scihub']);
  });

  it('derives publisher keys for metadata only', () => {
    expect(getCapabilityProfileConfigKeysBySource(['metadata_entitled'])).toEqual({
      webofscience: ['WOS_API_KEY'],
      sciencedirect: ['ELSEVIER_API_KEY'],
      springer: ['SPRINGER_API_KEY'],
      scopus: ['ELSEVIER_API_KEY'],
      ieee: ['IEEE_API_KEY']
    });
  });

  it('separates direct platform descriptors from generic descriptors', () => {
    expect(getPlatformToolDescriptors().map(platform => platform.toolName)).toEqual([
      'search_dblp',
      'search_ieee',
      'search_acm',
      'search_usenix',
      'search_openreview'
    ]);
    expect(getGenericPlatformToolDescriptors().map(platform => platform.toolName)).toEqual([
      'search_dblp',
      'search_ieee',
      'search_acm',
      'search_usenix',
      'search_openreview'
    ]);
    expect(getGenericSearchToolNames()).toEqual([
      'search_dblp',
      'search_ieee',
      'search_acm',
      'search_usenix',
      'search_openreview',
      'search_springerlink'
    ]);
    expect(getGenericSearchToolNames()).not.toContain('search_wiley');
  });
});
