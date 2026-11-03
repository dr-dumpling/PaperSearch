import axios from "axios";
import * as fs from "fs";
import * as path from "path";
import { TIMEOUTS, USER_AGENT } from "../../../config/constants.js";
import { safeFilename } from "../../../infrastructure/pdf/PdfDownload.js";
import { sanitizeDoi } from "../../../infrastructure/security/SecurityUtils.js";
/**
 * Springer Nature Full Text (TDM) API. There is no PDF endpoint: subscription
 * full text comes back as JATS XML, which is written next to PDFs as `.xml`.
 * Without entitlement the record carries metadata but no `<body>`.
 */
const SPRINGER_TDM_API = "https://api.springernature.com/xmldata/jats";
const SPRINGER_PREFIX = "10.1007/";
const MIN_BODY_CHARS = 1500;
export function createSpringerAdapter(http = axios) {
    return {
        id: "springer",
        requiredConfigKey: "SPRINGER_API_KEY",
        matches: (doi) => doi.startsWith(SPRINGER_PREFIX),
        configured: (env) => Boolean(env.SPRINGER_API_KEY),
        fetch: (doi, savePath, env) => fetchSpringerJats(http, doi, savePath, env),
    };
}
async function fetchSpringerJats(http, doi, savePath, env) {
    const apiKey = env.SPRINGER_API_KEY;
    if (!apiKey)
        return { kind: "skipped", message: "SPRINGER_API_KEY not configured." };
    let response;
    try {
        response = await http.get(SPRINGER_TDM_API, {
            params: { q: `doi:"${doi}"`, api_key: apiKey },
            responseType: "text",
            timeout: TIMEOUTS.DOWNLOAD,
            headers: {
                "User-Agent": USER_AGENT,
                Accept: "application/xml,text/xml,*/*",
            },
            validateStatus: (status) => status < 500,
        });
    }
    catch (error) {
        const code = error?.code;
        return {
            kind: "error",
            code: "provider_error",
            message: `Springer TDM request failed${typeof code === "string" && /^[A-Z0-9_]+$/.test(code) ? ` (${code})` : ""}.`,
        };
    }
    if (response.status === 401 || response.status === 403) {
        return {
            kind: "error",
            code: response.status === 401 ? "api_key_rejected" : "not_entitled",
            message: `Springer TDM API refused the request (HTTP ${response.status}).`,
        };
    }
    if (response.status === 429) {
        return {
            kind: "error",
            code: "rate_limited",
            message: "Springer TDM API rate limit reached (HTTP 429).",
        };
    }
    if (response.status >= 400) {
        return {
            kind: "error",
            code: "provider_error",
            message: `Springer TDM API returned HTTP ${response.status}.`,
        };
    }
    const xml = typeof response.data === "string"
        ? response.data
        : Buffer.from(response.data).toString("utf8");
    if (!/<article[\s>]/i.test(xml)) {
        return {
            kind: "skipped",
            message: "Springer TDM API returned no article record for this DOI.",
        };
    }
    const recordDoi = xml.match(/<article-id[^>]*pub-id-type="doi"[^>]*>\s*([^<\s]+)\s*</i)?.[1];
    const expected = sanitizeDoi(doi);
    if (!recordDoi ||
        !expected.valid ||
        recordDoi.toLowerCase() !== expected.sanitized.toLowerCase()) {
        return {
            kind: "error",
            code: "record_mismatch",
            message: "Springer TDM record DOI does not match the requested DOI; nothing was saved.",
        };
    }
    const body = xml.match(/<body[\s>][\s\S]*?<\/body>/i)?.[0] ?? "";
    const bodyText = body
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim();
    if (bodyText.length < MIN_BODY_CHARS) {
        return {
            kind: "error",
            code: "not_entitled",
            message: "Springer TDM API returned the record without full-text body: this key has no subscription entitlement for the article.",
        };
    }
    fs.mkdirSync(savePath, { recursive: true });
    const outputPath = path.join(savePath, `springer_${safeFilename(doi)}.xml`);
    const tmpPath = `${outputPath}.part`;
    fs.writeFileSync(tmpPath, xml, "utf8");
    fs.renameSync(tmpPath, outputPath);
    return {
        kind: "ok",
        path: outputPath,
        format: "jats-xml",
        source: "springer_tdm",
    };
}
//# sourceMappingURL=springer.js.map