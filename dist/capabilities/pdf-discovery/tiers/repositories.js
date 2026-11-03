import { TIMEOUTS } from '../../../config/constants.js';
import { withTimeout } from '../../../infrastructure/security/SecurityUtils.js';
import { downloadPmcPdf, pmcidForDoi } from '../pmcCloud.js';
/**
 * Repository copies: PubMed Central through its official channels (see
 * pmcCloud.ts). Repository search results (CORE, OpenAIRE, PMC/Europe PMC
 * search) are not downloaded here: their links are landing pages or sit
 * behind bot protection, so searching cost tens of seconds per paper for no
 * PDF. Other repository copies arrive through Unpaywall's OA locations.
 */
export function createRepositoryTier(requestTimeoutMs = TIMEOUTS.REPOSITORY_SEARCH) {
    return {
        id: 'repositories',
        stage: 'repositories',
        run: (context) => tryPubMedCentral(context, requestTimeoutMs)
    };
}
async function tryPubMedCentral(context, requestTimeoutMs) {
    const given = /^PMC\d+$/i.test(context.paperId || '') ? context.paperId.toUpperCase() : '';
    try {
        const pmcid = given || (context.doi
            ? await withTimeout(pmcidForDoi(context.doi, requestTimeoutMs), requestTimeoutMs, 'PMC ID lookup timed out')
            : '');
        if (!pmcid) {
            return { status: 'skipped', message: 'Not in PubMed Central.' };
        }
        const found = await downloadPmcPdf(pmcid, context.savePath, requestTimeoutMs);
        if (!found) {
            return { status: 'skipped', message: `PubMed Central has no PDF for ${pmcid}.` };
        }
        return { status: 'ok', path: found.path, message: found.path, trace: { pmcid, via: found.via } };
    }
    catch (error) {
        return { status: 'error', message: error instanceof Error ? error.message : String(error) };
    }
}
//# sourceMappingURL=repositories.js.map