import { mkdtempSync, writeFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import { createEntitledAccessTier } from "../../src/capabilities/pdf-discovery/tiers/entitledAccess.js";
import type { CarsiBackend } from "../../src/capabilities/pdf-discovery/carsi/index.js";
import { normalizeDownloadResult } from "../../src/capabilities/pdf-discovery/carsi/CarsiResultNormalizer.js";
import type { DownloadTierContext } from "../../src/capabilities/pdf-discovery/DownloadTier.js";
import { textPdf } from "../fixtures/textPdf.js";

describe("Entitled PDF acceptance", () => {
  let directory: string;
  let context: DownloadTierContext;
  beforeEach(() => {
    directory = mkdtempSync(
      join(tmpdir(), "paper-search-entitled-acceptance-"),
    );
    context = {
      searchers: {} as any,
      source: "crossref",
      paperId: "10.1000/target",
      title: "Nutrition and health",
      savePath: directory,
      useEntitledAccess: true,
      useSciHub: false,
    };
  });
  afterEach(() => {
    rmSync(directory, { recursive: true, force: true });
  });

  it.each([
    ["10.1000/other", "pdf_identity_mismatch"],
    ["", "pdf_identity_unverified"],
  ])(
    "retains but rejects a file with article DOI %s",
    async (articleDoi, code) => {
      const path = join(directory, "paper.pdf");
      writeFileSync(
        path,
        textPdf([
          // Another article's front page, or a page that names no article.
          articleDoi
            ? ["Another article", `doi:${articleDoi}`]
            : ["A document without identifiers"],
          ["References", "doi:10.1000/target"],
        ]),
      );
      const backend = {
        downloadLegalDoi: jest.fn(async () => ({
          kind: "success",
          identifier: context.paperId,
          path,
        })),
      } as unknown as CarsiBackend;
      const result = await createEntitledAccessTier(backend).run(context);
      expect(result).toMatchObject({
        status: "error",
        code,
        review: { path, reason: code },
      });
      expect(result.path).toBeUndefined();
      expect(existsSync(path)).toBe(true);
    },
  );

  it.each([
    "login_required",
    "paywall",
    "entitlement_missing",
    "cloudflare_blocked",
    "download_timeout",
    "browser_operation_timeout",
    "batch_stopped",
    "profile_busy",
    "publisher_content_error",
    "access_blocked",
    "source_exception",
  ])("preserves actionable %s without raw backend hints", async (code) => {
    const backend = {
      downloadLegalDoi: jest.fn(async () => ({
        kind: "attempt_error",
        identifier: context.paperId,
        code,
        message: "cookie=private https://example.org/?token=private",
      })),
    } as unknown as CarsiBackend;
    const result = await createEntitledAccessTier(backend).run(context);
    expect(result).toMatchObject({ status: "error", code });
    expect(JSON.stringify(result)).not.toMatch(/cookie|token|private|https/);
  });

  it.each([
    ["login_timeout", "登录超时"],
    ["login_page_closed", "页面已关闭"],
    ["login_credentials_rejected", "凭证被拒绝"],
    ["login_retries_exhausted", "重试次数已用尽"],
    ["institution_not_registered", "认证应用或入口未注册"],
    ["generic_institution_entry_missing", "按通用规则没有找到机构登录入口"],
    ["unsupported_publisher", "没有指向 PaperSearch 能登录的出版社网站"],
  ])(
    "preserves %s from MCP JSON through normalization and the tier",
    async (code, message) => {
      const payload = {
        success: false,
        error_type: code,
        action: "review_browser",
        reason: "cookie=private https://example.org/?token=private",
        reason_code: "institution_pdf_entitlement_missing",
        agent_hint: "private raw backend error",
        source_failures: [{ reason: "private raw exception" }],
      };
      const backend = {
        downloadLegalDoi: jest.fn(async () =>
          normalizeDownloadResult(
            { content: [{ type: "text", text: JSON.stringify(payload) }] },
            context.paperId,
          ),
        ),
      } as unknown as CarsiBackend;
      const result = await createEntitledAccessTier(backend).run(context);
      expect(result).toMatchObject({ status: "error", code });
      expect(result.message).toContain(message);
      expect(result.path).toBeUndefined();
      expect(JSON.stringify(result)).not.toMatch(
        /cookie|token|private|https|entitlement_missing/,
      );
    },
  );

  it.each([
    ["uis.example.edu.cn", "（uis.example.edu.cn）"],
    ["uis.example.edu.cn/?token=private", "（学校的网站）"],
  ])("names the school's site a login stopped on, a host name only: %s", async (host, shown) => {
    const payload = {
      success: false,
      error_type: "idp_no_return_to_publisher",
      action: "review_browser",
      artifacts: { driver: "publisher", state: "idp_no_return_to_publisher", stopped_host: host },
    };
    const backend = {
      downloadLegalDoi: jest.fn(async () =>
        normalizeDownloadResult({ content: [{ type: "text", text: JSON.stringify(payload) }] }, context.paperId),
      ),
    } as unknown as CarsiBackend;
    const result = await createEntitledAccessTier(backend).run(context);
    expect(result).toMatchObject({ status: "error", code: "idp_no_return_to_publisher" });
    expect(result.message).toContain(shown);
    expect(result.message).toContain("没有回到出版社");
    expect(JSON.stringify(result)).not.toMatch(/token|private/);
  });

  it.each([
    { error_type: "login_page_closed_unknown", action: "review_browser" },
    { error_type: "__proto__", action: "review_browser" },
    { error_type: "download_failed", action: "review_browser" },
  ])(
    "does not infer a login or entitlement diagnosis from reason text: %j",
    async (fields) => {
      const backend = {
        downloadLegalDoi: jest.fn(async () =>
          normalizeDownloadResult(
            {
              content: [{
                type: "text",
                text: JSON.stringify({
                  success: false,
                  ...fields,
                  reason: "login_page_closed institution_pdf_entitlement_missing cookie=private",
                }),
              }],
            },
            context.paperId,
          ),
        ),
      } as unknown as CarsiBackend;
      expect(await createEntitledAccessTier(backend).run(context)).toMatchObject({
        status: "error",
        code: "download_failed",
      });
    },
  );
});
