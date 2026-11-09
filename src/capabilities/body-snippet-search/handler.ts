import type { Searchers } from '../../core/searchers.js';
import { searchBodySnippets } from './service.js';
import type { SemanticSnippetSearchArgs } from './types.js';

function jsonTextResponse(text: string) {
  return {
    content: [
      {
        type: 'text' as const,
        text
      }
    ]
  };
}

export async function handleSemanticSnippets(args: SemanticSnippetSearchArgs, searchers: Searchers) {
  const results = await searchBodySnippets(searchers, args);
  const bodyCount = results.filter(result => result.snippet.snippetKind === 'body').length;
  const lookupFailed = results.filter(result => result.paper.metadataStatus === 'lookup_failed').length;
  const note = lookupFailed
    ? ` DOI, year and journal could not be looked up for ${lookupFailed}; check them before citing.`
    : '';

  return jsonTextResponse(
    `Found ${results.length} Semantic Scholar snippet(s), including ${bodyCount} body snippet(s).${note}\n\n${JSON.stringify(
      results,
      null,
      2
    )}`
  );
}
