/**
 * How to run this very PaperSearch CLI (node and the script it was started
 * with), as a JSON list; empty when that is not known. Passed to the progress
 * window, which runs `config test` with it: a window started from the desktop
 * may not find `paper-search` on its PATH.
 */
export function paperSearchCommand() {
    return process.argv[1] ? JSON.stringify([process.execPath, process.argv[1]]) : "";
}
//# sourceMappingURL=selfCommand.js.map