import { describe, expect, it } from "@jest/globals";
import {
  normalizeCacheClearResult,
  normalizeDownloadResult,
  SchoolToolResultError,
} from "../../src/capabilities/pdf-discovery/school/SchoolResultNormalizer.js";

describe("SchoolResultNormalizer", () => {
  it("keeps the wait of a rate-limited article as a number, and only there", () => {
    const limited = normalizeDownloadResult(
      textResult({ success: false, error_type: "rate_limited", action: "wait", retry_after_sec: 1234.2 }),
      "10.1016/x",
    );
    expect(limited).toEqual(expect.objectContaining({ code: "rate_limited", retryAfterSec: 1235 }));
    const other = normalizeDownloadResult(
      textResult({ success: false, error_type: "login_timeout", retry_after_sec: 60 }),
      "10.1016/x",
    );
    expect(other).not.toHaveProperty("retryAfterSec");
  });

  it.each([
    [
      "paywall",
      "institution_pdf_entitlement_missing",
      "review_entitlement",
      "entitlement_missing",
    ],
    ["paywall", undefined, "review_entitlement", "paywall"],
    ["entitlement_missing", undefined, "review_entitlement", "paywall"],
    [undefined, undefined, "entitlement_missing", "paywall"],
    [
      "paywall",
      "institution_pdf_entitlement_missing",
      "login_required",
      "login_required",
    ],
    [
      "timeout",
      "institution_pdf_entitlement_missing",
      "review_entitlement",
      "timeout",
    ],
    ["access_blocked", undefined, "review_entitlement", "access_blocked"],
  ])(
    "distinguishes entitlement evidence from %s/%s/%s",
    (error_type, reason_code, action, code) => {
      const result = normalizeDownloadResult(
        textResult({
          success: false,
          error_type,
          reason_code,
          action,
          reason: "cookie=private",
        }),
        "10.1000/example",
      );
      expect(result).toMatchObject({ kind: "attempt_error", code });
      expect(JSON.stringify(result)).not.toContain("private");
    },
  );
  it("preserves a publisher content error without exposing its raw page details", () => {
    const result = normalizeDownloadResult(
      textResult({
        success: false,
        error_type: "publisher_content_error",
        action: "review_publisher_error",
        reason: "https://publisher.example/?token=secret",
        source_failures: [{ reason: "cookie=private" }],
      }),
      "10.1000/example",
    );
    expect(result).toMatchObject({
      kind: "attempt_error",
      code: "publisher_content_error",
    });
    expect(JSON.stringify(result)).not.toMatch(
      /cookie|private|token|secret|https/,
    );
  });
  it("preserves an explicit login action rather than hiding it behind paywall", () => {
    expect(
      normalizeDownloadResult(
        textResult({
          success: false,
          error_type: "paywall",
          action: "login_required",
        }),
        "10.1000/example",
      ),
    ).toMatchObject({ kind: "attempt_error", code: "login_required" });
  });
  it.each([0, 1])(
    "accepts identifier-scoped cache clear count %i",
    (cleared) => {
      expect(() =>
        normalizeCacheClearResult(textResult({ cleared })),
      ).not.toThrow();
    },
  );

  it.each([
    textResult({ cleared: "all" }),
    { isError: true, content: [{ type: "text", text: '{"cleared":1}' }] },
    { content: [{ type: "text", text: "{not-json" }] },
  ])("rejects an invalid cache-clear result", (result) => {
    expect(() => normalizeCacheClearResult(result)).toThrow(
      expect.objectContaining({ code: "cache_clear_failed" }),
    );
  });

  it("requires success=true and a non-empty file for download success", () => {
    expect(
      normalizeDownloadResult(
        textResult({
          success: true,
          file: "/tmp/paper.pdf",
          source: "Future Source",
        }),
        "10.1000/example",
      ),
    ).toEqual({
      kind: "success",
      identifier: "10.1000/example",
      path: "/tmp/paper.pdf",
      source: "Future Source",
    });

    expect(() =>
      normalizeDownloadResult(
        textResult({ success: true, file: "" }),
        "10.1000/example",
      ),
    ).toThrow(expect.objectContaining({ code: "invalid_download_result" }));
  });

  it("does not turn a failure carrying file/source into success", () => {
    const outcome = normalizeDownloadResult(
      textResult({
        success: false,
        file: "/tmp/suspicious-preview.pdf",
        source: "Publisher Preview",
        error_type: "suspicious_pdf",
        reason: "preview only",
      }),
      "10.1000/example",
    );

    expect(outcome).toEqual({
      kind: "attempt_error",
      identifier: "10.1000/example",
      code: "suspicious_pdf",
      message: "School backend did not return a usable PDF (suspicious_pdf).",
    });
  });

  it.each([{}, { success: null }, { success: "true" }, { success: 1 }])(
    "rejects an invalid success value %#",
    (payload) => {
      let thrown: unknown = undefined;
      try {
        normalizeDownloadResult(textResult(payload), "10.1000/example");
      } catch (error) {
        thrown = error;
      }

      expect(thrown).toBeInstanceOf(SchoolToolResultError);
      expect(thrown).toMatchObject({ code: "invalid_download_result" });
    },
  );

  it("ignores raw hints and URLs in business failures", () => {
    const outcome = normalizeDownloadResult(
      textResult({
        success: false,
        error_type: "paywall",
        reason: "https://publisher.example/login?token=secret",
        agent_hint: "cookie=session-secret",
      }),
      "10.1000/example",
    );

    expect(outcome).toEqual(
      expect.objectContaining({ kind: "attempt_error", code: "paywall" }),
    );
    expect(JSON.stringify(outcome)).not.toMatch(
      /https?:\/\/|token|cookie|session-secret/i,
    );
  });

  const sensitiveFailureValues: Array<["error_type" | "action", string]> = [
    ["error_type", "token"],
    ["action", "bearer"],
    ["error_type", "authorization"],
    ["action", "api_key"],
    ["error_type", "ticket"],
    ["action", "https://publisher.example/login?token=raw-secret"],
    ["error_type", "/Users/example/.school/private/session.json"],
    ["action", ["sk", "live", "51RawCredentialValue"].join("_")],
    ["error_type", "sk-proj-abcdefghijklmnopqrstuv"],
    ["action", "sk-ant-api03-abcdefghijklmnopqrstuv"],
    ["error_type", "glpat-abcdefghijklmnopqrstuv"],
    ["action", "AIzaSyDabcdefghijklmnopqrstuv"],
    ["error_type", "npm_abcdefghijklmnopqrstuv"],
    ["action", "publisher.example.com"],
    ["error_type", "192.0.2.10"],
    ["action", "localhost"],
    ["error_type", "sk-1234567890abcdefghijklmnop"],
    ["action", ["rk", "live", "1234567890abcdefghijklmnop"].join("_")],
    ["error_type", ["rk", "test", "1234567890abcdefghijklmnop"].join("_")],
    ["action", "whsec_1234567890abcdefghijklmnop"],
    ["error_type", "vendor_1234567890abcdefghijklmnop"],
    ["action", "0123456789abcdef0123456789abcdef"],
    ["error_type", "550e8400-e29b-41d4-a716-446655440000"],
    ["action", "aB3dE5fG7hJ9kL2mN4pQ6rS8"],
    ["error_type", "123456789012345678901234"],
  ];

  it.each(sensitiveFailureValues)(
    "does not propagate a sensitive %s failure value",
    (field, sensitiveValue) => {
      const outcome = normalizeDownloadResult(
        textResult({ success: false, [field]: sensitiveValue }),
        "10.1000/example",
      );
      const serialized = JSON.stringify(outcome).toLowerCase();

      expect(outcome).toEqual({
        kind: "attempt_error",
        identifier: "10.1000/example",
        code: "download_failed",
        message: "School backend did not return a usable PDF (download_failed).",
      });
      expect(serialized).not.toContain(sensitiveValue.toLowerCase());
    },
  );

  it.each([
    "token",
    "Bearer raw-bearer-value",
    "authorization=Basic raw-authorization-value",
    "api_key=raw-api-key-value",
    "ticket=TGT-raw-ticket-value",
    "https://publisher.example/download?token=raw-secret",
    "/Users/example/.school/private/source.json",
    ["sk", "live", "51RawCredentialValue"].join("_"),
    "sk-proj-abcdefghijklmnopqrstuv",
    "sk-ant-api03-abcdefghijklmnopqrstuv",
    "glpat-abcdefghijklmnopqrstuv",
    "AIzaSyDabcdefghijklmnopqrstuv",
    "npm_abcdefghijklmnopqrstuv",
    "publisher.example.com",
    "192.0.2.10",
    "localhost:4312",
    "sk-1234567890abcdefghijklmnop",
    ["rk", "live", "1234567890abcdefghijklmnop"].join("_"),
    ["rk", "test", "1234567890abcdefghijklmnop"].join("_"),
    "whsec_1234567890abcdefghijklmnop",
    "vendor_1234567890abcdefghijklmnop",
    "0123456789abcdef0123456789abcdef",
    "550e8400-e29b-41d4-a716-446655440000",
    "aB3dE5fG7hJ9kL2mN4pQ6rS8",
    "123456789012345678901234",
  ])("omits a sensitive success source: %s", (sensitiveSource) => {
    const outcome = normalizeDownloadResult(
      textResult({
        success: true,
        file: "/tmp/paper.pdf",
        source: sensitiveSource,
      }),
      "10.1000/example",
    );
    const serialized = JSON.stringify(outcome).toLowerCase();

    expect(outcome).toEqual({
      kind: "success",
      identifier: "10.1000/example",
      path: "/tmp/paper.pdf",
    });
    expect(serialized).not.toContain(sensitiveSource.toLowerCase());
  });

  it("does not fall through from a sensitive error_type to a safe action", () => {
    const outcome = normalizeDownloadResult(
      textResult({
        success: false,
        error_type: "token",
        action: "login_required",
      }),
      "10.1000/example",
    );

    expect(outcome).toEqual({
      kind: "attempt_error",
      identifier: "10.1000/example",
      code: "download_failed",
      message: "School backend did not return a usable PDF (download_failed).",
    });
  });

  it("keeps the safe login_required action code", () => {
    expect(
      normalizeDownloadResult(
        textResult({ success: false, action: "login_required" }),
        "10.1000/example",
      ),
    ).toEqual({
      kind: "attempt_error",
      identifier: "10.1000/example",
      code: "login_required",
      message: "School backend did not return a usable PDF (login_required).",
    });
  });

  it.each([
    {
      isError: true,
      content: [{ type: "text", text: '{"success":true,"file":"/tmp/a.pdf"}' }],
    },
    {
      content: [
        { type: "text", text: '{"success":true}' },
        { type: "text", text: '{"file":"/tmp/a.pdf"}' },
      ],
    },
    { content: [{ type: "image", data: "ignored", mimeType: "image/png" }] },
    { structuredContent: { success: true, file: "/tmp/a.pdf" } },
    { content: [{ type: "text", text: "{not-json" }] },
  ])("rejects non-unique or malformed MCP content", (result) => {
    expect(() => normalizeDownloadResult(result, "10.1000/example")).toThrow(
      expect.objectContaining({ code: "invalid_download_result" }),
    );
  });
});

function textResult(payload: Record<string, unknown>) {
  return {
    content: [{ type: "text", text: JSON.stringify(payload) }],
  };
}
