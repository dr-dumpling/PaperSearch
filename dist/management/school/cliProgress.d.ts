import type { SchoolBackend } from "../../capabilities/pdf-discovery/school/index.js";
/**
 * The CLI's backend: a download can be stopped with Ctrl-C and tells its steps
 * on stderr; every other method of the backend is passed on as it is (each one
 * by name: a method left out here is gone for the CLI, see the wrapper test).
 */
export declare function withCliSchoolProgress(backend: SchoolBackend): SchoolBackend;
//# sourceMappingURL=cliProgress.d.ts.map