export declare function pmcidForDoi(doi: string, timeoutMs: number): Promise<string>;
export declare function downloadPmcPdf(pmcid: string, savePath: string, timeoutMs: number): Promise<{
    path: string;
    via: "pmc_cloud" | "europepmc";
} | null>;
//# sourceMappingURL=pmcCloud.d.ts.map