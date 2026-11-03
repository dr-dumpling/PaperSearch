export const FAILURE_CLASSES = [
    "no_access",
    "user_or_external",
    "unsupported",
    "unexplained",
];
/** Short names, for one-line counts. */
export const FAILURE_CLASS_NAMES = {
    no_access: "没权限",
    user_or_external: "用户或外部原因",
    unsupported: "暂不支持的网站",
    unexplained: "原因不明",
};
export const FAILURE_CLASS_LABELS = {
    no_access: "没权限（有依据）",
    user_or_external: "用户或外部原因",
    unsupported: "暂不支持的网站",
    unexplained: "原因不明（需排查）",
};
const CLASS_OF_CODE = {
    // The publisher denied the recognised school; the publisher has no route for
    // the school's federation; the school is not registered there; the user
    // marked the journal or publisher as without access.
    entitlement_missing: "no_access",
    institution_federation_unavailable: "no_access",
    institution_not_registered: "no_access",
    no_entitlement: "no_access",
    // The user skipped, cancelled, closed the login, gave wrong credentials or did
    // not finish on the school's login page; the school's login failed; the
    // publisher blocked access or answered with its error page; the per-hour
    // limit; another run held the browser.
    user_skipped: "user_or_external",
    cancelled: "user_or_external",
    login_timeout: "user_or_external",
    login_page_closed: "user_or_external",
    login_credentials_rejected: "user_or_external",
    captcha_required: "user_or_external",
    idp_login_error: "user_or_external",
    idp_account_locked: "user_or_external",
    idp_password_expired: "user_or_external",
    // The school's login ended on its own site: the school has not enabled the publisher.
    idp_no_return_to_publisher: "user_or_external",
    access_blocked: "user_or_external",
    cloudflare_blocked: "user_or_external",
    publisher_content_error: "user_or_external",
    publisher_unreachable: "user_or_external",
    rate_limited: "user_or_external",
    batch_stopped: "user_or_external",
    profile_busy: "user_or_external",
    // Content only on another platform (ClinicalKey); a DOI leading to no site to
    // sign in on; a site without a profile where the shared rules found no
    // institution entry: no rules for that site yet.
    unsupported_platform: "unsupported",
    unsupported_publisher: "unsupported",
    generic_institution_entry_missing: "unsupported",
};
export function classifyFailureCode(code) {
    return code && Object.hasOwn(CLASS_OF_CODE, code) ? CLASS_OF_CODE[code] : "unexplained";
}
/** Steps recorded after the outcome was decided (and the supplementary-file step). */
function afterTheOutcome(state) {
    return state.startsWith("supplements_") || state === "publisher_session_saved" || state === "entitlement_denied";
}
/**
 * The class of a failed entitled-access stage, from its code and the
 * backend's diagnostic (or record) as the run ledger keeps it.
 */
export function describeFailure(code, backend, trace) {
    const detail = (backend?.diagnostic ?? backend?.record);
    const events = (Array.isArray(detail?.events) ? detail.events : []);
    let failureClass = classifyFailureCode(code);
    if (code === "login_timeout" && !events.some((event) => event.state === "login_wait_ended")) {
        // Recorded before the wait's page was kept (2026-11-01): the wait may have
        // run out on the article, where the user had nothing to do.
        failureClass = "unexplained";
    }
    if (failureClass === "no_access") {
        const evidence = noAccessEvidence(code, detail, events);
        return evidence ? { failureClass, evidence } : { failureClass };
    }
    if (failureClass === "unexplained") {
        const exception = typeof trace?.exception === "string" ? `程序异常：${trace.exception.slice(0, 160)}` : "";
        const stoppedAt = lastStep(events) || exception;
        return stoppedAt ? { failureClass, stoppedAt } : { failureClass };
    }
    return { failureClass };
}
function noAccessEvidence(code, detail, events) {
    if (code === "no_entitlement")
        return "你标记过该期刊或出版社无权限";
    if (code === "institution_federation_unavailable") {
        const notFound = [...events].reverse().find((event) => event.state === "auto_institution_not_found");
        const [school, where] = String(notFound?.detail ?? "").split(" @ ");
        return school && where
            ? `机构列表里找不到 ${school.trim()}（${hostOf(where) || where.slice(0, 60)}）`
            : "出版社没有学校所在联盟的登录路线";
    }
    const denied = [...events].reverse().find((event) => event.state === "entitlement_denied");
    if (denied?.detail)
        return String(denied.detail);
    const lines = (Array.isArray(detail?.access_evidence) ? detail.access_evidence : [])
        .filter((line) => typeof line === "string" && line.trim() !== "");
    const denial = lines.find((line) => /\b(?:does not|do not|not|no)\b.{0,40}\b(?:subscribe|subscribed|subscription|access|available|registered|purchased)\b/i.test(line));
    // The publisher's own check decided (ScienceDirect reads its access panel);
    // records before 2026-11-01 kept only "Brought to you by", not the denial.
    return denial ?? "出版社判定学校没有订阅（这条记录没有保存页面原文）";
}
function lastStep(events) {
    const last = [...events].reverse().find((event) => event.state && !afterTheOutcome(event.state));
    if (!last?.state)
        return undefined;
    const detail = last.detail ? String(last.detail) : "";
    return detail ? `${last.state}：${detail.slice(0, 120)}` : last.state;
}
export function hostOf(url) {
    if (typeof url !== "string")
        return "";
    try {
        return new URL(url).hostname;
    }
    catch {
        return "";
    }
}
//# sourceMappingURL=failureClass.js.map