import { z } from "zod";
import { proFeatures } from "../../config/edition.js";
import { isKnownSearchPlatform } from "../../registry/platformMetadata.js";
import type { DownloadContent } from "./types.js";

const CONTENT_KINDS = ["pdf", "supplements", "markdown"] as const;
type ContentKind = (typeof CONTENT_KINDS)[number];

/**
 * ``content`` as the kinds asked for, each fetched on its own, in any combination (user,
 * 2026-11-14): pdf (the main text's PDF), supplements, markdown (the full-text package
 * with article.md), or several together ("supplements,markdown", or a list). The
 * caller (the AI) picks them; 0.6's main and both are gone with them. Read into the
 * download's content (main, supplements, both or markdown) and whether the Markdown is
 * made too; ``markdown: true`` adds it to whatever else is asked for. Without PaperSearch Pro's
 * features (config/edition.ts) there is no markdown kind and no ``markdown``.
 */
function readContent<T extends { content?: string | string[]; markdown?: boolean }>(
  value: T, ctx: z.RefinementCtx, offered: readonly ContentKind[] = CONTENT_KINDS,
): Omit<T, "content" | "markdown"> & { content: DownloadContent; fulltext: boolean } {
  const pro = proFeatures();
  const allowed = pro ? offered : offered.filter((kind) => kind !== "markdown");
  const example = allowed.length < 2 ? "" : allowed.includes("markdown")
    ? (allowed.includes("supplements") ? "supplements,markdown" : "pdf,markdown") : "pdf,supplements";
  const words = (Array.isArray(value.content) ? value.content : [value.content ?? ""])
    .flatMap((part) => String(part).toLowerCase().split(/[\s,+]+/))
    .filter(Boolean);
  const kinds = new Set<ContentKind>();
  for (const word of words) {
    if ((allowed as readonly string[]).includes(word)) kinds.add(word as ContentKind);
    else ctx.addIssue({ code: "custom", path: ["content"],
      message: example ? `content: ${allowed.join(", ")} or several of them such as "${example}"` : `content: ${allowed.join(", ")}` });
  }
  if (!pro && value.markdown === true) {
    ctx.addIssue({ code: "custom", path: ["markdown"], message: "markdown: not offered by this version" });
  }
  const { markdown: alsoMarkdown, ...rest } = value;
  const markdown = alsoMarkdown === true || kinds.has("markdown");
  const pdf = kinds.has("pdf") || (!kinds.has("supplements") && !kinds.has("markdown"));
  const content: DownloadContent = pdf && kinds.has("supplements") ? "both"
    : pdf ? "main" : kinds.has("supplements") ? "supplements" : "markdown";
  return { ...(rest as Omit<T, "content" | "markdown">), content, fulltext: markdown };
}

const ContentField = z.union([z.string(), z.array(z.string())]).optional();

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
    // pdf or markdown (no supplementary files here: download_with_fallback).
    content: ContentField,
    markdown: z.boolean().optional().default(false),
  })
  .strip()
  .transform((value, ctx) => readContent(value, ctx, ["pdf", "markdown"]));

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
    content: ContentField,
    markdown: z.boolean().optional().default(false),
    batch: DownloadBatchPositionSchema.optional(),
  })
  .strip()
  .transform((value, ctx) => readContent(value, ctx));

export const DownloadBatchSchema = z
  .object({
    items: z
      .array(
        z
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
          }),
      )
      .optional()
      .default([]),
    resume: z.coerce.string().optional(),
    // With resume: "possibly_short" also makes again the Markdown saved with a note of what it may
    // lack (possiblyMissing), e.g. after rules were fixed (user, 2026-11-18).
    markdownAgain: z.enum(["possibly_short"]).optional(),
    savePath: z.coerce.string().optional(),
    folderName: z.coerce.string().optional(),
    school: z.coerce.string().max(200).optional(),
    useEntitledAccess: z.boolean().optional().default(true),
    useSciHub: z.boolean().optional().default(true),
    content: ContentField,
    markdown: z.boolean().optional().default(false),
    // Unset means two_phase (batch.ts); 接着下 then goes on as the batch went (resume.ts).
    mode: z.enum(["two_phase", "per_item", "entitled_only"]).optional(),
  })
  .strip()
  .refine((args) => args.items.length > 0 || !!args.resume?.trim(), { message: "items (at least one) or resume is required" })
  .transform((value, ctx) => readContent(value, ctx));
