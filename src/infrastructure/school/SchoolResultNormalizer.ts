import { isAbsolute, resolve } from "node:path";
import type { SchoolFulltextPage, SchoolInvocationOutcome, SchoolSupplement, SchoolTrace } from "./types.js";
import { isInside } from "../../capabilities/download/outputLayout.js";

export class SchoolToolResultError extends Error {
  constructor(readonly code: "cache_clear_failed" | "invalid_download_result") {
    super(code);
    this.name = "SchoolToolResultError";
  }
}

export function normalizeCacheClearResult(result: unknown): void {
  const payload = parseSingleTextJson(result, "cache_clear_failed");
  if (payload.cleared !== 0 && payload.cleared !== 1) {
    throw new SchoolToolResultError("cache_clear_failed");
  }
}

export function normalizeDownloadResult(
  result: unknown,
  identifier: string,
  outputDir?: string,
  diagnosticsDir?: string,
): SchoolInvocationOutcome {
  const payload = parseSingleTextJson(result, "invalid_download_result");
  const trace = backendTrace(payload.artifacts, outputDir, diagnosticsDir);
  const supplements = backendSupplements(payload.supplements, outputDir);
  const fulltextPage = backendFulltextPage(payload.fulltext_page, outputDir);

  if (payload.success === true) {
    if ((typeof payload.file !== "string" || payload.file.trim().length === 0) && fulltextPage) {
      // A visit for the article's page alone (fulltext "only"): no PDF was asked of it.
      return {
        kind: "attempt_error",
        identifier,
        code: "fulltext_page_only",
        message: "School backend saved the article page alone; no PDF was asked of it.",
        ...(trace ? { trace } : {}),
        fulltextPage,
      };
    }
    if (typeof payload.file !== "string" || payload.file.trim().length === 0) {
      // A visit for the page alone whose page was not saved: why, as the backend says it (it
      // came as success with nothing in it, 后端结果无法使用: Oxford, Karger, PNAS, 2026-11-17).
      const missed = typeof payload.fulltext_page_not_saved === "string" ? payload.fulltext_page_not_saved.trim() : "";
      if (/^[a-z_]{1,40}$/.test(missed)) {
        return {
          kind: "attempt_error",
          identifier,
          // No text on it; a paywall or denial on it (pnas.org's "Get full access", 2026-11-17); else not saved.
          code: missed === "fulltext_not_shown" ? "page_no_fulltext" : missed === "fulltext_denied" ? "page_not_entitled" : "page_not_saved",
          message: `School backend opened the article but did not save its page (${missed}).`,
          ...(trace ? { trace } : {}),
        };
      }
      throw new SchoolToolResultError("invalid_download_result");
    }
    const source = safeDiagnosticLabel(payload.source);
    // The saved school it was got through, when not the default one (school_switch.py): a name to show, no more.
    const school = typeof payload.school === "string" && payload.school.trim().length <= 120 ? payload.school.trim() : "";
    return {
      kind: "success",
      identifier,
      path: payload.file,
      ...(source ? { source } : {}),
      ...(school ? { school } : {}),
      ...(trace ? { trace } : {}),
      ...(supplements ? { supplements } : {}),
      ...(fulltextPage ? { fulltextPage } : {}),
      ...(!fulltextPage && payload.fulltext_page_not_shown === true ? { fulltextNotShown: true } : {}),
    };
  }

  if (payload.success !== false) {
    throw new SchoolToolResultError("invalid_download_result");
  }

  const reasonCandidates = [payload.error_type, payload.action];
  const code = reasonCandidates.some(isSensitiveReasonCandidate)
    ? "download_failed"
    : (payload.action === "login_required" ? "login_required" : "") ||
      (payload.error_type === "paywall" &&
      payload.reason_code === "institution_pdf_entitlement_missing" &&
      payload.action === "review_entitlement"
        ? "entitlement_missing"
        : "") ||
      safeReasonCode(payload.error_type) ||
      safeReasonCode(payload.action) ||
      "download_failed";
  const retryAfter = payload.retry_after_sec;
  const tried = payload.schools_tried;
  return {
    kind: "attempt_error",
    identifier,
    code,
    ...(typeof tried === "number" && Number.isInteger(tried) && tried >= 2 && tried <= 20 ? { schoolsTried: tried } : {}),
    message: `School backend did not return a usable PDF (${code}).`,
    ...(code === "rate_limited" && typeof retryAfter === "number" && Number.isFinite(retryAfter) && retryAfter > 0
      ? { retryAfterSec: Math.min(3600, Math.ceil(retryAfter)),
          ...(typeof payload.publisher === "string" && payload.publisher.trim()
            ? { hourlyPublisher: payload.publisher.trim().slice(0, 200) } : {}) }
      : {}),
    ...(trace ? { trace } : {}),
    ...(supplements ? { supplements } : {}),
    ...(fulltextPage ? { fulltextPage } : {}),
  };
}

