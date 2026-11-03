"use strict";
// CommonJS keeps the existing CommonJS parser resolvable both in the installed
// ESM CLI and in Jest. The same file is the worker entry, without eval code.
const { Worker, parentPort, workerData } = require("node:worker_threads");
const { readFileSync } = require("node:fs");
if (workerData?.paperSearchPdfFirstPage === true) {
    const parse = require("pdf-parse/lib/pdf-parse.js");
    parse(readFileSync(workerData.filePath), { max: workerData.maxPages || 1 })
        .then((result) => {
        const text = typeof result.text === "string"
            ? result.text.slice(0, (workerData.maxPages || 1) > 1 ? 400000 : 50000)
            : null;
        parentPort.postMessage(workerData.withInfo
            ? { text, numpages: Number(result.numpages) || 0 }
            : text);
    })
        .catch(() => parentPort.postMessage(null));
}
function runWorker(filePath, withInfo, maxPages = 1) {
    return new Promise((resolve) => {
        const worker = new Worker(__filename, {
            workerData: { filePath, paperSearchPdfFirstPage: true, withInfo, maxPages },
            stdout: true,
            stderr: true,
            resourceLimits: { maxOldGenerationSizeMb: 128 },
        });
        // Library warnings must not corrupt JSON or leak document contents.
        worker.stdout.resume();
        worker.stderr.resume();
        let settled = false;
        const finish = (value) => {
            if (settled)
                return;
            settled = true;
            clearTimeout(timer);
            void worker.terminate().then(() => resolve(value), () => resolve(null));
        };
        const timer = setTimeout(() => finish(null), 15_000);
        worker.once("message", (value) => finish(withInfo
            ? value && typeof value === "object" && typeof value.text === "string"
                ? value
                : null
            : typeof value === "string"
                ? value
                : null));
        worker.once("error", () => finish(null));
        worker.once("exit", () => finish(null));
    });
}
/**
 * First-page text plus the page count, for callers that must reject one-page
 * previews.
 * @param {string} filePath @returns {Promise<{ text: string, numpages: number } | null>}
 */
function extractFirstPageInfo(filePath) {
    return runWorker(filePath, true);
}
/**
 * Text of the first `maxPages` pages (bounded), for evidence that a first page
 * does not carry, such as a DOI printed only on page 2.
 * @param {string} filePath @param {number} maxPages @returns {Promise<string | null>}
 */
function extractPages(filePath, maxPages) {
    return runWorker(filePath, false, Math.max(1, Math.min(8, maxPages)));
}
module.exports = { extractFirstPageInfo, extractPages };
//# sourceMappingURL=PdfFirstPage.cjs.map