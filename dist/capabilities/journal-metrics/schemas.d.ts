import { z } from 'zod';
export declare const QueryJournalMetricsSchema: z.ZodEffects<z.ZodObject<{
    journal: z.ZodOptional<z.ZodString>;
    journals: z.ZodOptional<z.ZodUnion<[z.ZodString, z.ZodArray<z.ZodString, "many">]>>;
    file: z.ZodOptional<z.ZodString>;
    includeRaw: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
}, "strip", z.ZodTypeAny, {
    includeRaw: boolean;
    journal?: string | undefined;
    file?: string | undefined;
    journals?: string | string[] | undefined;
}, {
    journal?: string | undefined;
    file?: string | undefined;
    journals?: string | string[] | undefined;
    includeRaw?: boolean | undefined;
}>, {
    includeRaw: boolean;
    journal?: string | undefined;
    file?: string | undefined;
    journals?: string | string[] | undefined;
}, {
    journal?: string | undefined;
    file?: string | undefined;
    journals?: string | string[] | undefined;
    includeRaw?: boolean | undefined;
}>;
//# sourceMappingURL=schemas.d.ts.map