/**
 * The backend's supplementary files: status, a cleaned label, the file only
 * when it lies inside ``outputDir``, size, and a code-like reason.
 */
function backendSupplements(value: unknown, outputDir?: string): SchoolSupplement[] | undefined {
  if (!Array.isArray(value)) return undefined;
  // An explicit empty list means discovery completed without attachments.
  // A malformed/nonempty list that is entirely rejected must remain unknown.
  if (value.length === 0) return [];
  const files: SchoolSupplement[] = [];
  for (const raw of value.slice(0, 200)) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const item = raw as Record<string, unknown>;
    const status = item.status;
    if (status !== "saved" && status !== "failed" && status !== "skipped") continue;
    const file = insideOutputDir(item.file, outputDir);
    if (status === "saved" && !file) continue;
    const entry: SchoolSupplement = { status, label: cleanLabel(item.label) };
    if (file) entry.file = file;
    if (typeof item.size === "number" && Number.isFinite(item.size) && item.size >= 0) {
      entry.size = Math.round(item.size);
    }
    const code = typeof item.reason === "string" ? item.reason.trim().split(/[:\s]/, 1)[0] : "";
    if (/^[A-Za-z0-9_]{1,64}$/.test(code)) entry.reason = code;
    files.push(entry);
  }
  return files.length ? files : undefined;
}

/**
 * The full-text page the backend saved: its HTML file and figure images, each only
 * when it lies inside ``outputDir``, with http(s) addresses. Anything else is dropped;
 * a page without its HTML file is no page.
 */
function backendFulltextPage(value: unknown, outputDir?: string): SchoolFulltextPage | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const page = value as Record<string, unknown>;
  const file = insideOutputDir(page.file, outputDir);
  const url = webAddress(page.url);
  if (!file || !/\.html?$/i.test(file) || !url) return undefined;
  const images: SchoolFulltextPage["images"] = [];
  for (const raw of Array.isArray(page.images) ? page.images.slice(0, 200) : []) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const image = raw as Record<string, unknown>;
    const imageFile = insideOutputDir(image.file, outputDir);
    const imageUrl = webAddress(image.url);
    if (imageFile && imageUrl) images.push({ url: imageUrl, file: imageFile });
  }
  return { file, url, images };
}

function webAddress(value: unknown): string | undefined {
  if (typeof value !== "string" || value.length > 2048) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function cleanLabel(value: unknown): string {
  if (typeof value !== "string") return "";
  return value
    .replace(/https?:\/\/\S+/gi, "")
    .replace(/[\u0000-\u001f\u007f]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 200);
}

function insideOutputDir(file: unknown, outputDir?: string): string | undefined {
  if (!outputDir || typeof file !== "string" || !isAbsolute(file)) return undefined;
  // Links followed: the backend reports /private/tmp for the /tmp it was given (macOS).
  return isInside(file, outputDir) ? resolve(file) : undefined;
}

/**
 * The backend's ``artifacts``: driver/publisher labels, the state code, record
 * files, a stopped login's host name, where a wait on a login ended and whether its browser
 * stopped answering (``browser_stopped``). Anything else, and any file outside
 * ``outputDir``, is dropped.
 */
/** Where a wait on a school login can end (the backend's _login_wait_page). */
const LOGIN_WAIT_PAGES = new Set(["school_login", "school_choice", "institution_chooser", "authentication_redirect",
  "publisher", "other", "closed"]);

function backendTrace(value: unknown, outputDir?: string, diagnosticsDir?: string): SchoolTrace | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const artifacts = value as Record<string, unknown>;
  const trace: SchoolTrace = {};
  const driver = safeDiagnosticLabel(artifacts.driver);
  const publisher = safeDiagnosticLabel(artifacts.publisher);
  const state = typeof artifacts.state === "string" && /^[a-z0-9_]{1,64}$/.test(artifacts.state)
    ? artifacts.state
    : "";
  const stoppedHost = typeof artifacts.stopped_host === "string" && artifacts.stopped_host.length <= 253
    && /^[a-z0-9-]+(?:\.[a-z0-9-]+)+$/.test(artifacts.stopped_host) ? artifacts.stopped_host : "";
  if (driver) trace.driver = driver;
  if (publisher) trace.publisher = publisher;
  if (state) trace.state = state;
  if (stoppedHost) trace.stoppedHost = stoppedHost;
  if (typeof artifacts.login_wait_page === "string" && LOGIN_WAIT_PAGES.has(artifacts.login_wait_page)) {
    trace.loginWaitPage = artifacts.login_wait_page;
  }
  if (artifacts.browser_stopped === true) trace.browserStopped = true;
  for (const key of ["record", "diagnostic"] as const) {
    const file = insideOutputDir(artifacts[key], diagnosticsDir) || insideOutputDir(artifacts[key], outputDir);
    if (file) trace[key] = file;
  }
  return Object.keys(trace).length ? trace : undefined;
}

