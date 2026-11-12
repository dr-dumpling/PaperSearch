import { isAbsolute, resolve } from "node:path";
import { isInside } from "../outputLayout.js";
export class SchoolToolResultError extends Error {
    code;
    constructor(code) {
        super(code);
        this.code = code;
        this.name = "SchoolToolResultError";
    }
}
export function normalizeCacheClearResult(result) {
    const payload = parseSingleTextJson(result, "cache_clear_failed");
    if (payload.cleared !== 0 && payload.cleared !== 1) {
        throw new SchoolToolResultError("cache_clear_failed");
    }
}
export function normalizeDownloadResult(result, identifier, outputDir, diagnosticsDir) {
    const payload = parseSingleTextJson(result, "invalid_download_result");
    const trace = backendTrace(payload.artifacts, outputDir, diagnosticsDir);
    const supplements = backendSupplements(payload.supplements, outputDir);
    if (payload.success === true) {
        if (typeof payload.file !== "string" || payload.file.trim().length === 0) {
            throw new SchoolToolResultError("invalid_download_result");
        }
        const source = safeDiagnosticLabel(payload.source);
        return {
            kind: "success",
            identifier,
            path: payload.file,
            ...(source ? { source } : {}),
            ...(trace ? { trace } : {}),
            ...(supplements ? { supplements } : {}),
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
    return {
        kind: "attempt_error",
        identifier,
        code,
        message: `School backend did not return a usable PDF (${code}).`,
        ...(code === "rate_limited" && typeof retryAfter === "number" && Number.isFinite(retryAfter) && retryAfter > 0
            ? { retryAfterSec: Math.min(3600, Math.ceil(retryAfter)) }
            : {}),
        ...(trace ? { trace } : {}),
        ...(supplements ? { supplements } : {}),
    };
}
/**
 * The backend's supplementary files: status, a cleaned label, the file only
 * when it lies inside ``outputDir``, size, and a code-like reason.
 */
function backendSupplements(value, outputDir) {
    if (!Array.isArray(value))
        return undefined;
    // An explicit empty list means discovery completed without attachments.
    // A malformed/nonempty list that is entirely rejected must remain unknown.
    if (value.length === 0)
        return [];
    const files = [];
    for (const raw of value.slice(0, 200)) {
        if (!raw || typeof raw !== "object" || Array.isArray(raw))
            continue;
        const item = raw;
        const status = item.status;
        if (status !== "saved" && status !== "failed" && status !== "skipped")
            continue;
        const file = insideOutputDir(item.file, outputDir);
        if (status === "saved" && !file)
            continue;
        const entry = { status, label: cleanLabel(item.label) };
        if (file)
            entry.file = file;
        if (typeof item.size === "number" && Number.isFinite(item.size) && item.size >= 0) {
            entry.size = Math.round(item.size);
        }
        const code = typeof item.reason === "string" ? item.reason.trim().split(/[:\s]/, 1)[0] : "";
        if (/^[A-Za-z0-9_]{1,64}$/.test(code))
            entry.reason = code;
        files.push(entry);
    }
    return files.length ? files : undefined;
}
function cleanLabel(value) {
    if (typeof value !== "string")
        return "";
    return value
        .replace(/https?:\/\/\S+/gi, "")
        .replace(/[\u0000-\u001f\u007f]+/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 200);
}
function insideOutputDir(file, outputDir) {
    if (!outputDir || typeof file !== "string" || !isAbsolute(file))
        return undefined;
    // Links followed: the backend reports /private/tmp for the /tmp it was given (macOS).
    return isInside(file, outputDir) ? resolve(file) : undefined;
}
/**
 * The backend's ``artifacts``: driver/publisher labels, the state code, record
 * files and a stopped login's host name. Anything else, and any file outside
 * ``outputDir``, is dropped.
 */
function backendTrace(value, outputDir, diagnosticsDir) {
    if (!value || typeof value !== "object" || Array.isArray(value))
        return undefined;
    const artifacts = value;
    const trace = {};
    const driver = safeDiagnosticLabel(artifacts.driver);
    const publisher = safeDiagnosticLabel(artifacts.publisher);
    const state = typeof artifacts.state === "string" && /^[a-z0-9_]{1,64}$/.test(artifacts.state)
        ? artifacts.state
        : "";
    const stoppedHost = typeof artifacts.stopped_host === "string" && artifacts.stopped_host.length <= 253
        && /^[a-z0-9-]+(?:\.[a-z0-9-]+)+$/.test(artifacts.stopped_host) ? artifacts.stopped_host : "";
    if (driver)
        trace.driver = driver;
    if (publisher)
        trace.publisher = publisher;
    if (state)
        trace.state = state;
    if (stoppedHost)
        trace.stoppedHost = stoppedHost;
    for (const key of ["record", "diagnostic"]) {
        const file = insideOutputDir(artifacts[key], diagnosticsDir) || insideOutputDir(artifacts[key], outputDir);
        if (file)
            trace[key] = file;
    }
    return Object.keys(trace).length ? trace : undefined;
}
function parseSingleTextJson(result, errorCode) {
    if (!result || typeof result !== "object" || Array.isArray(result)) {
        throw new SchoolToolResultError(errorCode);
    }
    const toolResult = result;
    if (toolResult.isError === true ||
        !Array.isArray(toolResult.content) ||
        toolResult.content.length !== 1) {
        throw new SchoolToolResultError(errorCode);
    }
    const block = toolResult.content[0];
    if (!block || typeof block !== "object" || Array.isArray(block)) {
        throw new SchoolToolResultError(errorCode);
    }
    const textBlock = block;
    if (textBlock.type !== "text" || typeof textBlock.text !== "string") {
        throw new SchoolToolResultError(errorCode);
    }
    try {
        const parsed = JSON.parse(textBlock.text);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
            throw new Error("not an object");
        }
        return parsed;
    }
    catch {
        throw new SchoolToolResultError(errorCode);
    }
}
function safeReasonCode(value) {
    if (typeof value !== "string")
        return "";
    const trimmed = value.trim();
    if (containsSensitiveDiagnosticValue(trimmed))
        return "";
    const normalized = trimmed.toLowerCase();
    // Reserved local diagnosis requires the structured evidence checked above.
    if (normalized === "entitlement_missing")
        return "paywall";
    return /^[a-z0-9_.-]{1,64}$/.test(normalized) ? normalized : "";
}
function isSensitiveReasonCandidate(value) {
    return (typeof value === "string" && containsSensitiveDiagnosticValue(value.trim()));
}
function safeDiagnosticLabel(value) {
    if (typeof value !== "string")
        return "";
    const trimmed = value.trim();
    if (containsSensitiveDiagnosticValue(trimmed))
        return "";
    return /^[\p{L}\p{N}][\p{L}\p{N} ._()&+:-]{0,63}$/u.test(trimmed)
        ? trimmed
        : "";
}
function containsSensitiveDiagnosticValue(value) {
    if (value.length === 0)
        return false;
    return (/(?:https?|file):\/\/|\bwww\./i.test(value) ||
        /(?:^|[^a-z0-9_-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?::\d{1,5})?(?=$|[^a-z0-9_-])/i.test(value) ||
        /(?:^|[^\d])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?=$|[^\d])/i.test(value) ||
        /(?:^|[^a-z0-9_-])localhost(?::\d{1,5})?(?=$|[^a-z0-9_-])/i.test(value) ||
        /(?:^|[\s"'=])(?:~\/|\/\S*|[a-z]:[\\/]|\\\\)/i.test(value) ||
        /(?:^|[^a-z0-9])(?:authorization|bearer|token|api[\s._-]*key|ticket|cookie|password|passwd|secret|session|credential|access[\s._-]*key)(?=$|[^a-z0-9])/i.test(value) ||
        /\b(?:sk|pk)_(?:live|test)_[a-z0-9_-]{8,}\b/i.test(value) ||
        /\bsk-(?:proj|ant)-[a-z0-9_-]{8,}\b/i.test(value) ||
        /\bglpat-[a-z0-9_-]{8,}\b/i.test(value) ||
        /\bAIza[a-z0-9_-]{12,}\b/i.test(value) ||
        /\bnpm_[a-z0-9]{8,}\b/i.test(value) ||
        /\b(?:gh[pousr]|github_pat)_[a-z0-9_]{10,}\b/i.test(value) ||
        /\bxox[baprs]-[a-z0-9-]{10,}\b/i.test(value) ||
        /\bAKIA[0-9A-Z]{16}\b/.test(value) ||
        /\beyJ[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\b/i.test(value) ||
        /\b(?:sk-[a-z0-9_-]{16,}|rk_(?:live|test)_[a-z0-9_-]{12,}|whsec_[a-z0-9_-]{12,})\b/i.test(value) ||
        looksLikeOpaqueCredential(value));
}
function looksLikeOpaqueCredential(value) {
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) {
        return true;
    }
    if (/^[0-9a-f]{24,}$/i.test(value) || /^\d{24,}$/.test(value)) {
        return true;
    }
    return (/^[a-z0-9_-]{24,}$/i.test(value) && /[a-z]/i.test(value) && /\d/.test(value));
}
//# sourceMappingURL=SchoolResultNormalizer.js.map