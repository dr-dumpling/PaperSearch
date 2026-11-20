import { readFileSync } from "node:fs";
import { isValidPdfFile } from "../../../../infrastructure/pdf/PdfDownload.js";
import { verifyPdfIdentity } from "../../../../infrastructure/pdf/PdfIdentity.js";
import { identityRejection } from "./identity.js";
import { schoolAttemptDetails } from "../../../../infrastructure/school/index.js";
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
            ...(context.title ? { title: context.title } : {}),
            ...(context.batch ? { batch: context.batch } : {}),
            ...(context.withSupplements ? { supplements: "with" } : {}),
            ...(context.shortUserWait ? { userWait: "short" } : {}),
            ...(context.withFulltext ? { fulltext: "with" } : {}),
            ...(context.school ? { school: context.school } : {}),
        });
        const supplements = {
            // An empty list is kept: the visit checked the article page and it listed none, which is
            // not "never checked" (a resume asked for them all again, Windows 2026-11-16).
            ...(outcome.kind !== "backend_unavailable" && Array.isArray(outcome.supplements) ? { supplements: outcome.supplements } : {}),
            // The full-text page goes to the full-text step whatever became of the PDF.
            ...(outcome.kind !== "backend_unavailable" && outcome.fulltextPage ? { fulltextPage: outcome.fulltextPage } : {}),
        };
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
                ...schoolAttemptDetails(outcome.code, outcome.trace),
                ...(outcome.retryAfterSec ? { retryAfterSec: outcome.retryAfterSec } : {}),
                ...(outcome.hourlyPublisher ? { hourlyPublisher: outcome.hourlyPublisher } : {}),
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
            ...(outcome.trace?.state === "batch_stopped" ? { code: "batch_stopped" } : {}),
            trace,
            ...supplements,
            ...(outcome.fulltextNotShown ? { fulltextNotShown: true } : {}),
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
//# sourceMappingURL=school.js.map