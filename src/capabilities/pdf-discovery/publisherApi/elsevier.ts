import axios from "axios";
import * as fs from "fs";
import * as path from "path";
import { TIMEOUTS, USER_AGENT } from "../../../config/constants.js";
import {
  isPdfBuffer,
  safeFilename,
} from "../../../infrastructure/pdf/PdfDownload.js";
import { extractFirstPageInfo } from "../../../infrastructure/pdf/PdfFirstPage.cjs";
import type {
  PublisherApiAdapter,
  PublisherApiEnv,
  PublisherApiOutcome,
} from "./index.js";

/**
 * Elsevier Article Retrieval API: `GET /content/article/doi/{doi}` with
 * `Accept: application/pdf`. A valid key without full-text entitlement does
 * not fail; it returns a one-page preview, so the page count is checked.
 * Entitlement follows the egress IP (campus network) or an institution token.
 */
const ELSEVIER_ARTICLE_API = "https://api.elsevier.com/content/article/doi/";
const ELSEVIER_PREFIX = "10.1016/";

export function createElsevierAdapter(
  http: Pick<typeof axios, "get"> = axios,
): PublisherApiAdapter {
  return {
    id: "elsevier",
    requiredConfigKey: "ELSEVIER_API_KEY",
    matches: (doi) => doi.startsWith(ELSEVIER_PREFIX),
    configured: (env) => Boolean(env.ELSEVIER_API_KEY),
    fetch: (doi, savePath, env) => fetchElsevierPdf(http, doi, savePath, env),
  };
}

async function fetchElsevierPdf(
  http: Pick<typeof axios, "get">,
  doi: string,
  savePath: string,
  env: PublisherApiEnv,
): Promise<PublisherApiOutcome> {
  const apiKey = env.ELSEVIER_API_KEY;
  if (!apiKey)
    return { kind: "skipped", message: "ELSEVIER_API_KEY not configured." };
  const headers: Record<string, string> = {
    "X-ELS-APIKey": apiKey,
    Accept: "application/pdf",
    "User-Agent": USER_AGENT,
  };
  if (env.ELSEVIER_INSTTOKEN)
    headers["X-ELS-Insttoken"] = env.ELSEVIER_INSTTOKEN;

  let response: {
    status: number;
    data: unknown;
    headers?: Record<string, unknown>;
  };
  try {
    response = await http.get(ELSEVIER_ARTICLE_API + encodeURIComponent(doi), {
      responseType: "arraybuffer",
      timeout: TIMEOUTS.DOWNLOAD,
      maxRedirects: 5,
      headers,
      validateStatus: (status: number) => status < 500,
    });
  } catch (error: unknown) {
    const code = (error as { code?: string })?.code;
    return {
      kind: "error",
      code: "provider_error",
      message: `Elsevier API request failed${typeof code === "string" && /^[A-Z0-9_]+$/.test(code) ? ` (${code})` : ""}.`,
    };
  }

  switch (true) {
    case response.status === 401:
      return {
        kind: "error",
        code: "api_key_rejected",
        message: "Elsevier API rejected the API key (HTTP 401).",
      };
    case response.status === 403:
      return {
        kind: "error",
        code: "not_entitled",
        message:
          "Elsevier API refused full text (HTTP 403): the request's network egress or token is not entitled to this article.",
      };
    case response.status === 404:
      return {
        kind: "skipped",
        message: "Elsevier API has no article for this DOI (HTTP 404).",
      };
    case response.status === 429:
      return {
        kind: "error",
        code: "rate_limited",
        message: "Elsevier API rate limit reached (HTTP 429).",
      };
    case response.status >= 400:
      return {
        kind: "error",
        code: "provider_error",
        message: `Elsevier API returned HTTP ${response.status}.`,
      };
  }

  const buffer = Buffer.isBuffer(response.data)
    ? response.data
    : Buffer.from(response.data as ArrayBuffer);
  const contentType = String(response.headers?.["content-type"] ?? "");
  if (!isPdfBuffer(buffer, contentType)) {
    return {
      kind: "error",
      code: "not_entitled",
      message:
        "Elsevier API answered without a PDF body; full text is not entitled for this key or network.",
    };
  }

  fs.mkdirSync(savePath, { recursive: true });
  const outputPath = path.join(savePath, `elsevier_${safeFilename(doi)}.pdf`);
  const tmpPath = `${outputPath}.part`;
  fs.writeFileSync(tmpPath, buffer);
  fs.renameSync(tmpPath, outputPath);

  const info = await extractFirstPageInfo(outputPath);
  if (info && info.numpages === 1) {
    // A one-page document from this endpoint is the unentitled preview, not the article.
    try {
      fs.unlinkSync(outputPath);
    } catch {
      /* already gone */
    }
    return {
      kind: "error",
      code: "not_entitled",
      message:
        "Elsevier API returned a one-page preview: the key is valid but this network/token is not entitled to the full text.",
    };
  }
  return {
    kind: "ok",
    path: outputPath,
    format: "pdf",
    source: "elsevier_api",
  };
}
