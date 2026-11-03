import { describe, expect, it } from "@jest/globals";
import { classifyFailureCode, describeFailure } from "../../src/infrastructure/runlog/failureClass.js";

const diagnostic = (fields: Record<string, unknown>) => ({ diagnostic: { file: "/x/diagnostic.json", ...fields } });

describe("failure classes (ADR 0012)", () => {
  it("puts each code in one class, and anything unknown in unexplained", () => {
    expect(classifyFailureCode("entitlement_missing")).toBe("no_access");
    expect(classifyFailureCode("institution_federation_unavailable")).toBe("no_access");
    expect(classifyFailureCode("no_entitlement")).toBe("no_access");
    expect(classifyFailureCode("user_skipped")).toBe("user_or_external");
    expect(classifyFailureCode("profile_busy")).toBe("user_or_external");
    expect(classifyFailureCode("idp_no_return_to_publisher")).toBe("user_or_external");
    expect(classifyFailureCode("unsupported_platform")).toBe("unsupported");
    expect(classifyFailureCode("unsupported_publisher")).toBe("unsupported");
    expect(classifyFailureCode("generic_institution_entry_missing")).toBe("unsupported");
    for (const code of ["download_failed", "download_timeout", "login_not_reached", "login_required",
      "source_exception", "pdf_identity_unverified", "pdf_wrong_article", undefined, "toString"]) {
      expect(classifyFailureCode(code)).toBe("unexplained");
    }
  });

  it("counts a login timeout as the user's only when the record says it ended on a page for the user", () => {
    const ended = diagnostic({ events: [{ state: "login_wait_ended", detail: "school_login" }] });
    expect(describeFailure("login_timeout", ended).failureClass).toBe("user_or_external");
    // Neurological Research before the fix: the wait ran out on the article; older records cannot tell.
    const old = diagnostic({ events: [{ state: "sso_entry_clicked" }, { state: "login_state", detail: "MRI markers | https://www.tandfonline.com/doi/full/x" }, { state: "user_wait_expired" }] });
    expect(describeFailure("login_timeout", old)).toEqual({ failureClass: "unexplained", stoppedAt: "user_wait_expired" });
  });

  it("keeps the evidence for no access", () => {
    const denied = diagnostic({ access_evidence: ["Access provided by Hong Mu-lan University", "Hong Mu-lan University does not subscribe to this content"] });
    expect(describeFailure("entitlement_missing", denied)).toEqual({
      failureClass: "no_access", evidence: "Hong Mu-lan University does not subscribe to this content",
    });
    const sage = diagnostic({ events: [
      { state: "auto_institution_not_found", detail: "Hong Mu-lan @ https://journals.sagepub.com/action/ssostart?redirectUri=x" },
      { state: "auto_institution_not_found", detail: "Hong Mu-lan @ https://login.openathens.net/auth?t=x" },
      { state: "institution_federation_unavailable" },
    ] });
    expect(describeFailure("institution_federation_unavailable", sage).evidence).toBe("机构列表里找不到 Hong Mu-lan（login.openathens.net）");
    expect(describeFailure("no_entitlement").evidence).toBe("你标记过该期刊或出版社无权限");
    // ScienceDirect's own check decided; the backend keeps the page's words as an event.
    const sciencedirect = diagnostic({ access_evidence: ["Brought to you by:Hong Mu-Lan University"], events: [
      { state: "entitlement_denied", detail: "Hong Mu-lan University does not subscribe to this content on ScienceDirect." }] });
    expect(describeFailure("entitlement_missing", sciencedirect).evidence)
      .toBe("Hong Mu-lan University does not subscribe to this content on ScienceDirect.");
    // An older record kept only the school's name: "recognised" is not the evidence.
    expect(describeFailure("entitlement_missing", diagnostic({ access_evidence: ["Brought to you by:Hong Mu-Lan University"] })).evidence)
      .toBe("出版社判定学校没有订阅（这条记录没有保存页面原文）");
  });

  it("says where an unexplained failure stopped, before the steps taken after the outcome", () => {
    const capture = diagnostic({ events: [
      { state: "pdf_capture_started" },
      { state: "pdf_entry_gated", detail: "get access / access through institution shown" },
      { state: "pdf_candidate", detail: "https://www.tandfonline.com/doi/pdf/10.1080/0142159x.2026.2752868?needAccess=true" },
      { state: "supplements_found", detail: "0" },
      { state: "supplements_saved", detail: "0/0" },
    ] });
    expect(describeFailure("download_failed", capture)).toEqual({
      failureClass: "unexplained",
      stoppedAt: "pdf_candidate：https://www.tandfonline.com/doi/pdf/10.1080/0142159x.2026.2752868?needAccess=true",
    });
    expect(describeFailure("download_failed")).toEqual({ failureClass: "unexplained" });
    expect(describeFailure("download_failed", diagnostic({ events: [{ state: "pdf_capture_started" },
      { state: "supplements_not_supported", detail: "LWW" }] })).stoppedAt).toBe("pdf_capture_started");
    expect(describeFailure("source_exception", undefined, { exception: "TypeError: x is undefined" }).stoppedAt)
      .toBe("程序异常：TypeError: x is undefined");
  });
});
