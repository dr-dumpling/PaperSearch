/**
 * First-page text plus the page count, for callers that must reject one-page
 * previews.
 * @param {string} filePath @returns {Promise<{ text: string, numpages: number } | null>}
 */
export function extractFirstPageInfo(filePath: string): Promise<{
    text: string;
    numpages: number;
} | null>;
/**
 * Text of the first `maxPages` pages (bounded), for evidence that a first page
 * does not carry, such as a DOI printed only on page 2.
 * @param {string} filePath @param {number} maxPages @returns {Promise<string | null>}
 */
export function extractPages(filePath: string, maxPages: number): Promise<string | null>;
//# sourceMappingURL=PdfFirstPage.d.cts.map