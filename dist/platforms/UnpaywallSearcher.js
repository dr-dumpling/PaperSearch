import axios from 'axios';
import { PaperFactory } from '../models/Paper.js';
import { PaperSource } from './PaperSource.js';
import { TIMEOUTS, USER_AGENT } from '../config/constants.js';
import { sanitizeDoi } from '../infrastructure/security/SecurityUtils.js';
export class UnpaywallSearcher extends PaperSource {
    client;
    email;
    constructor(email) {
        const configuredEmail = email || process.env.PAPER_SEARCH_UNPAYWALL_EMAIL || process.env.UNPAYWALL_EMAIL || '';
        super('unpaywall', 'https://api.unpaywall.org/v2', configuredEmail);
        this.email = configuredEmail.trim();
        this.client = axios.create({
            baseURL: this.baseUrl,
            timeout: TIMEOUTS.DEFAULT,
            headers: {
                Accept: 'application/json',
                'User-Agent': `${USER_AGENT} (https://github.com/dr-dumpling/PaperSearch)`
            },
            validateStatus: status => status < 500
        });
    }
    getCapabilities() {
        return {
            search: true,
            download: false,
            fullText: false,
            citations: false,
            requiresApiKey: true,
            supportedOptions: ['maxResults']
        };
    }
    hasApiKey() {
        return Boolean(this.email);
    }
    async search(query, _options = {}) {
        const doi = this.extractDoi(query);
        if (!doi || !this.email)
            return [];
        const paper = await this.getPaperByDoi(doi);
        return paper ? [paper] : [];
    }
    async getPaperByDoi(doi) {
        if (!this.email)
            return null;
        const cleanDoi = this.extractDoi(doi);
        if (!cleanDoi)
            return null;
        const record = await this.fetchRecord(cleanDoi, 'getPaperByDoi');
        return record ? this.parseRecord(record, cleanDoi) : null;
    }
    /**
     * Every OA location's PDF URL, published version first, then accepted and
     * submitted; within a version, repositories before the publisher. Unpaywall's
     * own best location prefers publisher copies, which often refuse plain HTTP.
     */
    async resolvePdfCandidates(doi) {
        if (!this.email)
            return [];
        const cleanDoi = this.extractDoi(doi);
        if (!cleanDoi)
            return [];
        const record = await this.fetchRecord(cleanDoi, 'resolvePdfCandidates');
        const versionRank = { publishedVersion: 0, acceptedVersion: 1, submittedVersion: 2 };
        const seen = new Set();
        return (record?.oa_locations || [])
            .filter((location) => location.url_for_pdf && !seen.has(location.url_for_pdf) && seen.add(location.url_for_pdf))
            .map((location) => ({ url: location.url_for_pdf, hostType: location.host_type || '', version: location.version || '' }))
            .sort((a, b) => (versionRank[a.version] ?? 3) - (versionRank[b.version] ?? 3) ||
            Number(a.hostType !== 'repository') - Number(b.hostType !== 'repository'));
    }
    async fetchRecord(cleanDoi, operation) {
        try {
            const response = await this.client.get(`/${encodeURIComponent(cleanDoi)}`, {
                params: { email: this.email }
            });
            if (response.status === 404 || response.status === 422)
                return null;
            if (response.status >= 400) {
                throw new Error(`Unpaywall request failed with HTTP ${response.status}`);
            }
            return response.data;
        }
        catch (error) {
            this.handleHttpError(error, operation);
        }
    }
    async downloadPdf(_paperId, _options = {}) {
        throw new Error('Unpaywall does not host PDFs. Use returned pdf_url with download_with_fallback.');
    }
    async readPaper(_paperId, _options = {}) {
        throw new Error('Unpaywall provides OA metadata only; it does not provide full text.');
    }
    parseRecord(record, doi) {
        const best = record.best_oa_location || {};
        const pdfUrl = best.url_for_pdf || best.url || this.firstLocationUrl(record.oa_locations || []);
        const authors = (record.z_authors || [])
            .map(author => `${author.given || ''} ${author.family || ''}`.trim())
            .filter(Boolean);
        return PaperFactory.create({
            paperId: `unpaywall:${doi}`,
            title: record.title || doi,
            authors,
            abstract: '',
            doi: record.doi || doi,
            publishedDate: record.published_date ? this.parseDate(record.published_date) : null,
            pdfUrl: pdfUrl || '',
            url: best.url || record.doi_url || `https://doi.org/${doi}`,
            source: 'unpaywall',
            journal: record.journal_name || '',
            extra: {
                isOpenAccess: Boolean(record.is_oa),
                oaStatus: record.oa_status || '',
                publisher: record.publisher || '',
                hostType: best.host_type || '',
                license: best.license || '',
                version: best.version || ''
            }
        });
    }
    firstLocationUrl(locations) {
        for (const location of locations) {
            const candidate = location.url_for_pdf || location.url || '';
            if (candidate)
                return candidate;
        }
        return '';
    }
    extractDoi(value) {
        const candidate = value.match(/10\.\d{4,9}\/[-._;()/:A-Z0-9]+/i)?.[0] || value;
        const result = sanitizeDoi(candidate);
        return result.valid ? result.sanitized : '';
    }
}
//# sourceMappingURL=UnpaywallSearcher.js.map