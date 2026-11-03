import type { DownloadTier } from '../DownloadTier.js';
/**
 * Repository copies: PubMed Central through its official channels (see
 * pmcCloud.ts). Repository search results (CORE, OpenAIRE, PMC/Europe PMC
 * search) are not downloaded here: their links are landing pages or sit
 * behind bot protection, so searching cost tens of seconds per paper for no
 * PDF. Other repository copies arrive through Unpaywall's OA locations.
 */
export declare function createRepositoryTier(requestTimeoutMs?: number): DownloadTier;
//# sourceMappingURL=repositories.d.ts.map