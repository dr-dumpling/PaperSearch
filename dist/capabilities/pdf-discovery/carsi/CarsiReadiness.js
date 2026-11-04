import { resolve } from "node:path";
import { AjvJsonSchemaValidator } from "@modelcontextprotocol/sdk/validation/ajv";
const DOWNLOAD_TOOL = "carsi_download";
const CACHE_CLEAR_TOOL = "carsi_cache_clear";
const BATCH_PROGRESS_TOOL = "carsi_batch_progress";
const COMPATIBILITY_BATCH = {
    id: "paper-search-compatibility",
    index: 1,
    total: 2,
    done: 0,
    succeeded: 0,
    failed: 0,
};
/** The MCP server name of the bundled backend (carsi/). */
export const ACCEPTED_SERVER_NAMES = new Set([
    "paper-search-carsi",
]);
const SCHEMA_VALIDATOR = new AjvJsonSchemaValidator();
const COMPATIBILITY_DOI = "10.1000/paper-search-compatibility";
/** The probe and real invocation must validate and send the same policy. */
export function createCarsiDownloadArguments(identifier, outputDir, strategy = "legal_only", batch, supplements, userWait, diagnosticsDir) {
    return {
        identifier,
        output_dir: resolve(outputDir),
        scihub_enabled: false,
        use_tor: false,
        bibtex: false,
        strategy,
        ...(batch
            ? {
                batch_id: batch.id,
                batch_index: batch.index,
                batch_total: batch.total,
                batch_done: batch.done,
                batch_succeeded: batch.succeeded,
                batch_failed: batch.failed,
            }
            : {}),
        ...(supplements ? { supplements } : {}),
        ...(userWait ? { user_wait: userWait } : {}),
        ...(diagnosticsDir ? { diagnostics_dir: resolve(diagnosticsDir) } : {}),
    };
}
export function selectCarsiBatchSupport(tools, strategy) {
    const download = tools.find((tool) => tool.name === DOWNLOAD_TOOL);
    const progress = tools.filter((tool) => tool.name === BATCH_PROGRESS_TOOL);
    return {
        downloadFields: !!download &&
            acceptsDeclaredArguments(download.inputSchema, createCarsiDownloadArguments(COMPATIBILITY_DOI, "paper-search-carsi-output", strategy, COMPATIBILITY_BATCH)),
        supplementsField: !!download &&
            acceptsDeclaredArguments(download.inputSchema, createCarsiDownloadArguments(COMPATIBILITY_DOI, "paper-search-carsi-output", strategy, undefined, "with")),
        userWaitField: !!download &&
            acceptsDeclaredArguments(download.inputSchema, createCarsiDownloadArguments(COMPATIBILITY_DOI, "paper-search-carsi-output", strategy, undefined, undefined, "short")),
        diagnosticsDirField: !!download && acceptsDeclaredArguments(download.inputSchema, createCarsiDownloadArguments(COMPATIBILITY_DOI, "output", strategy, undefined, undefined, undefined, "diagnostics")),
        progressTool: progress.length === 1 &&
            acceptsDeclaredArguments(progress[0].inputSchema, {
                batch_id: COMPATIBILITY_BATCH.id,
                total: 2,
                done: 1,
                succeeded: 1,
                failed: 0,
                current: COMPATIBILITY_DOI,
                finished: false,
            }),
    };
}
export function validateCarsiContract(serverName, tools) {
    if (!ACCEPTED_SERVER_NAMES.has(serverName ?? "")) {
        return incompatible("server_name_mismatch", "The MCP server is not paper-search-carsi.");
    }
    const download = tools.find((tool) => tool.name === DOWNLOAD_TOOL);
    if (!download) {
        return incompatible("missing_download_tool", "CARSI does not expose the required download tool.");
    }
    const cacheClear = tools.find((tool) => tool.name === CACHE_CLEAR_TOOL);
    if (!cacheClear) {
        return incompatible("missing_cache_clear_tool", "CARSI does not expose identifier-scoped cache clear.");
    }
    if (tools.filter((tool) => tool.name === DOWNLOAD_TOOL).length !== 1 ||
        tools.filter((tool) => tool.name === CACHE_CLEAR_TOOL).length !== 1) {
        return incompatible("ambiguous_tool_contract", "CARSI advertises conflicting definitions for a required tool.");
    }
    if (!isCompatibleDownloadSchema(download.inputSchema)) {
        return incompatible("download_schema_incompatible", "The CARSI download schema does not accept the required legal-only request. Update the PaperSearch adapter before using this backend.");
    }
    if (!isCompatibleCacheClearSchema(cacheClear.inputSchema)) {
        return incompatible("cache_clear_schema_incompatible", "The CARSI cache-clear schema does not accept an identifier-scoped request. Update the PaperSearch adapter before using this backend.");
    }
    return {
        state: "available",
        code: "ready",
        message: "CARSI MCP contract is compatible.",
        missing: [],
    };
}
/**
 * institutional_only tells the backend to skip its own public/OA race, which
 * PaperSearch has already run. It is only sent when the schema explicitly
 * enumerates the value; a plain string schema keeps legal_only.
 */
