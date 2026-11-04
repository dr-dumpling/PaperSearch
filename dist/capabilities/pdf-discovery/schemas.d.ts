import { z } from "zod";
export declare const DownloadPaperSchema: z.ZodObject<{
    paperId: z.ZodString;
    platform: z.ZodEffects<z.ZodString, string, string>;
    savePath: z.ZodOptional<z.ZodString>;
    useEntitledAccess: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
}, "strip", z.ZodTypeAny, {
    paperId: string;
    platform: string;
    useEntitledAccess: boolean;
    savePath?: string | undefined;
}, {
    paperId: string;
    platform: string;
    savePath?: string | undefined;
    useEntitledAccess?: boolean | undefined;
}>;
export declare const DownloadWithFallbackSchema: z.ZodObject<{
    source: z.ZodString;
    paperId: z.ZodString;
    doi: z.ZodDefault<z.ZodOptional<z.ZodString>>;
    title: z.ZodDefault<z.ZodOptional<z.ZodString>>;
    savePath: z.ZodOptional<z.ZodString>;
    useEntitledAccess: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
    useSciHub: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
    content: z.ZodDefault<z.ZodOptional<z.ZodEnum<["main", "supplements", "both"]>>>;
    batch: z.ZodOptional<z.ZodEffects<z.ZodEffects<z.ZodObject<{
        id: z.ZodString;
        index: z.ZodNumber;
        total: z.ZodNumber;
        done: z.ZodOptional<z.ZodNumber>;
        succeeded: z.ZodOptional<z.ZodNumber>;
        failed: z.ZodOptional<z.ZodNumber>;
    }, "strip", z.ZodTypeAny, {
        id: string;
        index: number;
        total: number;
        done?: number | undefined;
        failed?: number | undefined;
        succeeded?: number | undefined;
    }, {
        id: string;
        index: number;
        total: number;
        done?: number | undefined;
        failed?: number | undefined;
        succeeded?: number | undefined;
    }>, {
        id: string;
        index: number;
        total: number;
        done?: number | undefined;
        failed?: number | undefined;
        succeeded?: number | undefined;
    }, {
        id: string;
        index: number;
        total: number;
        done?: number | undefined;
        failed?: number | undefined;
        succeeded?: number | undefined;
    }>, {
        done: number;
        succeeded: number;
        failed: number;
        id: string;
        index: number;
        total: number;
    }, {
        id: string;
        index: number;
        total: number;
        done?: number | undefined;
        failed?: number | undefined;
        succeeded?: number | undefined;
    }>>;
}, "strip", z.ZodTypeAny, {
    paperId: string;
    title: string;
    source: string;
    doi: string;
    content: "main" | "supplements" | "both";
    useEntitledAccess: boolean;
    useSciHub: boolean;
    savePath?: string | undefined;
    batch?: {
        done: number;
        succeeded: number;
        failed: number;
        id: string;
        index: number;
        total: number;
    } | undefined;
}, {
    paperId: string;
    source: string;
    title?: string | undefined;
    doi?: string | undefined;
    content?: "main" | "supplements" | "both" | undefined;
    savePath?: string | undefined;
    useEntitledAccess?: boolean | undefined;
    useSciHub?: boolean | undefined;
    batch?: {
        id: string;
        index: number;
        total: number;
        done?: number | undefined;
        failed?: number | undefined;
        succeeded?: number | undefined;
    } | undefined;
}>;
export declare const DownloadBatchSchema: z.ZodObject<{
    items: z.ZodArray<z.ZodEffects<z.ZodObject<{
        source: z.ZodOptional<z.ZodString>;
        paperId: z.ZodOptional<z.ZodString>;
        doi: z.ZodOptional<z.ZodString>;
        title: z.ZodOptional<z.ZodString>;
        savePath: z.ZodOptional<z.ZodString>;
    }, "strip", z.ZodTypeAny, {
        paperId?: string | undefined;
        title?: string | undefined;
        source?: string | undefined;
        doi?: string | undefined;
        savePath?: string | undefined;
    }, {
        paperId?: string | undefined;
        title?: string | undefined;
        source?: string | undefined;
        doi?: string | undefined;
        savePath?: string | undefined;
    }>, {
        paperId?: string | undefined;
        title?: string | undefined;
        source?: string | undefined;
        doi?: string | undefined;
        savePath?: string | undefined;
    }, {
        paperId?: string | undefined;
        title?: string | undefined;
        source?: string | undefined;
        doi?: string | undefined;
        savePath?: string | undefined;
    }>, "many">;
    savePath: z.ZodOptional<z.ZodString>;
    useEntitledAccess: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
    useSciHub: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
    content: z.ZodDefault<z.ZodOptional<z.ZodEnum<["main", "supplements", "both"]>>>;
    mode: z.ZodDefault<z.ZodOptional<z.ZodEnum<["two_phase", "per_item", "entitled_only"]>>>;
}, "strip", z.ZodTypeAny, {
    items: {
        paperId?: string | undefined;
        title?: string | undefined;
        source?: string | undefined;
        doi?: string | undefined;
        savePath?: string | undefined;
    }[];
    mode: "two_phase" | "per_item" | "entitled_only";
    content: "main" | "supplements" | "both";
    useEntitledAccess: boolean;
    useSciHub: boolean;
    savePath?: string | undefined;
}, {
    items: {
        paperId?: string | undefined;
        title?: string | undefined;
        source?: string | undefined;
        doi?: string | undefined;
        savePath?: string | undefined;
    }[];
    mode?: "two_phase" | "per_item" | "entitled_only" | undefined;
    content?: "main" | "supplements" | "both" | undefined;
    savePath?: string | undefined;
    useEntitledAccess?: boolean | undefined;
    useSciHub?: boolean | undefined;
}>;
//# sourceMappingURL=schemas.d.ts.map