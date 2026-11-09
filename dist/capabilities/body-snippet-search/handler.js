import { searchBodySnippets } from './service.js';
function jsonTextResponse(text) {
    return {
        content: [
            {
                type: 'text',
                text
            }
        ]
    };
}
export async function handleSemanticSnippets(args, searchers) {
    const results = await searchBodySnippets(searchers, args);
    const bodyCount = results.filter(result => result.snippet.snippetKind === 'body').length;
    const lookupFailed = results.filter(result => result.paper.metadataStatus === 'lookup_failed').length;
    const note = lookupFailed
        ? ` DOI, year and journal could not be looked up for ${lookupFailed}; check them before citing.`
        : '';
    return jsonTextResponse(`Found ${results.length} Semantic Scholar snippet(s), including ${bodyCount} body snippet(s).${note}\n\n${JSON.stringify(results, null, 2)}`);
}
//# sourceMappingURL=handler.js.map