export function selectCarsiDownloadStrategy(schema) {
    const strategySchema = schema.properties?.strategy;
    if (!enumeratedStrings(strategySchema, schema).has("institutional_only") ||
        !acceptsDeclaredArguments(schema, createCarsiDownloadArguments(COMPATIBILITY_DOI, "paper-search-carsi-output", "institutional_only"))) {
        return "legal_only";
    }
    return "institutional_only";
}
function enumeratedStrings(node, root, depth = 0, seen = new Set()) {
    const found = new Set();
    if (!node || typeof node !== "object" || Array.isArray(node) || depth > 8) {
        return found;
    }
    const record = node;
    if (Array.isArray(record.enum)) {
        for (const value of record.enum)
            if (typeof value === "string")
                found.add(value);
    }
    if (typeof record.const === "string")
        found.add(record.const);
    for (const key of ["anyOf", "oneOf", "allOf"]) {
        const branches = record[key];
        if (Array.isArray(branches)) {
            for (const branch of branches) {
                for (const value of enumeratedStrings(branch, root, depth + 1, seen))
                    found.add(value);
            }
        }
    }
    if (typeof record.$ref === "string" &&
        record.$ref.startsWith("#/") &&
        !seen.has(record.$ref)) {
        seen.add(record.$ref);
        let target = root;
        for (const segment of record.$ref.slice(2).split("/")) {
            target =
                target && typeof target === "object"
                    ? target[segment]
                    : undefined;
        }
        for (const value of enumeratedStrings(target, root, depth + 1, seen))
            found.add(value);
    }
    return found;
}
export function isCompatibleDownloadSchema(schema) {
    return acceptsDeclaredArguments(schema, createCarsiDownloadArguments(COMPATIBILITY_DOI, "paper-search-carsi-output"));
}
export function isCompatibleCacheClearSchema(schema) {
    return acceptsDeclaredArguments(schema, { identifier: COMPATIBILITY_DOI });
}
function acceptsDeclaredArguments(schema, args) {
    if (schema.type !== "object" || !schema.properties)
        return false;
    // Additional properties alone do not advertise support for our policy flags.
    // Validate values using JSON Schema itself so compatible required/oneOf/$ref
    // changes do not depend on a particular generator's schema spelling.
    return (Object.keys(args).every((field) => Object.prototype.hasOwnProperty.call(schema.properties, field)) && schemaAccepts(schema, args));
}
function incompatible(code, message) {
    return {
        state: "incompatible",
        code,
        message,
        missing: [],
    };
}
function schemaAccepts(schema, value) {
    try {
        const validate = SCHEMA_VALIDATOR.getValidator(schema);
        return validate(value).valid;
    }
    catch {
        return false;
    }
}
//# sourceMappingURL=CarsiReadiness.js.map