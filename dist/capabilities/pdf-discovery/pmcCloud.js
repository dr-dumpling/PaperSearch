import axios from "axios";
import { createHash } from "node:crypto";
import { readFileSync, unlinkSync } from "node:fs";
import { DEFAULT_MAILTO, USER_AGENT } from "../../config/constants.js";
import { downloadPdfFromUrl, safeFilename } from "../../infrastructure/pdf/PdfDownload.js";
/**
 * PubMed Central PDFs through NCBI's sanctioned channels (2026): the PMC Article
 * Datasets bucket (no key, PDFs "when permissible"), with Europe PMC's PDF
 * renderer for articles the bucket has no PDF for. The PMC site's /pdf/ link
 * (proof-of-work page) and Europe PMC's old render URLs need a browser.
 */
const BUCKET = "https://pmc-oa-opendata.s3.amazonaws.com";
const IDCONV = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/";
const EUROPE_PMC_PDF = "https://europepmc.org/api/getPdf";
const EUROPE_PMC_RETRY_MS = 10_000;
export async function pmcidForDoi(doi, timeoutMs) {
    const query = new URLSearchParams({
        ids: doi,
        format: "json",
        tool: "papersearch",
        email: process.env.NCBI_EMAIL || process.env.CROSSREF_MAILTO || DEFAULT_MAILTO,
    });
    // Node's fetch, not axios: NCBI's firewall answered axios requests with 403
    // while fetch, curl and Python requests got 200 (2026-10-31).
    const request = () => fetch(`${IDCONV}?${query}`, {
        headers: { "User-Agent": USER_AGENT, Accept: "application/json" },
        signal: AbortSignal.timeout(timeoutMs),
    });
    let response = await request();
    if ([403, 429].includes(response.status) || response.status >= 500) {
        // NCBI throttles bursts (no API key: 3 requests/s); one short retry.
        await new Promise((resolve) => setTimeout(resolve, 1_000));
        response = await request();
    }
    if (response.status !== 200)
        throw new Error(`PMC ID lookup failed with HTTP ${response.status}.`);
    const body = (await response.json());
    const record = (body.records || []).find((item) => String(item.doi || "").toLowerCase() === doi.toLowerCase());
    return /^PMC\d+$/i.test(record?.pmcid || "") ? record.pmcid.toUpperCase() : "";
}
/** The newest article version whose PDF is in the bucket, with its MD5. */
async function bucketPdf(pmcid, timeoutMs) {
    const listing = await axios.get(`${BUCKET}/`, {
        params: { "list-type": "2", prefix: `${pmcid}.`, delimiter: "/" },
        responseType: "text",
        timeout: timeoutMs,
    });
    const versions = [...String(listing.data).matchAll(/<Prefix>(PMC\d+\.(\d+))\/<\/Prefix>/g)]
        .map((match) => ({ key: match[1], version: Number(match[2]) }))
        .sort((a, b) => b.version - a.version);
    for (const { key } of versions) {
        const meta = await axios.get(`${BUCKET}/metadata/${key}.json`, {
            timeout: timeoutMs,
            validateStatus: (status) => status < 500,
        });
        const pdf = typeof meta.data?.pdf_url === "string" ? meta.data.pdf_url : "";
        const prefix = "s3://pmc-oa-opendata/";
        if (meta.status !== 200 || !pdf.startsWith(prefix))
            continue;
        const [objectKey, query] = pdf.slice(prefix.length).split("?");
        return { url: `${BUCKET}/${objectKey}`, md5: new URLSearchParams(query || "").get("md5") || "" };
    }
    return null;
}
export async function downloadPmcPdf(pmcid, savePath, timeoutMs) {
    const name = `pmc_${safeFilename(pmcid)}`;
    const cloud = await bucketPdf(pmcid, timeoutMs);
    if (cloud) {
        const path = await downloadPdfFromUrl(cloud.url, savePath, name);
        if (cloud.md5 && createHash("md5").update(readFileSync(path)).digest("hex") !== cloud.md5) {
            unlinkSync(path);
            throw new Error(`PMC PDF for ${pmcid} failed its MD5 check.`);
        }
        return { path, via: "pmc_cloud" };
    }
    // Europe PMC rate-limits hard (429 with Retry-After ~10 s): one retry, then give up.
    const url = `${EUROPE_PMC_PDF}?pmcid=${encodeURIComponent(pmcid)}`;
    for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
            return { path: await downloadPdfFromUrl(url, savePath, name, { timeoutMs: 60_000 }), via: "europepmc" };
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            if (/HTTP 404/.test(message))
                return null;
            if (attempt === 0 && /HTTP 429/.test(message)) {
                await new Promise((resolve) => setTimeout(resolve, EUROPE_PMC_RETRY_MS));
                continue;
            }
            throw error;
        }
    }
    return null;
}
//# sourceMappingURL=pmcCloud.js.map