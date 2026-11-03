import { z } from "zod";
import { isKnownSearchPlatform } from "../../registry/platformMetadata.js";
export const DownloadPaperSchema = z
    .object({
    paperId: z.coerce.string().min(1),
    platform: z.coerce
        .string()
        .min(1)
        .refine((value) => isKnownSearchPlatform(value), {
        message: "Unsupported download platform",
    }),
    savePath: z.coerce.string().optional(),
    useEntitledAccess: z.boolean().optional().default(true),
})
    .strip();
const DownloadBatchPositionSchema = z
    .object({
    id: z.string().trim().min(1).max(128),
    index: z.number().int().min(1),
    total: z.number().int().min(1).max(100_000),
    done: z.number().int().min(0).optional(),
    succeeded: z.number().int().min(0).optional(),
    failed: z.number().int().min(0).optional(),
})
    .strip()
    .refine((batch) => batch.index <= batch.total, {
    message: "batch.index must not exceed batch.total",
})
    .transform((batch) => ({
    ...batch,
    done: batch.done ?? batch.index - 1,
    succeeded: batch.succeeded ?? 0,
    failed: batch.failed ?? 0,
}));
export const DownloadWithFallbackSchema = z
    .object({
    source: z.coerce.string().min(1),
    paperId: z.coerce.string().min(1),
    doi: z.coerce.string().optional().default(""),
    title: z.coerce.string().optional().default(""),
    savePath: z.coerce.string().optional(),
    useEntitledAccess: z.boolean().optional().default(true),
    useSciHub: z.boolean().optional().default(true),
    content: z.enum(["main", "supplements", "both"]).optional().default("main"),
    batch: DownloadBatchPositionSchema.optional(),
})
    .strip();
export const DownloadBatchSchema = z
    .object({
    items: z
        .array(z
        .object({
        source: z.coerce.string().optional(),
        paperId: z.coerce.string().optional(),
        doi: z.coerce.string().optional(),
        title: z.coerce.string().optional(),
        savePath: z.coerce.string().optional(),
    })
        .strip()
        .refine((item) => !!(item.doi?.trim() || item.paperId?.trim()), {
        message: "Each item needs a doi or paperId",
    }))
        .min(1)
        .max(1000),
    savePath: z.coerce.string().optional(),
    useEntitledAccess: z.boolean().optional().default(true),
    useSciHub: z.boolean().optional().default(true),
    content: z.enum(["main", "supplements", "both"]).optional().default("main"),
    mode: z.enum(["two_phase", "per_item", "entitled_only"]).optional().default("two_phase"),
})
    .strip();
//# sourceMappingURL=schemas.js.map