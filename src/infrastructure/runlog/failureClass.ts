/**
 * Every failed institutional download is in one of these classes (ADR 0012):
 * evidenced no access; four for a cause outside PaperSearch's rules, by whose it
 * is (yours, the school's, the publisher's or the network's, the article's or the
 * site's own); a site without rules yet; or unexplained. "No access" is never
 * concluded from a missing PDF, a timeout or an error; unexplained failures are
 * investigated. The four were one class, "用户或外部原因", until 2026-11-19 (user:
 * the report did not say whose the cause was).
 */
export type FailureClass =
  | "no_access"
  | "user_side"
  | "school_side"
  | "publisher_or_network"
  | "article_or_site"
  | "unsupported"
  | "unexplained";

export const FAILURE_CLASSES: readonly FailureClass[] = [
  "no_access",
  "user_side",
  "school_side",
  "publisher_or_network",
  "article_or_site",
  "unsupported",
  "unexplained",
];

/** Short names, for one-line counts and the progress window's tags. */
export const FAILURE_CLASS_NAMES: Readonly<Record<FailureClass, string>> = {
  no_access: "没权限",
  user_side: "你这边",
  school_side: "学校那边",
  publisher_or_network: "出版社或网络",
  article_or_site: "文章或网站本身",
  unsupported: "暂不支持的网站",
  unexplained: "原因不明",
};

export const FAILURE_CLASS_LABELS: Readonly<Record<FailureClass, string>> = {
  no_access: "没权限（有依据）",
  user_side: "你这边（操作或设置）",
  school_side: "学校那边（学校登录）",
  publisher_or_network: "出版社或网络",
  article_or_site: "文章或网站本身",
  unsupported: "暂不支持的网站",
  unexplained: "原因不明（需排查）",
};

const CLASS_OF_CODE: Readonly<Record<string, FailureClass>> = {
  // The publisher denied the recognised school; the publisher has no route for
  // the school's federation; the user
  // marked the journal or publisher as without access.
  entitlement_missing: "no_access",
  institution_federation_unavailable: "no_access",
  // The school's sign-in is not enabled for the publisher: the publisher says so (Optica: "Your
  // organization does not have access via SSO"), or the school's login system does (SYSU's for
  // JAMA: "The application you have accessed is not registered for use with this service"). No
  // access by this way in, as one with no route for the school (user, 2026-11-19; it was
  // user_or_external). Another entry of the school may still have it.
  institution_not_registered: "no_access",
  no_entitlement: "no_access",
  // Yours: you skipped, cancelled, stopped the batch, closed the login page or the
  // browser, or did not finish signing in within the wait; another run of yours held
  // the browser; the institutional download was not run; PaperSearch Pro not
  // installed, or its key needed.
  user_skipped: "user_side",
  cancelled: "user_side",
  batch_stopped: "user_side",
  login_timeout: "user_side",
  login_page_closed: "user_side",
  browser_closed: "user_side",
  profile_busy: "user_side",
  // A Markdown missing figures, not kept, as the institutional download, which reads the
  // page, never ran (2026-11-16).
  institutional_not_run: "user_side",
  // The Markdown is PaperSearch Pro's: not installed, or its key needed (2026-11-18).
  markdown_pro_required: "user_side",
  markdown_pro_key_required: "user_side",
  // The school's: its login refused the credentials, failed, locked the account or
  // found the password expired; it ended on its own site, the school not having
  // enabled the publisher; it stopped working mid-batch at a publisher it had worked
  // at, the paper waiting, not tried (user, 2026-11-15).
  login_credentials_rejected: "school_side",
  idp_login_error: "school_side",
  idp_account_locked: "school_side",
  idp_password_expired: "school_side",
  idp_no_return_to_publisher: "school_side",
  login_paused: "school_side",
  // The publisher's or the network's: the site blocked the network or asked for a human
  // verification that did not pass (a firewall's page answered instead of a file:
  // Figshare, 2026-11-08), answered with its error page or not at all; the network was
  // down (neither doi.org nor PubMed answered, 2026-11-17); the per-hour limit kept for
  // the school; PubMed Central did not answer the Markdown's lookup (Windows,
  // 2026-11-16); a figure or a table of the page not fetched (BMJ, 2026-11-16);
  // PaperSearch Pro's server not reached for its weekly check.
  access_blocked: "publisher_or_network",
  cloudflare_blocked: "publisher_or_network",
  captcha_required: "publisher_or_network",
  verification_page: "publisher_or_network",
  publisher_content_error: "publisher_or_network",
  publisher_unreachable: "publisher_or_network",
  network_unavailable: "publisher_or_network",
  rate_limited: "publisher_or_network",
  pmc_failed: "publisher_or_network",
  figures_missing: "publisher_or_network",
  tables_missing: "publisher_or_network",
  markdown_pro_offline: "publisher_or_network",
  // The article's or the site's own: accepted, its full text not online yet (Optica,
  // 2026-11-08); doi.org not knowing the DOI yet (2026-11-15) or never (a paper published
  // long ago, PubMed listing no other link, 2026-11-16); the site offers no school login
  // at all, only its own accounts or none (an open-access site): its design, not evidence
  // that the school has no access, nor a site our rules do not know (user, 2026-11-18).
  article_not_yet_published: "article_or_site",
  doi_not_resolved: "article_or_site",
  doi_not_registered: "article_or_site",
  no_institution_entry: "article_or_site",
  // Content only on another platform (ClinicalKey); a DOI leading to no site to
  // sign in on; a site without a profile where the shared rules found no
  // institution entry: no rules for that site yet.
  unsupported_platform: "unsupported",
  unsupported_publisher: "unsupported",
  generic_institution_entry_missing: "unsupported",
  // Supplementary files: no rule for the site's files yet.
  supplements_not_supported: "unsupported",
};

