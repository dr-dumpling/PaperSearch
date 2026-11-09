import { describe, it, expect } from '@jest/globals';
import { handleSemanticSnippets } from '../../src/capabilities/body-snippet-search/handler.js';

function result(metadataStatus: 'found' | 'not_found' | 'lookup_failed', snippetKind = 'body') {
  return {
    score: null,
    paper: { corpusId: '1', title: 'T', authors: [], openAccessInfo: {}, url: '', doi: null, pmid: null, year: null, journal: null, metadataStatus },
    snippet: { text: 'x', snippetKind, section: '', snippetOffset: {}, annotations: {} },
    text: 'x',
    source: 'T'
  };
}

async function summary(results: ReturnType<typeof result>[]): Promise<string> {
  const searchers = { semantic: { searchSnippets: async () => results } } as any;
  const response = await handleSemanticSnippets({ query: 'q' } as any, searchers);
  return response.content[0].text.split('\n')[0];
}

describe('handleSemanticSnippets', () => {
  it('says when DOI, year and journal could not be looked up', async () => {
    expect(await summary([result('lookup_failed'), result('found', 'abstract')])).toBe(
      'Found 2 Semantic Scholar snippet(s), including 1 body snippet(s). DOI, year and journal could not be looked up for 1; check them before citing.'
    );
  });

  it('adds nothing when the lookup worked', async () => {
    expect(await summary([result('found'), result('not_found')])).toBe(
      'Found 2 Semantic Scholar snippet(s), including 2 body snippet(s).'
    );
  });
});