function parseSingleTextJson(
  result: unknown,
  errorCode: "cache_clear_failed" | "invalid_download_result",
): Record<string, unknown> {
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    throw new SchoolToolResultError(errorCode);
  }

  const toolResult = result as { isError?: unknown; content?: unknown };
  if (
    toolResult.isError === true ||
    !Array.isArray(toolResult.content) ||
    toolResult.content.length !== 1
  ) {
    throw new SchoolToolResultError(errorCode);
  }

  const block = toolResult.content[0];
  if (!block || typeof block !== "object" || Array.isArray(block)) {
    throw new SchoolToolResultError(errorCode);
  }
  const textBlock = block as { type?: unknown; text?: unknown };
  if (textBlock.type !== "text" || typeof textBlock.text !== "string") {
    throw new SchoolToolResultError(errorCode);
  }

  try {
    const parsed = JSON.parse(textBlock.text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("not an object");
    }
    return parsed as Record<string, unknown>;
  } catch {
    throw new SchoolToolResultError(errorCode);
  }
}

function safeReasonCode(value: unknown): string {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  if (containsSensitiveDiagnosticValue(trimmed)) return "";
  const normalized = trimmed.toLowerCase();
  // Reserved local diagnosis requires the structured evidence checked above.
  if (normalized === "entitlement_missing") return "paywall";
  return /^[a-z0-9_.-]{1,64}$/.test(normalized) ? normalized : "";
}

function isSensitiveReasonCandidate(value: unknown): boolean {
  return (
    typeof value === "string" && containsSensitiveDiagnosticValue(value.trim())
  );
}

function safeDiagnosticLabel(value: unknown): string {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  if (containsSensitiveDiagnosticValue(trimmed)) return "";
  return /^[\p{L}\p{N}][\p{L}\p{N} ._()&+:-]{0,63}$/u.test(trimmed)
    ? trimmed
    : "";
}

function containsSensitiveDiagnosticValue(value: string): boolean {
  if (value.length === 0) return false;

  return (
    /(?:https?|file):\/\/|\bwww\./i.test(value) ||
    /(?:^|[^a-z0-9_-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?::\d{1,5})?(?=$|[^a-z0-9_-])/i.test(
      value,
    ) ||
    /(?:^|[^\d])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?=$|[^\d])/i.test(value) ||
    /(?:^|[^a-z0-9_-])localhost(?::\d{1,5})?(?=$|[^a-z0-9_-])/i.test(value) ||
    /(?:^|[\s"'=])(?:~\/|\/\S*|[a-z]:[\\/]|\\\\)/i.test(value) ||
    /(?:^|[^a-z0-9])(?:authorization|bearer|token|api[\s._-]*key|ticket|cookie|password|passwd|secret|session|credential|access[\s._-]*key)(?=$|[^a-z0-9])/i.test(
      value,
    ) ||
    /\b(?:sk|pk)_(?:live|test)_[a-z0-9_-]{8,}\b/i.test(value) ||
    /\bsk-(?:proj|ant)-[a-z0-9_-]{8,}\b/i.test(value) ||
    /\bglpat-[a-z0-9_-]{8,}\b/i.test(value) ||
    /\bAIza[a-z0-9_-]{12,}\b/i.test(value) ||
    /\bnpm_[a-z0-9]{8,}\b/i.test(value) ||
    /\b(?:gh[pousr]|github_pat)_[a-z0-9_]{10,}\b/i.test(value) ||
    /\bxox[baprs]-[a-z0-9-]{10,}\b/i.test(value) ||
    /\bAKIA[0-9A-Z]{16}\b/.test(value) ||
    /\beyJ[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\b/i.test(value) ||
    /\b(?:sk-[a-z0-9_-]{16,}|rk_(?:live|test)_[a-z0-9_-]{12,}|whsec_[a-z0-9_-]{12,})\b/i.test(
      value,
    ) ||
    looksLikeOpaqueCredential(value)
  );
}

function looksLikeOpaqueCredential(value: string): boolean {
  if (
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      value,
    )
  ) {
    return true;
  }
  if (/^[0-9a-f]{24,}$/i.test(value) || /^\d{24,}$/.test(value)) {
    return true;
  }
  return (
    /^[a-z0-9_-]{24,}$/i.test(value) && /[a-z]/i.test(value) && /\d/.test(value)
  );
}
