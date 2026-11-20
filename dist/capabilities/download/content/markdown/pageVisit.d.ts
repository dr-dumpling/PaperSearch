/**
 * 只为 Markdown 打开文章页：PDF 已从开放来源取得、又要 Markdown 时，经学校订阅下载后端打开文章页、
 * 存下网页（不再下 PDF），交给 step.ts 转换。
 */
import { type SchoolBackend } from "../../../../infrastructure/school/index.js";
import type { DownloadWithFallbackOptions } from "../../types.js";
import type { FulltextPageVisit } from "./step.js";
/**
 * --fulltext for an article whose PDF came from an open stage: a visit for its full-text
 * page alone (no PDF), on a site with page rules (step.ts). Undefined without a
 * backend, or with entitled access turned off.
 */
export declare function fulltextPageVisit(backend: SchoolBackend | undefined, request: Pick<DownloadWithFallbackOptions, "useEntitledAccess" | "batch" | "shortUserWait" | "title" | "school">): FulltextPageVisit | undefined;
//# sourceMappingURL=pageVisit.d.ts.map