export function classifyFailureCode(code: string | undefined): FailureClass {
  return code && Object.hasOwn(CLASS_OF_CODE, code) ? CLASS_OF_CODE[code] : "unexplained";
}

export interface FailureDescription {
  failureClass: FailureClass;
  /** no_access: the page's words or the decisive step. */
  evidence?: string;
  /** unexplained: the last step the browser reached. */
  stoppedAt?: string;
}

interface BackendEvent {
  state?: string;
  detail?: string;
}

/** Steps recorded after the outcome was decided (and the supplementary-file step). */
function afterTheOutcome(state: string): boolean {
  return state.startsWith("supplements_") || state === "publisher_session_saved" || state === "entitlement_denied";
}

/**
 * The class of a failed entitled-access stage, from its code and the
 * backend's diagnostic (or record) as the run ledger keeps it.
 */
export function describeFailure(
  code: string | undefined,
  backend?: Record<string, unknown>,
  trace?: Record<string, unknown>,
): FailureDescription {
  const detail = (backend?.diagnostic ?? backend?.record) as Record<string, unknown> | undefined;
  const events = (Array.isArray(detail?.events) ? detail.events : []) as BackendEvent[];
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

function noAccessEvidence(
  code: string | undefined,
  detail: Record<string, unknown> | undefined,
  events: BackendEvent[],
): string | undefined {
  if (code === "no_entitlement") return "你标记过该期刊或出版社无权限";
  if (code === "institution_not_registered") {
    // The page's own words, as the backend kept them on its block event: the publisher's, or the
    // school's login system's; not said whose, the words name the site (user, 2026-11-19).
    const said = [...events].reverse().find((event) => event.state === "institution_not_registered" && event.detail);
    return said ? `这个登录入口没有开通：${String(said.detail).slice(0, 160)}` : "这个登录入口没有开通";
  }
  if (code === "institution_federation_unavailable") {
    const notFound = [...events].reverse().find((event) => event.state === "auto_institution_not_found");
    const [school, where] = String(notFound?.detail ?? "").split(" @ ");
    return school && where
      ? `机构列表里找不到 ${school.trim()}（${hostOf(where) || where.slice(0, 60)}）`
      : "出版社没有学校所在联盟的登录路线";
  }
  const denied = [...events].reverse().find((event) => event.state === "entitlement_denied");
  if (denied?.detail) return String(denied.detail);
  const lines = (Array.isArray(detail?.access_evidence) ? detail.access_evidence : [])
    .filter((line): line is string => typeof line === "string" && line.trim() !== "");
  const denial = lines.find((line) =>
    /\b(?:does not|do not|not|no)\b.{0,40}\b(?:subscribe|subscribed|subscription|access|available|registered|purchased)\b/i.test(line),
  );
  // The publisher's own check decided (ScienceDirect reads its access panel);
  // records before 2026-11-01 kept only "Brought to you by", not the denial.
  return denial ?? "出版社判定学校没有订阅（这条记录没有保存页面原文）";
}

function lastStep(events: BackendEvent[]): string | undefined {
  const last = [...events].reverse().find((event) => event.state && !afterTheOutcome(event.state));
  if (!last?.state) return undefined;
  const detail = last.detail ? String(last.detail) : "";
  return detail ? `${last.state}：${detail.slice(0, 120)}` : last.state;
}

export function hostOf(url: unknown): string {
  if (typeof url !== "string") return "";
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}
