import { readFileSync } from "node:fs";
import { isValidPdfFile } from "../../../infrastructure/pdf/PdfDownload.js";
import { verifyPdfIdentity } from "../../../infrastructure/pdf/PdfIdentity.js";
import { identityRejection } from "../identity.js";
import { carsiAttemptDetails, } from "../carsi/index.js";
const BACKEND_UNAVAILABLE_MESSAGE = "Entitled access backend unavailable.";
/** The URL the backend took the PDF from, from its run record: evidence for a scan without text. */
function recordPdfUrl(record) {
    if (typeof record !== "string" || !record)
        return undefined;
    try {
        const url = JSON.parse(readFileSync(record, "utf8")).pdf_url;
        return typeof url === "string" && url ? url : undefined;
    }
    catch {
        return undefined;
    }
}
const ATTEMPT_FAILED_MESSAGE = "Entitled access download attempt failed.";
export function createEntitledAccessTier(backend) {
    return {
        id: "entitled_access",
        stage: "entitled_access",
        run: (context) => tryEntitledAccess(context, backend),
    };
}
async function tryEntitledAccess(context, backend) {
    if (!context.useEntitledAccess) {
        return {
            status: "skipped",
            message: "Entitled access disabled by useEntitledAccess=false.",
        };
    }
    if (!backend) {
        return { status: "skipped", message: BACKEND_UNAVAILABLE_MESSAGE };
    }
    try {
        const outcome = await backend.downloadLegalDoi({
            identifier: context.doi || context.paperId,
            outputDir: context.savePath,
            ...(context.diagnosticsDir ? { diagnosticsDir: context.diagnosticsDir } : {}),
            ...(context.batch ? { batch: context.batch } : {}),
            ...(context.withSupplements ? { supplements: "with" } : {}),
            ...(context.shortUserWait ? { userWait: "short" } : {}),
        });
        const supplements = outcome.kind !== "backend_unavailable" && outcome.supplements?.length
            ? { supplements: outcome.supplements }
            : {};
        if (outcome.kind === "backend_unavailable") {
            return { status: "skipped", message: BACKEND_UNAVAILABLE_MESSAGE };
        }
        if (outcome.kind === "attempt_error") {
            if (outcome.code === "invalid_identifier") {
                return {
                    status: "skipped",
                    message: "Entitled access requires a valid DOI.",
                };
            }
            return {
                status: "error",
                ...carsiAttemptDetails(outcome.code, outcome.trace),
                ...(outcome.retryAfterSec ? { retryAfterSec: outcome.retryAfterSec } : {}),
                ...(outcome.trace ? { trace: { ...outcome.trace } } : {}),
                ...supplements,
            };
        }
        const trace = { ...(outcome.trace ?? {}), file: outcome.path };
        if (!isValidPdfFile(outcome.path)) {
            return {
                status: "error",
                message: "Entitled access returned an invalid PDF.",
                code: "invalid_pdf",
                trace,
                ...supplements,
            };
        }
        const identity = await verifyPdfIdentity(outcome.path, context.doi || context.paperId, context.title, recordPdfUrl(outcome.trace?.record));
        trace.identity = identity;
        const rejection = identityRejection(identity, outcome.path);
        if (rejection)
            return { ...rejection, trace, ...supplements };
        return {
            status: "ok",
            path: outcome.path,
            verified: true,
            message: "Entitled access PDF downloaded.",
            trace,
            ...supplements,
        };
    }
    catch (error) {
        return {
            status: "error",
            message: ATTEMPT_FAILED_MESSAGE,
            trace: {
                exception: error instanceof Error ? `${error.name}: ${error.message}`.slice(0, 500) : String(error),
            },
        };
    }
}
/**
 * Supplementary files only, for an article whose main text came from another
 * stage. Undefined when no backend can do it.
 */
export async function fetchSupplementsOnly(backend, request, onTrace) {
    if (!backend)
        return undefined;
    try {
        const outcome = await backend.downloadLegalDoi({ ...request, supplements: "only" });
        if (outcome.kind === "backend_unavailable")
            return undefined;
        if (outcome.trace)
            onTrace?.({ ...outcome.trace });
        if (outcome.kind === "attempt_error" && (!outcome.supplements ||
            (outcome.supplements.length === 0 && outcome.code !== "supplements_only"))) {
            const { code } = carsiAttemptDetails(outcome.code);
            return [{ label: "", status: code === "batch_stopped" || code === "user_skipped" ? "skipped" : "failed", reason: code }];
        }
        return outcome.supplements ?? [{ label: "", status: "failed", reason: "supplements_not_reported" }];
    }
    catch (error) {
        return [
            {
                label: "",
                status: "failed",
                reason: error instanceof Error ? error.name : "backend_error",
            },
        ];
    }
}
//# sourceMappingURL=entitledAccess.js.map