export type PublisherApiFormat = "pdf" | "jats-xml";
export type PublisherApiOutcome = {
    kind: "ok";
    path: string;
    format: PublisherApiFormat;
    source: string;
} | {
    kind: "skipped";
    message: string;
} | {
    kind: "error";
    code: string;
    message: string;
};
export interface PublisherApiEnv {
    [key: string]: string | undefined;
}
export interface PublisherApiAdapter {
    /** Stable adapter id, used in attempt messages and file names. */
    id: string;
    /** Config key that must be present for this adapter to run. */
    requiredConfigKey: string;
    matches(doi: string): boolean;
    configured(env: PublisherApiEnv): boolean;
    fetch(doi: string, savePath: string, env: PublisherApiEnv): Promise<PublisherApiOutcome>;
}
export declare function createDefaultPublisherApiAdapters(): PublisherApiAdapter[];
export declare function selectPublisherApiAdapter(doi: string, adapters: readonly PublisherApiAdapter[]): PublisherApiAdapter | undefined;
export { createElsevierAdapter } from "./elsevier.js";
export { createSpringerAdapter } from "./springer.js";
//# sourceMappingURL=index.d.ts.map