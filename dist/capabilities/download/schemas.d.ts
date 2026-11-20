import { z } from "zod";
import type { DownloadContent } from "./types.js";
export declare const DownloadPaperSchema: z.ZodEffects<z.ZodObject<{
    paperId: z.ZodString;
    platform: z.ZodEffects<z.ZodString, string, string>;
    savePath: z.ZodOptional<z.ZodString>;
    useEntitledAccess: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
    content: z.ZodOptional<z.ZodUnion<[z.ZodString, z.ZodArray<z.ZodString, "many">]>>;
    markdown: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
}, "strip", z.ZodTypeAny, {
    paperId: string;
    markdown: boolean;
    platform: string;
    useEntitledAccess: boolean;
    savePath?: string | undefined;
    content?: string | string[] | undefined;
}, {
    paperId: string;
    platform: string;
    markdown?: boolean | undefined;
    savePath?: string | undefined;
    useEntitledAccess?: boolean | undefined;
    content?: string | string[] | undefined;
}>, Omit<{
    paperId: string;
    markdown: boolean;
    platform: string;
    useEntitledAccess: boolean;
    savePath?: string | undefined;
    content?: string | string[] | undefined;
}, "markdown" | "content"> & {
    content: DownloadContent;
    fulltext: boolean;
}, {
    paperId: string;
    platform: string;
    markdown?: boolean | undefined;
    savePath?: string | undefined;
    useEntitledAccess?: boolean | undefined;
    content?: string | string[] | undefined;
}>;
export declare const DownloadWithFallbackSchema: z.ZodEffects<z.ZodObject<{
    source: z.ZodString;
    paperId: z.ZodString;
    doi: z.ZodDefault<z.ZodOptional<z.ZodString>>;
    title: z.ZodDefault<z.ZodOptional<z.ZodString>>;
    savePath: z.ZodOptional<z.ZodString>;
    useEntitledAccess: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
    useSciHub: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
    content: z.ZodOptional<z.ZodUnion<[z.ZodString, z.ZodArray<z.ZodString, "many">]>>;
    markdown: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
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
    markdown: boolean;
    useEntitledAccess: boolean;
    useSciHub: boolean;
    savePath?: string | undefined;
    content?: string | string[] | undefined;
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
    markdown?: boolean | undefined;
    savePath?: string | undefined;
    useEntitledAccess?: boolean | undefined;
    content?: string | string[] | undefined;
    useSciHub?: boolean | undefined;
    batch?: {
        id: string;
        index: number;
        total: number;
        done?: number | undefined;
        failed?: number | undefined;
        succeeded?: number | undefined;
    } | undefined;
}>, Omit<{
    paperId: string;
    title: string;
    source: string;
    doi: string;
    markdown: boolean;
    useEntitledAccess: boolean;
    useSciHub: boolean;
    savePath?: string | undefined;
    content?: string | string[] | undefined;
    batch?: {
        done: number;
        succeeded: number;
        failed: number;
        id: string;
        index: number;
        total: number;
    } | undefined;
}, "markdown" | "content"> & {
    content: DownloadContent;
    fulltext: boolean;
}, {
    paperId: string;
    source: string;
    title?: string | undefined;
    doi?: string | undefined;
    markdown?: boolean | undefined;
    savePath?: string | undefined;
    useEntitledAccess?: boolean | undefined;
    content?: string | string[] | undefined;
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
export declare const DownloadBatchSchema: z.ZodEffects<z.ZodEffects<z.ZodObject<{
    items: z.ZodDefault<z.ZodOptional<z.ZodArray<z.ZodEffects<z.ZodObject<{
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
    }>, "many">>>;
    resume: z.ZodOptional<z.ZodString>;
    markdownAgain: z.ZodOptional<z.ZodEnum<["possibly_short"]>>;
    savePath: z.ZodOptional<z.ZodString>;
    folderName: z.ZodOptional<z.ZodString>;
    school: z.ZodOptional<z.ZodString>;
    useEntitledAccess: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
    useSciHub: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
    content: z.ZodOptional<z.ZodUnion<[z.ZodString, z.ZodArray<z.ZodString, "many">]>>;
    markdown: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
    mode: z.ZodOptional<z.ZodEnum<["two_phase", "per_item", "entitled_only"]>>;
}, "strip", z.ZodTypeAny, {
    items: {
        paperId?: string | undefined;
        title?: string | undefined;
        source?: string | undefined;
        doi?: string | undefined;
        savePath?: string | undefined;
    }[];
    markdown: boolean;
    useEntitledAccess: boolean;
    useSciHub: boolean;
    savePath?: string | undefined;
    content?: string | string[] | undefined;
    folderName?: string | undefined;
    school?: string | undefined;
    mode?: "two_phase" | "per_item" | "entitled_only" | undefined;
    resume?: string | undefined;
    markdownAgain?: "possibly_short" | undefined;
}, {
    items?: {
        paperId?: string | undefined;
        title?: string | undefined;
        source?: string | undefined;
        doi?: string | undefined;
        savePath?: string | undefined;
    }[] | undefined;
    markdown?: boolean | undefined;
    savePath?: string | undefined;
    useEntitledAccess?: boolean | undefined;
    content?: string | string[] | undefined;
    useSciHub?: boolean | undefined;
    folderName?: string | undefined;
    school?: string | undefined;
    mode?: "two_phase" | "per_item" | "entitled_only" | undefined;
    resume?: string | undefined;
    markdownAgain?: "possibly_short" | undefined;
}>, {
    items: {
        paperId?: string | undefined;
        title?: string | undefined;
        source?: string | undefined;
        doi?: string | undefined;
        savePath?: string | undefined;
    }[];
    markdown: boolean;
    useEntitledAccess: boolean;
    useSciHub: boolean;
    savePath?: string | undefined;
    content?: string | string[] | undefined;
    folderName?: string | undefined;
    school?: string | undefined;
    mode?: "two_phase" | "per_item" | "entitled_only" | undefined;
    resume?: string | undefined;
    markdownAgain?: "possibly_short" | undefined;
}, {
    items?: {
        paperId?: string | undefined;
        title?: string | undefined;
        source?: string | undefined;
        doi?: string | undefined;
        savePath?: string | undefined;
    }[] | undefined;
    markdown?: boolean | undefined;
    savePath?: string | undefined;
    useEntitledAccess?: boolean | undefined;
    content?: string | string[] | undefined;
    useSciHub?: boolean | undefined;
    folderName?: string | undefined;
    school?: string | undefined;
    mode?: "two_phase" | "per_item" | "entitled_only" | undefined;
    resume?: string | undefined;
    markdownAgain?: "possibly_short" | undefined;
}>, Omit<{
    items: {
        paperId?: string | undefined;
        title?: string | undefined;
        source?: string | undefined;
        doi?: string | undefined;
        savePath?: string | undefined;
    }[];
    markdown: boolean;
    useEntitledAccess: boolean;
    useSciHub: boolean;
    savePath?: string | undefined;
    content?: string | string[] | undefined;
    folderName?: string | undefined;
    school?: string | undefined;
    mode?: "two_phase" | "per_item" | "entitled_only" | undefined;
    resume?: string | undefined;
    markdownAgain?: "possibly_short" | undefined;
}, "markdown" | "content"> & {
    content: DownloadContent;
    fulltext: boolean;
}, {
    items?: {
        paperId?: string | undefined;
        title?: string | undefined;
        source?: string | undefined;
        doi?: string | undefined;
        savePath?: string | undefined;
    }[] | undefined;
    markdown?: boolean | undefined;
    savePath?: string | undefined;
    useEntitledAccess?: boolean | undefined;
    content?: string | string[] | undefined;
    useSciHub?: boolean | undefined;
    folderName?: string | undefined;
    school?: string | undefined;
    mode?: "two_phase" | "per_item" | "entitled_only" | undefined;
    resume?: string | undefined;
    markdownAgain?: "possibly_short" | undefined;
}>;
//# sourceMappingURL=schemas.d.ts.map