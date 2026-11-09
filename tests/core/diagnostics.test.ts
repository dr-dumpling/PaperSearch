import { describe, it, expect, beforeEach } from '@jest/globals';
import {
  diagnoseError,
  diagnoseToolResult,
  getRequirementStatus
} from '../../src/core/diagnostics.js';

const ORIGINAL_ENV = { ...process.env };

describe('diagnostics', () => {
  beforeEach(() => {
    process.env = { ...ORIGINAL_ENV };
    delete process.env.ELSEVIER_API_KEY;
    delete process.env.SPRINGER_API_KEY;
    delete process.env.SEMANTIC_SCHOLAR_API_KEY;
    delete process.env.WOS_API_KEY;
    delete process.env.IEEE_API_KEY;
    delete process.env.EASYSCHOLAR_KEY;
    delete process.env.WILEY_TDM_TOKEN;
  });

  it('should report key-dependent capabilities and configuration state', () => {
    process.env.ELSEVIER_API_KEY = 'test-key';

    const requirements = getRequirementStatus();
    const scopus = requirements.find(item => item.id === 'scopus');
    const springer = requirements.find(item => item.id === 'springer');

    expect(scopus?.configured).toBe(true);
    expect(scopus?.keyGroups).toEqual([['ELSEVIER_API_KEY']]);
    expect(springer?.configured).toBe(false);
    expect(springer?.missingGroups).toEqual([['SPRINGER_API_KEY']]);
    const ieee = requirements.find(item => item.id === 'ieee');
    expect(ieee?.configured).toBe(false);
    expect(ieee?.missingGroups).toEqual([['IEEE_API_KEY']]);

    const easyscholar = requirements.find(item => item.id === 'easyscholar');
    expect(easyscholar?.configured).toBe(false);
    expect(easyscholar?.missingGroups).toEqual([['EASYSCHOLAR_KEY']]);
  });

  it('keeps Elsevier requirements metadata-only and removes Wiley TDM diagnostics', () => {
    process.env.ELSEVIER_API_KEY = 'test-key';
    process.env.WILEY_TDM_TOKEN = 'legacy-token';

    const requirements = getRequirementStatus();
    const sciencedirect = requirements.find(item => item.id === 'sciencedirect');
    const scopus = requirements.find(item => item.id === 'scopus');

    expect(requirements.map(item => item.id)).not.toContain('wiley');
    expect(sciencedirect).toEqual(
      expect.objectContaining({
        configured: true,
        capability: expect.stringMatching(/metadata/i),
        keyGroups: [['ELSEVIER_API_KEY']]
      })
    );
    expect(scopus).toEqual(
      expect.objectContaining({
        configured: true,
        capability: expect.stringMatching(/metadata/i),
        keyGroups: [['ELSEVIER_API_KEY']]
      })
    );
    expect(sciencedirect?.tools).not.toContain('download_paper');
    expect(scopus?.tools).not.toContain('download_paper');
  });

  it('should report EasyScholar journal metrics as configured when the canonical key exists', () => {
    process.env.EASYSCHOLAR_KEY = 'test-key';

    const requirements = getRequirementStatus();
    const easyscholar = requirements.find(item => item.id === 'easyscholar');

    expect(easyscholar?.configured).toBe(true);
    expect(easyscholar?.configuredGroups).toEqual([['EASYSCHOLAR_KEY']]);
    expect(easyscholar?.tools).toContain('query_journal_metrics');
  });

  it('should diagnose provider product permission failures', () => {
    process.env.ELSEVIER_API_KEY = 'test-key';

    const diagnostic = diagnoseError(
      {
        status: 401,
        message: 'sciencedirect: API key was accepted but does not have permission for this API product, view, or resource.'
      },
      { tool: 'search_papers', platform: 'sciencedirect' }
    );

    expect(diagnostic?.category).toBe('permission');
    expect(diagnostic?.platform).toBe('sciencedirect');
    expect(diagnostic?.summary).toContain('authenticated the key');
    expect(diagnostic?.actions.join('\n')).toContain('ScienceDirect Search API');
  });

  it('should diagnose missing required configuration', () => {
    const diagnostic = diagnoseError(
      { message: 'Web of Science API key not configured. Please set WOS_API_KEY environment variable.' },
      { tool: 'search_webofscience' }
    );

    expect(diagnostic?.category).toBe('missing_config');
    expect(diagnostic?.relatedConfigKeys).toContain('WOS_API_KEY');
    expect(diagnostic?.actions.join('\n')).toContain('WOS_API_KEY');
  });

  it('should tell where to get a missing snippet search key', () => {
    delete process.env.SEMANTIC_SCHOLAR_API_KEY;
    const diagnostic = diagnoseError(
      { message: 'Semantic Scholar API key not configured; search_semantic_snippets needs SEMANTIC_SCHOLAR_API_KEY.' },
      { tool: 'search_semantic_snippets' }
    );

    expect(diagnostic?.category).toBe('missing_config');
    expect(diagnostic?.relatedConfigKeys).toContain('SEMANTIC_SCHOLAR_API_KEY');
    expect(diagnostic?.actions).toContain(
      'SEMANTIC_SCHOLAR_API_KEY: Get one at https://www.semanticscholar.org/product/api, then run `paper-search setup SEMANTIC_SCHOLAR_API_KEY` in your own terminal; with school subscription downloads installed, `paper-search settings SEMANTIC_SCHOLAR_API_KEY` opens a window for it instead.'
    );
  });

  it('should diagnose missing IEEE API key for generic direct tools', () => {
    const diagnostic = diagnoseError(
      { message: 'IEEE API key is required. Please set IEEE_API_KEY environment variable.' },
      { tool: 'search_ieee' }
    );

    expect(diagnostic?.category).toBe('missing_config');
    expect(diagnostic?.platform).toBe('ieee');
    expect(diagnostic?.relatedConfigKeys).toContain('IEEE_API_KEY');
  });

  it('should treat configured but rejected keys as invalid keys', () => {
    process.env.SPRINGER_API_KEY = 'test-key';

    const diagnostic = diagnoseError(
      { status: 401, message: 'springer: Invalid or missing API key. Please check your credentials.' },
      { tool: 'search_papers', platform: 'springer' }
    );

    expect(diagnostic?.category).toBe('invalid_key');
    expect(diagnostic?.summary).toContain('rejected the API key');
  });

  it('should diagnose provider timeouts as skipped source warnings', () => {
    const diagnostic = diagnoseError(
      { message: 'openalex DOI lookup timed out after 15000ms' },
      { tool: 'get_paper_by_doi', platform: 'openalex' }
    );

    expect(diagnostic?.category).toBe('timeout');
    expect(diagnostic?.severity).toBe('warning');
    expect(diagnostic?.summary).toContain('was skipped');
  });

  it('should explain Google Scholar anti-bot challenges and proxy routing', () => {
    const diagnostic = diagnoseError(
      {
        status: 429,
        message:
          'Google Scholar returned an anti-bot challenge (CAPTCHA or unusual-traffic page). Wait before retrying.'
      },
      { tool: 'search_google_scholar' }
    );

    expect(diagnostic?.category).toBe('rate_limit');
    expect(diagnostic?.platform).toBe('googlescholar');
    expect(diagnostic?.summary).toContain('anti-bot challenge');
    expect(diagnostic?.actions.join('\n')).toContain('GOOGLE_SCHOLAR_PROXY_URL');
    expect(diagnostic?.relatedConfigKeys).toContain('GOOGLE_SCHOLAR_PROXY_URL');
  });

  it('should diagnose zero results when key is configured', () => {
    process.env.SEMANTIC_SCHOLAR_API_KEY = 'test-key';

    const diagnostic = diagnoseToolResult({
      tool: 'search_semantic_snippets',
      data: [],
      args: { query: 'very narrow method query' }
    });

    expect(diagnostic?.category).toBe('zero_results');
    expect(diagnostic?.severity).toBe('info');
    expect(diagnostic?.relatedConfigKeys).toContain('SEMANTIC_SCHOLAR_API_KEY');
    expect(diagnostic?.actions.join('\n')).toContain('broader');
  });

  it('should diagnose multi-source partial failures', () => {
    const diagnostic = diagnoseToolResult({
      tool: 'search_papers',
      data: {
        query: 'test',
        sources_requested: 'crossref,sciencedirect',
        sources_used: ['crossref', 'sciencedirect'],
        source_results: { crossref: 1, sciencedirect: 0 },
        errors: {
          sciencedirect:
            'sciencedirect: API key was accepted but does not have permission for this API product, view, or resource.'
        },
        total: 1,
        raw_total: 1,
        papers: []
      }
    });

    expect(diagnostic?.category).toBe('partial_failure');
    expect(diagnostic?.likelyCauses.join('\n')).toContain('sciencedirect');
    expect(diagnostic?.actions.join('\n')).toContain('provider-specific messages');
  });
});
