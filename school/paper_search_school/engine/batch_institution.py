"""Choosing the federation and the user's configured school on publisher and federation pickers.

Part of ``PublisherBatchDownloader`` (batch.py), which combines the mixins."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse

from .. import federations
from ..federations import schools
from . import access_rules
from .batch_common import (DownloadResult, _is_browser_error, _is_navigation_cut, logger, open_page,
                           pump_until, settle)


def _school_auth_patterns(config: dict[str, Any]) -> tuple[str, ...]:
    """The configured school's login hosts, for telling its login pages apart
    (``schools.login_hosts``: its entityID's host and those its federation lists);
    empty without one. The package names no school itself."""
    return schools.login_hosts(config)


# Institution search input selectors, tried in order on WAYF pages
_INSTITUTION_SEARCH_SELECTORS: list[str] = [
    "#searchInstitution", "#bdd-email", 'input[name="institution"]',
    "#institution-search", 'input[placeholder*="institution"]',
    'input[placeholder*="University"]',
]


class InstitutionMixin:
    """Choosing the federation and the user's configured school on publisher and federation pickers."""

    # The school chosen this often on one chooser address, the chooser back each time.
    SCHOOL_CHOICE_REPEATS = 3

    @property
    def federation(self) -> "federations.Federation | None":
        """The federation of the user's school (the federation layer); None: no
        school is configured and the user chooses the institution."""
        return federations.configured(self.config)

    @staticmethod
    def _school_choices_here(result: DownloadResult, url: str) -> int:
        return sum(e["state"] == "auto_institution_entry" and str(e.get("detail", "")).endswith(f"@ {url}")
                   for e in result.events)

    def _after_repeated_school_choice(self, page: Any, result: DownloadResult, url: str) -> bool:
        """The chooser came back each time the school was chosen on it. NEJM signed
        the school in, sent the browser back to its chooser, and the school was
        chosen there again every 4 s until the wait ran out (2026-11-03). Once per
        item the article is opened again: signed in, it gives the PDF. After that
        nothing more is chosen on the chooser; the user may still choose there."""
        if result.article_url and not any(e["state"] == "institution_choice_returned_article" for e in result.events):
            try:
                open_page(page, result.article_url, timeout_ms=60_000)
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
                self._event(result, "institution_session_return_error", f"{type(exc).__name__}: {str(exc)[:160]}")
                return False
            self._event(result, "institution_choice_returned_article",
                        f"chosen {self.SCHOOL_CHOICE_REPEATS} times @ {url[:160]}")
            settle(page, 3_000)
            return True
        if not any(e["state"] == "institution_choice_stopped" for e in result.events):
            self._event(result, "institution_choice_stopped", url[:160])
        return False

    def _select_institution(self, page: Any, result: DownloadResult) -> bool:
        if getattr(self, "_manual_school", False):
            return False  # the user reported a wrong school: they choose it in the window
        if self.adapter.leave_email_step(page, result):
            return True  # an email field takes no school name (Elsevier ID, 2026-11-11)
        federation = self.federation
        if federation is not None:
            here = str(getattr(page, "url", "") or "")
            if self._is_idp_host(urlparse(here).netloc) or self._on_school_login_page(here):
                # The school's own login page is the user's: nothing is chosen or
                # typed there (its CAS page took the school's name in a search
                # field once, 2026-11-11).
                return False
            if self._has_publisher_institution_session(page):
                # The publisher already shows a signed-in school: nothing to choose
                # (RSC's account menu names it and was clicked as an entry, 2026-11-01).
                return False
            here = str(getattr(page, "url", "") or "")
            if self._school_choices_here(result, here) >= self.SCHOOL_CHOICE_REPEATS:
                return self._after_repeated_school_choice(page, result, here)
            # The OpenAthens wayfinder goes straight to the school's entity on the
            # route that signs in there.
            if federation.openathens_entries and self._select_openathens_wayfinder(page, result):
                return True
            # Everything except human verification and the user's credentials is
            # automated once an institution is configured: a remembered
            # "Access through <school>" entry, the school in a publisher list or
            # search, then Continue. Without a configured school nothing is picked.
            if self.institution_query and self._select_from_institution_lists(page, result):
                return True
            if self.institution_query and self._assist_configured_institution(page, result):
                return True
            if self.institution_query and self._select_federation_link(page, result, here):
                return True
            if self.institution_query and not getattr(result, "_institution_not_listed", False):
                self._check_federation_school_links(page, result, here)
            if getattr(result, "_institution_not_listed", False):
                return False
            if self.adapter.prepare_institution_choice(page, result) is False:
                return False
            if self._open_seamlessaccess_chooser(page, result):
                return True
            try:
                chosen = self.adapter.choose_institution(page, result)
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
                # The page navigated while the publisher's step read it (Thieme's
                # Continue reloading its chooser, 2026-11-02): looked at again next pass.
                self._event(result, "institution_step_interrupted", f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}")
                return False
            if chosen is not None:
                return chosen
            if self.institution_query and self._assist_federation_discovery(page, result):
                return True
            if not any(event["state"] == "institution_selection_required" for event in result.events):
                self._event(result, "institution_selection_required", federation.code)
            return False
        current_url = str(getattr(page, "url", "") or "")
        host = (urlparse(current_url).netloc or "").lower()
        if self._is_idp_host(host):
            return False
        if not self.institution_query:
            self._event(result, "institution_required", "No subscription institution was configured for publisher login.")
            return False
        if host == "login.openathens.net":
            # Never fill an OpenAthens account form with an institution name.
            return False
        if self._select_openathens_wayfinder(page, result):
            return True
        if self.adapter.fill_institution_search(page, result):
            return True
        for selector in self.profile.institution_input_selectors:
            try:
                inp = page.locator(selector).first
                if inp.is_visible(timeout=5_000):
                    inp.fill(self.institution_query)
                    self._event(result, "institution_search", selector)
                    settle(page, 2_000)
                    if self._click_institution_search_result(page, result):
                        return True
                    try:
                        inp.press("Enter", timeout=3_000)
                        self._event(result, "institution_search_submitted", selector)
                        settle(page, 3_000)
                        if self._click_institution_search_result(page, result):
                            return True
                        # No entry matched the configured institution: leave the
                        # choice (and the Continue button) to the user.
                        if not any(e["state"] == "institution_selection_required" for e in result.events):
                            self._event(result, "institution_selection_required", "no matching entry")
                        return False
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    # Every <select> of the page, shown or not: JAMA keeps its federation and school
    # lists hidden behind a search box, ACS leaves its school list disabled after
    # filling it (2026-11-02). Values and labels, in one round trip.
    _SELECTS_JS = r"""() => [...document.querySelectorAll('select')].slice(0, 12).map((s, i) => ({
        i, name: s.id ? '#' + s.id : (s.name || 'select'), disabled: s.disabled, value: s.value,
        shown: s.getClientRects().length > 0 && getComputedStyle(s).visibility !== 'hidden',
        options: [...s.options].slice(0, 5000).map(o => [o.value, (o.text || '').replace(/\s+/g, ' ').trim()])}))"""
    # A list that cannot be chosen in as a user would (hidden, or still disabled once
    # filled) is set as its own script would, with the events its page listens to.
    # As a reader does: focus, choose, leave the list. Some sites load the next
    # list on leaving (blur), not on change.
    _SET_SELECT_JS = r"""([index, value]) => {
        const s = document.querySelectorAll('select')[index];
        if (!s) return false;
        s.disabled = false;
        s.focus();
        s.value = value;
        s.dispatchEvent(new Event('input', {bubbles: true}));
        s.dispatchEvent(new Event('change', {bubbles: true}));
        s.blur();
        s.dispatchEvent(new FocusEvent('focusout', {bubbles: true}));
        return s.value === value;
    }"""
    # A blank overlay left over the page (a loading backdrop that never closes:
    # ACS's #globalModalOverlay after choosing the federation, 2026-11-02): large,
    # fixed, named an overlay/backdrop/modal/loading, with nothing to use inside.
    _BLANK_OVERLAY_JS = r"""() => {
        const vw = innerWidth, vh = innerHeight;
        const named = /overlay|backdrop|modal-bg|loading|spinner|mask/i;
        for (const e of document.querySelectorAll('body *')) {
            const s = getComputedStyle(e);
            if (s.position !== 'fixed' || s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) continue;
            const r = e.getBoundingClientRect();
            if (r.width * r.height < vw * vh * 0.5 || !named.test(String(e.className) + ' ' + e.id)) continue;
            const usable = [...e.querySelectorAll('a[href], button, input, select, textarea, iframe')].some(c => c.getClientRects().length);
            if (usable) continue;
            const what = e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + '.' + String(e.className).trim().split(/\s+/).slice(0, 2).join('.');
            e.click();
            document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
            if (getComputedStyle(e).display !== 'none' && e.isConnected) e.style.display = 'none';
            return what;
        }
        return null;
    }"""
    # The chooser's own submit: the nearest control around what was chosen,
    # the first after it. A custom UI can hide both its school list and native
    # submit; a unique nearby native Select/Continue still belongs to it.
    # What was chosen is a list (its index among document.querySelectorAll('select')) or
    # an entry (a selector), whose form's controls only, or with no form none of
    # another form's; ``controls`` names the controls that count (null: any button
    # or link-button). Never a control of the page outside the chooser, such as the
    # header's search (review 2026-11-02).
    _LIST_SUBMIT_JS = r"""([anchor, controls]) => {
        const s = typeof anchor === 'number' ? document.querySelectorAll('select')[anchor] : document.querySelector(anchor);
        if (!s) return null;
        const own = s.form || s.closest('form');
        const shown = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden' && !el.disabled;
        const text = el => (el.innerText || el.value || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '')
            .replace(/\s+/g, ' ').trim();
        const CONTROL = controls || ('button, input[type="submit"], input[type="button"], input[type="image"], '
            + 'a[href^="javascript" i], a[role="button"], [role="button"], a.button, a.btn');
        const NOT = /cancel|back|reset|clear|register|personal|sign ?up|help|close|remember|forgot|subscribe|purchase|\bbuy\b/i;
        const NATIVE_ACTION = /^(?:select|continue|go|next|sign\s*in|log\s*in|选择|继续|登录)$|access.*institut/i;
        for (let box = s.parentElement, n = 0; box && n < 6; box = box.parentElement, n++) {
            const candidates = [...box.querySelectorAll(CONTROL)].filter(c => !s.contains(c) && !c.disabled && text(c).length <= 60
                && !NOT.test(text(c)) && (('form' in c ? c.form : c.closest('form')) === own));
            const found = candidates.filter(shown);
            const native = typeof anchor === 'number' && !shown(s) && own
                ? candidates.filter(c => c.type === 'submit' && c.form === own && !shown(c) && NATIVE_ACTION.test(text(c))) : [];
            if (!found.length && native.length !== 1) continue;
            const pick = native.length === 1 ? native[0]
                : (found.find(c => s.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING) || found[found.length - 1]);
            document.querySelectorAll('[data-paper-search-submit]').forEach(e => e.removeAttribute('data-paper-search-submit'));
            pick.setAttribute('data-paper-search-submit', '');
            return text(pick).slice(0, 80) || pick.tagName;
        }
        return null;
    }"""
    _FEDERATION_LINK_LIST = "ul.federation--list"
    _FEDERATION_SCHOOL_LIST = "ul.federation--list-inner"
    # How long one pass waits for the school's option once the federation is chosen
    # (ACS answered after 35-50 s, 2026-11-02; the login loop asks again).
    LIST_WAIT_SEC = 15

    def _page_selects(self, page: Any) -> list[dict]:
        try:
            found = page.evaluate(self._SELECTS_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return []
        return [s for s in found if isinstance(s, dict)] if isinstance(found, list) else []

    def _school_option(self, lists: list[dict]) -> tuple[dict, str, str, str] | None:
        """``(select, value, label, how)`` for the configured school's option: the
        one valued with its entityID, else the single one naming it."""
        entity_id = self._entity_id()
        names = {self._canonical_school_name(name) for name in self._institution_names()} - {""}
        for by_id in (True, False):
            for select in lists:
                options = [(str(o[0]), str(o[1])) for o in select.get("options") or ()
                           if isinstance(o, (list, tuple)) and len(o) == 2 and o[0]]
                if by_id:
                    hits = [o for o in options if entity_id and (o[0] == entity_id or self._carries_entity_id(o[0], entity_id))]
                else:
                    hits = [o for o in options if self._canonical_school_name(o[1]) in names]
                if len(hits) == 1 or (by_id and hits):
                    return select, hits[0][0], hits[0][1], "entityID" if by_id else "name"
        return None

    def _federation_option(self, lists: list[dict]) -> tuple[dict, str, str] | None:
        """``(select, value, label)``: a federation list's single entry for the school's federation."""
        federation = self.federation
        if federation is None:
            return None
        for select in lists:
            hits = [(str(o[0]), str(o[1])) for o in select.get("options") or ()
                    if isinstance(o, (list, tuple)) and len(o) == 2 and o[0] and federation.matches(str(o[1]))]
            if len(hits) == 1:
                return select, hits[0][0], hits[0][1]
        return None

    @staticmethod
    def _filled_lists(lists: Any, federation: dict) -> dict:
        """Filled school lists, not the header's journal/language/search lists.

        Only positive institution evidence can establish that a school is
        missing. An unrelated filled dropdown says nothing about an empty
        institution list that is still loading.
        """
        school = re.compile(r"institut|school|universit|\buniv\b|college|organi[sz]ation|\bidp\b|大学|学院|研究院", re.I)
        return {str(s.get("name")): list(s.get("options") or ()) for s in lists or ()
                if s.get("i") != federation.get("i") and len(s.get("options") or ()) > 1
                and (school.search(str(s.get("name") or "")) or any(
                    school.search(str(o[1])) for o in s.get("options") or ()
                    if isinstance(o, (list, tuple)) and len(o) == 2))}

    # The list chosen in, marked by its index among document.querySelectorAll('select'):
    # a locator's "select" would also count lists inside shadow roots.
    _MARK_SELECT_JS = r"""(index) => {
        document.querySelectorAll('[data-paper-search-list]').forEach(e => e.removeAttribute('data-paper-search-list'));
        const s = document.querySelectorAll('select')[index];
        if (s) s.setAttribute('data-paper-search-list', '');
        return !!s;
    }"""

    def _set_select(self, page: Any, select: dict, value: str) -> None:
        """Choose ``value`` the way the page's own script does, shown or hidden: a
        reader-like select_option made ACS wait about 25 s for its next list, the
        script's choice fills it in a second (2026-11-02)."""
        page.evaluate(self._SET_SELECT_JS, [int(select["i"]), value])

    # The page's own load: a reload at the same address is another page.
    _PAGE_LOAD_JS = "() => performance.timeOrigin"

    def _federation_choice_page(self, page: Any, result: DownloadResult) -> tuple[str, str] | None:
        """This page (its address and its load) when the school's federation may be chosen in its
        federation list now; None when not: the program chose the federation on this very
        page and it shows another federation since (the user's choice, left alone),
        or the page is navigating (looked at again next pass). A chooser that
        reloads, at the same address or another, with its first federation
        selected is a new page and is chosen again (Thieme after its Continue;
        one rule for every chooser, review 2026-11-02)."""
        try:
            here = (str(getattr(page, "url", "") or ""), str(page.evaluate(self._PAGE_LOAD_JS)))
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            self._event(result, "institution_step_interrupted",
                        f"{type(exc).__name__}: {(str(exc).splitlines() or [''])[0][:160]}")
            return None
        if here not in getattr(result, "_federation_pages", ()):
            return here
        if not any(e["state"] == "institution_federation_user_choice" and e.get("detail") == here[0][:200]
                   for e in result.events):
            self._event(result, "institution_federation_user_choice", here[0][:200])
        return None

    def _federation_chosen(self, result: DownloadResult, here: tuple[str, str], detail: str) -> None:
        """Record that the program chose the school's federation on page ``here`` (``_federation_choice_page``)."""
        result._federation_pages = getattr(result, "_federation_pages", set()) | {here}
        self._event(result, "institution_federation_selected", detail)

    def _select_federation_link(self, page: Any, result: DownloadResult, url: str) -> bool:
        """A publisher's list of federation links (Atypon's): the school's federation's."""
        federation = self.federation
        if federation is None or not self._on_publisher_host(url):
            return False
        listing = page.locator(self._FEDERATION_LINK_LIST).first
        try:
            if listing.is_visible() is not True:
                return False
            links = listing.get_by_role("link", name=federation.chooser_pattern)
            if links.count() != 1:
                return False
            href = links.first.get_attribute("href", timeout=800)
            if not href or not self._manual_institution_target_allowed(urljoin(url, href)):
                return False
            here = self._federation_choice_page(page, result)
            if here is None or not self._click_control(page, links.first, result, f"choose {federation.name} federation"):
                return False
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            self._event(result, "institution_step_interrupted", type(exc).__name__)
            return False
        self._federation_chosen(result, here, f"{federation.code}: federation link @ {url}")
        return True

    def _check_federation_school_links(self, page: Any, result: DownloadResult, url: str) -> None:
        """Only a complete link directory can establish absence after choosing the federation."""
        federation = self.federation
        if federation is None or not self._on_publisher_host(url):
            return
        try:
            listing = page.locator(self._FEDERATION_SCHOOL_LIST).first
            if listing.is_visible() is not True:
                return
            heading = page.get_by_role("heading", level=1, name=federation.chooser_pattern).first
            if heading.is_visible() is not True or self._is_challenge_page(page):
                self._school_list_unconfirmed(result, url, f"no {federation.name} heading, or a verification page")
                return
            rows = listing.locator(":scope > li")
            entries = page.evaluate(self._ENTRIES_JS, self._FEDERATION_SCHOOL_LIST + " > li > a[href]")
            busy = listing.evaluate("""el => el.closest('[aria-busy=true]') ? 'busy' :
                (el.closest('section')?.querySelector('input:not([type=hidden]), [aria-busy=true], [rel=next]')?.outerHTML || '').slice(0, 120)""",
                                    timeout=800)
            if not entries or len(entries) != rows.count() or busy:
                self._school_list_unconfirmed(
                    result, url, f"{len(entries or [])} links, {rows.count()} rows" + (f", {busy}" if busy else ""))
                return
            # Even a partial name match is enough to leave the choice open for the user.
            entity_id = self._entity_id()
            names = {self._canonical_school_name(name) for name in self._institution_names()} - {""}
            if any(self._institution_entry_score(entry, entity_id)
                   or self._canonical_school_name(entry["t"]) in names for entry in entries):
                return
            self._event(result, "auto_institution_not_found",
                        f"{self.institution_query} ({federation.name} list, {len(entries)} schools) @ {url}")
            result._institution_not_listed = True
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            self._event(result, "institution_step_interrupted", type(exc).__name__)

    def _school_list_unconfirmed(self, result: DownloadResult, url: str, why: str) -> None:
        """Why a shown school list of the federation could not settle the school's absence, once per page:
        the school was left to choose by hand and the wait ran out (Science, 2026-11-11)."""
        if not any(e["state"] == "federation_school_list_unconfirmed" and str(e.get("detail", "")).endswith(f"@ {url}")
                   for e in result.events):
            self._event(result, "federation_school_list_unconfirmed", f"{why} @ {url}")

    def _close_blank_overlay(self, page: Any, result: DownloadResult) -> None:
        try:
            closed = page.evaluate(self._BLANK_OVERLAY_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return
        if closed:
            self._event(result, "overlay_closed", str(closed)[:120])

    def _select_from_institution_lists(self, page: Any, result: DownloadResult) -> bool:
        """One rule for school lists in <select>s, shown or hidden: the federation
        list's entry for the school's federation, then the school's option (by entityID, the
        option's value, else by name), then the list's own submit control. Once per
        page; True when something was chosen. Without the school in a filled list
        the publisher has no route for it (``_institution_not_listed``)."""
        url = str(getattr(page, "url", "") or "")
        host = (urlparse(url).hostname or "").lower()
        if (self._is_idp_host(host) or not (self._on_publisher_host(url) or self._is_federation_chooser(url))
                or any(e["state"] == "institution_list_submitted" and e.get("detail", "").endswith(f"@ {url}")
                       for e in result.events)):
            return False  # only the publisher's and the federations' choosers
        lists = self._page_selects(page)
        school = self._school_option(lists)
        federation = None if school else self._federation_option(lists)
        if school is None and federation is None:
            return False
        if federation is not None:
            select, value, label = federation
            if not any(s.get("i") != select.get("i") for s in lists):
                # No school list beside it (Atypon's entries, Thieme's next page):
                # the publisher's own chooser rule and the entry assistance decide.
                return False
            if select.get("value") != value:
                here = self._federation_choice_page(page, result)
                if here is None:
                    return False
                self._set_select(page, select, value)
                self._federation_chosen(result, here, f"{self.federation.code}: {label} in {select.get('name')} @ {url}")
                page.wait_for_timeout(500)
                self._close_blank_overlay(page, result)
            started, seen = time.time(), {}

            def listed() -> bool:
                seen["lists"] = self._page_selects(page)
                seen["school"] = self._school_option(seen["lists"])
                return seen["school"] is not None

            if not pump_until(page, listed, self.LIST_WAIT_SEC * 1000, step_ms=500):
                filled = self._filled_lists(seen.get("lists"), select)
                page.wait_for_timeout(1_000)
                if filled and not listed() and self._filled_lists(seen["lists"], select) == filled:
                    # Filled, unchanged a second later, and without the school.
                    name, options = next(iter(filled.items()))
                    sample = ", ".join(str(o[1]) for o in options[1:6])
                    self._event(result, "auto_institution_not_found",
                                f"{self.federation.code} list {name} ({len(options)} options: {sample}) @ {url}")
                    result._institution_not_listed = True
                    return False
                count = max((len(s.get("options") or ()) for s in seen.get("lists") or () if s.get("i") != select.get("i")), default=0)
                if not any(e["state"] == "institution_list_not_ready" and e.get("detail") == f"{count} options @ {url}"
                           for e in result.events):
                    self._event(result, "institution_list_not_ready", f"{count} options @ {url}")
                return False
            school = seen["school"]
            if time.time() - started > 10:
                self._event(result, "wait", f"institution list: {time.time() - started:.0f} s, ended: the school's option appeared")
        select, value, label, how = school
        if select.get("value") != value:
            self._set_select(page, select, value)
        self._event(result, "institution_selected", f"{label[:80]} ({how}, {select.get('name')})")
        self._close_blank_overlay(page, result)
        try:
            submit = page.evaluate(self._LIST_SUBMIT_JS, [int(select["i"]), None])
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            submit = None
        if not submit:
            self._event(result, "institution_submit_missing", url[:200])
            return True
        if self._click_control(page, page.locator("[data-paper-search-submit]").first, result,
                               f"institution list submit: {submit}"):
            self._event(result, "institution_list_submitted", f"{submit} @ {url}")
        # Not clicked (script_click_failed): the school is chosen; the next pass submits again.
        return True

    @staticmethod
    def _canonical_school_name(text: str) -> str:
        """A school's name for comparing list labels: case, punctuation,
        parentheticals, a trailing address, "Univ"/"University" and a trailing
        "Library" do not count
        ("EXAMPLE (CITY) UNIV | https://idp.example.edu.cn/idp/shibboleth" = "Example
        University", as ACS labels them, 2026-11-02); Chinese names are kept."""
        text = re.split(r"\s+\|\s+|https?://", str(text or ""), maxsplit=1)[0]
        text = re.sub(r"\([^)]*\)|（[^）]*）", " ", text.lower()).replace("&", " and ")
        words = re.sub(r"[^a-z0-9一-鿿]+", " ", text).split()
        words = ["university" if word == "univ" else word for word in words]
        if words and words[-1] in ("library", "libraries"):
            words = words[:-1]
        if words and words[-1] == "university":
            words = words[:-1]
        return " ".join(words)

    # CARSI writes some English names with a curly apostrophe ("Xi’an"), publisher lists a straight one.
    _QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'"})

    def _institution_match_score(self, text: str) -> int:
        """3 = exactly the configured school, 2 = "<school> University" or "<school>,
        Library" (optionally a parenthetical; LibLynx names schools "<school>, Library",
        2026-11-02), 1 = merely contains it. Only 2+ is ever clicked.

        Parentheses that only repeat the school's other names keep the score of
        the name before them: Elsevier lists a school as "<Chinese name>(<English
        name>) (<English name>)", next to other schools whose names contain its own."""
        text = " ".join(str(text or "").translate(self._QUOTES).split()).lower().strip(" .,:;")
        # Long English names fit: "华中科技大学(Huazhong University of Science and Technology) (...)".
        aliased = re.fullmatch(r"([^()]+?)((?:\s*\([^()]{1,120}\))+)", text)
        if aliased:
            head = self._institution_match_score(aliased.group(1))
            notes = re.findall(r"\(([^()]{1,120})\)", aliased.group(2))
            if head >= 2 and all(self._institution_match_score(note) >= 2 for note in notes):
                return head
        best = 0
        text = re.sub(r"^the ", "", text)  # "University of Kita" is "The University of Kita"
        if self._name_residue(text) == "":
            return 3  # only the school's own names ("<Chinese name> <English name>")
        for name in self._institution_names():
            name = re.sub(r"^the ", "", " ".join(name.translate(self._QUOTES).split()).lower())
            if not name:
                continue
            if text == name:
                best = max(best, 3)
            elif re.fullmatch(re.escape(name) + r"(?: university)?(?:,? (?:the )?librar(?:y|ies))?(?: \([^)]{1,40}\))?", text):
                best = max(best, 2)
            elif name in text:
                best = max(best, 1)
        return best

    _ENTRY_SELECTOR = "li, a, button, [role=option], [role=button]"

    # An entry's own identifiers: its link and data attributes, and the hidden
    # fields and data attributes of the elements around it that hold no other
    # entry (Elsevier keeps each result's entityID in a hidden field, 2026-10-31).
    _ENTRIES_JS = """(sel) => {
                const all = [...document.querySelectorAll(sel)];
                const visible = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
                const cands = all.filter(visible);
                const inner = cands.filter(el => !cands.some(o => o !== el && el.contains(o)));
                const ids = el => {
                    const out = [el.href || el.getAttribute('href') || ''];
                    for (let row = el, up = 0; row && up < 4; up++) {
                        for (const a of row.attributes || []) if (a.name.startsWith('data-')) out.push(a.value);
                        for (const h of row.querySelectorAll('input[type=hidden]')) out.push(h.value || '');
                        const parent = row.parentElement;
                        if (!parent || inner.some(o => o !== el && parent.contains(o))) break;
                        row = parent;
                    }
                    return out.filter(Boolean).join(' ').slice(0, 4000);
                };
                return inner.map(el => ({i: all.indexOf(el), t: (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim(),
                                         h: el.href || el.getAttribute('href') || '', ids: ids(el)}))
                    .filter(it => it.t && it.t.length <= 160);
            }"""

    def _institution_entry_score(self, entry: dict, entity_id: str) -> int:
        if self._carries_entity_id(str(entry.get("ids") or ""), entity_id):
            return 4
        return self._institution_match_score(entry.get("t", ""))

    def _name_residue(self, text: str) -> str | None:
        """What is left of ``text`` (lower case) once the school's names are taken
        out, as words; None when it holds none of them."""
        names = sorted({re.sub(r"^the ", "", " ".join(n.translate(self._QUOTES).split()).lower())
                        for n in self._institution_names()} - {""}, key=len, reverse=True)
        rest, found = f" {text} ", False
        for name in names:
            if name in rest:
                rest, found = rest.replace(name, " "), True
        return " ".join(re.sub(r"[\W_]+", " ", rest).split()) if found else None

    # Words a unit of the school itself may add to its name (its library, campus,
    # hospital): such an entry may be the school's, so the search settles nothing.
    _OWN_UNIT = re.compile(r"^(?:graduate school|school of|faculty of|department of|institute of|cent(?:er|re) for)\b"
                           r"|^(?:(?:the|main|central|university|univ|library|libraries|campus|branch|hospital|"
                           r"medical|medicine|dentistry|nursing|pharmacy|law|business|graduate|department|"
                           r"health|engineering|center|centre|faculty|school|college|of|and)\b\s*)+$")

    # A search's own word that it found nothing (Elsevier's "Can't find your
    # institution?" is always there and does not count).
    _NO_RESULTS = re.compile(r"\bno (?:results?|matches|matching (?:institutions?|organi[sz]ations?)|"
                             r"(?:institutions?|organi[sz]ations?) (?:were )?found)\b|\b0 results\b|"
                             r"没有找到|无结果|未找到|找不到(?:相关|匹配)", re.I)
    # How long the results must stay the same before they settle the school's absence.
    SEARCH_SETTLED_SEC = 4

    def _search_lists_no_school(self, page: Any, result: DownloadResult, url: str, scored: list) -> bool:
        """The school's name was searched on this page, the results are shown and
        have not changed for ``SEARCH_SETTLED_SEC``, and none is the school: other
        schools whose names contain its own ("<school> of Advanced Science",
        Elsevier 2026-11-11), or the search saying it found none. Then the publisher has no entry for the school: the login ends at
        once (``_institution_not_listed``), not at the end of the wait."""
        def searched_here(event: dict) -> bool:
            # A record keeps 500 characters: a long address (Elsevier ID's) is cut short in it.
            where = str(event.get("detail", "")).split(" @ ", 1)[-1]
            return event["state"] == "auto_institution_search" and len(where) > 10 and url.startswith(where)

        if not any(searched_here(e) for e in result.events):
            return False  # nothing searched here: a page's other lists say nothing
        others = sorted({str(it.get("t") or "")[:80] for score, it in scored if score == 1})
        # A unit of the school (its library, campus, a faculty) may be its way in,
        # unless its publisher marks it as signing in no one (IP, VPN, email).
        may_sign_in = [str(it.get("t") or "") for score, it in scored if score == 1
                       and self.adapter.institution_entry_signs_in(unquote(str(it.get("ids") or ""))) is not False]
        residues = [self._name_residue(" ".join(o.translate(self._QUOTES).split()).lower()) for o in may_sign_in]
        if any(r is not None and self._OWN_UNIT.match(r) for r in residues):
            return False  # perhaps the school's own library or campus: left to the user
        if others:
            evidence = f"{len(others)} other entries: " + "; ".join(others[:3])
        else:
            try:
                said = self._NO_RESULTS.search(self._body_text(page, 4_000) or "")
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
                return False
            if not said:
                return False  # results not shown yet: looked at again next pass
            evidence = f'"{said.group(0)}"'
        now = time.time()
        seen = getattr(result, "_search_miss", None)
        if not seen or seen[0] != url or seen[1] != evidence:
            result._search_miss = (url, evidence, now)
            return False
        if now - seen[2] < self.SEARCH_SETTLED_SEC:
            return False
        self._event(result, "auto_institution_not_found",
                    f"{self.institution_query} (search: {evidence[:160]}) @ {url}")
        result._institution_not_listed = True
        return True

    def _click_unique_institution_entry(self, page: Any, result: DownloadResult, url: str) -> bool:
        """Click the single best visible entry for the configured school.

        An entry carrying the school's entityID wins (several such entries are
        the same school); otherwise the entry naming it. Only innermost
        candidates count (a list item and its link are one entry). Two entries
        with the same best name score, or only partial matches, are left to the
        user; the same text with the same link (an actual link, not two
        buttons) is one school (SAMS Sigma's "Recently Chosen" above its full
        list, 2026-11-01).
        """
        try:
            items = page.evaluate(self._ENTRIES_JS, self._ENTRY_SELECTOR)
        except Exception:
            return False
        if not isinstance(items, list):
            return False
        entity_id = self._entity_id()

        scored = [(self._institution_entry_score(it, entity_id), it) for it in items if isinstance(it, dict)]
        if self.federation is not None:
            # An entry its publisher marks as signing in no school (Elsevier's
            # entries carry their route: IP, VPN or a work email, no entityID) is
            # not the school's sign-in, whatever its name (2026-11-11).
            without = [it for score, it in scored if score >= 2
                       and self.adapter.institution_entry_signs_in(unquote(str(it.get("ids") or ""))) is False]
            if without:
                scored = [(score, it) for score, it in scored if not any(it is w for w in without)]
                if not any(score >= 2 for score, _ in scored):
                    self._event(result, "auto_institution_not_found",
                                f"{self.institution_query} (listed only without a school sign-in: "
                                f"{len(without)} entr{'y' if len(without) == 1 else 'ies'}) @ {url}")
                    result._institution_not_listed = True
                    return False
        top = max([score for score, _ in scored] or [0])
        best = [it for score, it in scored if score == top]
        if top < 2 and self.federation is not None and self._search_lists_no_school(page, result, url, scored):
            return False
        same = (len(best) == 1 or top == 4
                or (len({(it.get("t"), it.get("h")) for it in best}) == 1 and best[0].get("h")))
        if top < 2 or not same:
            # The entries' names first (all of them), then what each carries.
            seen = (" | ".join(str(it.get("t") or "")[:50] for it in best[:8]) + " :: "
                    + "; ".join(unquote(str(it.get("ids") or ""))[:600] for it in best[:4]))
            if top >= 1 and not any(e["state"] == "institution_entries_ambiguous"
                                    and str(e.get("detail", "")).startswith(seen) for e in result.events):
                # Which entries were alike, and what each carries: the record to
                # tell the school's entry from the others by (Elsevier listed two
                # entries with one school's name, neither its federation's, 2026-11-11).
                self._event(result, "institution_entries_ambiguous", f"{seen} @ {url[:200]}")
            return False
        target = best[0]
        before = str(getattr(page, "url", "") or "")
        try:
            marked = page.evaluate("""([sel, idx]) => {
                const el = document.querySelectorAll(sel)[idx];
                if (!el || el.getClientRects().length === 0) return false;
                document.querySelectorAll('[data-paper-search-entry]').forEach(e => e.removeAttribute('data-paper-search-entry'));
                el.setAttribute('data-paper-search-entry', ''); return true;
            }""", [self._ENTRY_SELECTOR, target["i"]])
        except Exception:
            return False
        if marked is not True:
            return False
        try:
            # A real click, as the user's: the GWT rows of OpenAthens Wayfinder
            # (Wolters Kluwer OneID) ignore a script's click() (cold start, 2026-11-01).
            page.locator("[data-paper-search-entry]").first.click(timeout=3_000)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            # Custom listboxes can commit their option on mousedown (Cambridge
            # WAYF), before blur closes the list. HTMLElement.click() alone
            # leaves the option unselected even though no error is raised.
            # This is only the already matched institution, never a challenge
            # widget, credential field or another default choice.
            # Omit MouseEventInit.view: an isolated evaluation world's window
            # can be rejected as a Window, and the selection does not need it.
            try:
                clicked = page.evaluate("""() => {
                    const el = document.querySelector('[data-paper-search-entry]');
                    if (!el || !el.getClientRects().length || el.closest('[disabled], [aria-disabled="true"]'))
                        return false;
                    const options = {bubbles:true, cancelable:true, button:0};
                    el.dispatchEvent(new MouseEvent('mousedown', {...options, buttons:1}));
                    el.dispatchEvent(new MouseEvent('mouseup', options));
                    el.click();
                    return true;
                }""")
                if clicked is not True:
                    return False
                self._event(result, "institution_entry_dispatched", "mouse sequence after native click failure")
            except Exception as again:
                if not _is_browser_error(again):
                    raise
                self._event(result, "institution_select_error", str(again).split("\n", 1)[0][:200])
                return False
        self._event(result, "auto_institution_entry", f"{target['t'][:80]} @ {url}")
        self._event(result, "institution_selected", target["t"][:80] + (" (entityID)" if top == 4 else ""))
        if top < 4:
            # Chosen by its name: what the entry carries, to tell later whether it
            # was the school's sign-in (Elsevier's entries carry their route, 2026-11-11).
            self._event(result, "institution_entry_data", unquote(str(target.get("ids") or ""))[:480])
        if not self._left_page(page, before):
            # Elsevier ID's entry goes straight on to the school; its page's other
            # "Submit and continue" belongs to something else.
            self._click_optional_continue(page, result, after_selection=True)
        return True

    @staticmethod
    def _any_visible(page: Any, selectors: tuple[str, ...]) -> bool:
        """Whether any of ``selectors`` shows on the page now (no waiting)."""
        for selector in selectors:
            try:
                if page.locator(selector).first.is_visible() is True:
                    return True
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
        return False

    @staticmethod
    def _left_page(page: Any, url: str, timeout_ms: int = 5_000) -> bool:
        """True once the page has gone on from ``url`` by itself."""
        try:
            page.wait_for_url(lambda now: now != url, timeout=timeout_ms)
            return True
        except Exception as exc:
            if _is_browser_error(exc, "TimeoutError"):
                return False
            if not _is_browser_error(exc):
                raise
            # The wait was cut off by the navigation itself (an aborted
            # navigation, a detached frame: an Atypon chooser going on to the
            # school failed the article, 2026-11-01): the page has gone on.
            return True

    # The school's name may follow "for" with no space: RSNA writes
    # "for<em>Example University</em>" (2026-11-07).
    _NO_INSTITUTION_SEARCH_RESULTS = re.compile(
        r"^(?:no (?:institutions?|results?|matches) found(?:[.!]?$|\s+for)"
        r"|we couldn['’]t find any results? for)", re.I)
    _INSTITUTION_LIST_LINK = re.compile(r"^(?:select|choose) (?:your|an) institution from (?:a|the) list$", re.I)

    def _handle_institution_search_miss(self, page: Any, result: DownloadResult, url: str) -> bool:
        """Use a visible negative result for our search, and try an offered list first."""
        if (not (self._on_publisher_host(url) or self._is_federation_chooser(url))
                or self._is_challenge_page(page)
                or any(e["state"] == "auto_institution_list_opened" and e.get("detail") == url for e in result.events)):
            return False
        queries = {e.get("detail", "") for e in result.events if e["state"] == "auto_institution_search"}
        try:
            notice = page.get_by_text(self._NO_INSTITUTION_SEARCH_RESULTS).filter(visible=True).first
            if notice.is_visible() is not True:
                return False  # no candidate yet does not establish an empty result
            message = notice.inner_text(timeout=800)
            named = re.split(r"\bfor", message, maxsplit=1, flags=re.I)[1:]
            ours = {q.rsplit(" @ ", 1)[0] for q in queries if q.endswith(f" @ {url}")}
            typed = [str(box.input_value(timeout=800) or "").strip()
                     for box in (page.locator(selector).first for selector in self._institution_search_selectors(page))
                     if box.is_visible() is True]
            if any(typed) and not any(value in ours for value in typed):
                return False  # the box holds another query now: the reply is not about ours
            if named:
                # The reply names the query it answers. RSNA's box, once it held the
                # name, had lost the placeholder it was found by, and the miss went
                # unseen until the page wait ran out (2026-11-08).
                if not any(self._canonical_school_name(named[0]) == self._canonical_school_name(q) for q in ours):
                    return False  # the reply names a different query
            elif not any(value in ours for value in typed):
                return False
            listing = page.get_by_role("link", name=self._INSTITUTION_LIST_LINK).filter(visible=True).first
            if listing.is_visible() is True:
                href = listing.get_attribute("href", timeout=800)
                if (href and self._manual_institution_target_allowed(urljoin(url, href))
                        and self._click_control(page, listing, result, "open institution list")):
                    self._event(result, "auto_institution_list_opened", url)
                    return True
                if not any(e["state"] == "auto_institution_list_refused" and e.get("detail", "").endswith(url)
                           for e in result.events):
                    self._event(result, "auto_institution_list_refused", f"{str(href)[:160]} @ {url}")
                return False  # there is another route; don't call the school missing
            self._event(result, "auto_institution_not_found", f"{message[:120]} @ {url}")
            result._institution_not_listed = True
            return False
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            self._event(result, "institution_step_interrupted", type(exc).__name__)
        return False

    def _assist_configured_institution(self, page: Any, result: DownloadResult) -> bool:
        """Pick the user's configured institution on the current page.

        Order: a remembered "Access through <school>" entry; the single best
        visible entry naming the school (lists shown after the federation is
        set, search results); the school in a dropdown; then type the school
        into an empty institution search box. Ties and partial matches between
        several entries are left to the user, typed input is never replaced,
        and Continue follows only our own selection.
        """
        names = [n for n in self._institution_names() if n]
        if not names:
            return False
        url = str(getattr(page, "url", "") or "")
        done = {(e["state"], e.get("detail", "").split(" @ ")[-1]) for e in result.events}

        def once(action: str) -> bool:
            return (f"auto_{action}", url) not in done

        # 1. remembered entry on an article/access page: "Access through <school>"
        #    under any of its names ("<Chinese name>(<English name>) (...)", Elsevier ID)
        if once("remembered_entry"):
            entries = []
            for role in ("link", "button"):
                try:
                    for entry in page.get_by_role(role, name=re.compile(r"^\s*access through\s*\S", re.I)).all()[:10]:
                        if entry.is_visible() is True:
                            label = re.sub(r"^\s*access through\s*", "", entry.inner_text(timeout=1_000), flags=re.I)
                            entries.append((self._institution_match_score(label), label, entry))
                except Exception:
                    continue
            if not any(score >= 2 for score, _, _ in entries):
                # A widget's accessible name can differ from its visible school
                # text, or it can be a clickable div/span without a role. Use
                # the visible control text, still requiring a click affordance.
                try:
                    candidates = page.evaluate("""() => {
                        document.querySelectorAll('[data-paper-search-remembered]').forEach(e =>
                            e.removeAttribute('data-paper-search-remembered'));
                        const items = [...document.querySelectorAll('a,button,[role="button"],div,span')].filter(el => {
                            const native = el.matches('a[href],button,[role="button"]');
                            if (!native && el.closest('a,button,[role="button"]')) return false;
                            const text = (el.textContent || '').trim();
                            return text.length <= 160 && /^access through\\s*\\S/i.test(text)
                                && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden'
                                && !el.disabled && el.getAttribute('aria-disabled') !== 'true'
                                && (native || typeof el.onclick === 'function' || getComputedStyle(el).cursor === 'pointer');
                        });
                        return items.filter(el => !items.some(other => other !== el && el.contains(other)))
                            .slice(0,10).map((el,i) => {
                                el.setAttribute('data-paper-search-remembered', String(i));
                                return {i, text:(el.textContent || '').trim()};
                            });
                    }""")
                except Exception as exc:
                    if not _is_navigation_cut(exc):
                        raise
                    # The page navigated while it was read, e.g. the user chose
                    # a school (Karger's wayfinder): looked at again next pass.
                    self._event(result, "login_navigation_interrupted", "institution-entry")
                    return False
                if isinstance(candidates, list):
                    for candidate in candidates:
                        label = re.sub(r"^\s*access through\s*", "", candidate["text"], flags=re.I)
                        entries.append((self._institution_match_score(label), label,
                                        page.locator(f'[data-paper-search-remembered="{candidate["i"]}"]')))
            top = max((score for score, _, _ in entries), default=0)
            best = [(label, entry) for score, label, entry in entries if score == top]
            if top >= 2 and len(best) == 1:
                self._event(result, "auto_remembered_entry", f"{best[0][0][:80]} @ {url}")
                try:
                    best[0][1].click(timeout=5_000, no_wait_after=True)
                except Exception as exc:
                    if not _is_browser_error(exc):
                        raise
                    # The page moved on by itself (OpenAthens forwards to the
                    # remembered school, 2026-11-01): nothing left to click.
                    return False
                return True
        # 2. a visible entry carrying the school's entityID or naming it (after federation choice / search)
        if self._click_unique_institution_entry(page, result, url):
            return True
        # 3. a dropdown listing the school: _select_from_institution_lists, asked first.
        # 4. type the school into an empty institution search box (once per page);
        # never on a verification page, which the challenge wait takes first: a
        # search there found no school and ended the login (fixture, 2026-11-01).
        if not once("institution_search"):
            return self._handle_institution_search_miss(page, result, url)
        if not self._is_challenge_page(page):
            if self._assist_federation_discovery(page, result):
                self._event(result, "auto_institution_search", f"{self.federation.code} @ {url}")
                return True
            for selector in self._institution_search_selectors(page):
                try:
                    box = page.locator(selector).first
                    if box.is_visible(timeout=800) is not True:
                        continue
                    if str(box.input_value(timeout=2_000) or "").strip():
                        return False  # the user is typing; never replace it
                    # The English name, with a straight apostrophe (CARSI writes "Xi’an", 2026-11-01).
                    query = next((q for q in (n.translate(self._QUOTES) for n in names) if q.isascii()), names[0])
                    # Key by key: search-as-you-type lists (SAMS Sigma, OpenAthens)
                    # do not search on a filled value (2026-11-01).
                    box.press_sequentially(query, delay=40)
                    try:
                        # Briefly: a read with the default 30 s timeout stalled every
                        # school choice on AHA's and Neurology's choosers (2026-11-01).
                        typed = str(box.input_value(timeout=2_000) or "")
                    except Exception as exc:
                        if not _is_browser_error(exc):
                            raise
                        typed = query  # not readable now: go on to the results
                    if typed != query and query.endswith(typed):
                        # Keys typed while the search was still loading are lost
                        # (the school's name without its first word, RSC 2026-11-01).
                        settle(page, 1_000)
                        box.fill("")
                        box.press_sequentially(query, delay=40)
                        self._event(result, "institution_search_retyped", f"{typed[:40]} @ {url}")
                    self._event(result, "auto_institution_search", f"{query} @ {url}")
                    # The results list as soon as it shows the school (at most 5 s).
                    if pump_until(page, lambda: self._click_unique_institution_entry(page, result, url), 5_000):
                        return True
                    # No successful selection within this short poll does not
                    # prove absence: results may arrive later, be ambiguous or
                    # temporarily unclickable. The login's existing page budget
                    # bounds later passes, which inspect the entries again.
                    self._event(result, "institution_list_not_ready", f"search selection pending @ {url}")
                    return False
                except Exception as exc:
                    # Kept, not dropped: this step once stalled 30 s without a trace.
                    self._event(result, "institution_search_error",
                                f"{selector}: {type(exc).__name__}: {str(exc)[:160]} @ {url}")
                    continue
        return False

    # SeamlessAccess's "Access through your institution" button: RSC's own class, and
    # the standard one ("ra21-button", De Gruyter's LibLynx page, 2026-11-02).
    _SA_BUTTON = "button.js-sa-federated-login, button.ra21-button"
    _SA_GENERIC_LABELS = frozenset({"access through your institution", "access through your organization",
                                    "access through your organisation"})
    # SeamlessAccess's newer button sits in a frame of its own, with its "change" link (#dsbutton).
    _SA_CTA_FRAME = "https://service.seamlessaccess.org/cta"

    def _open_seamlessaccess_chooser(self, page: Any, result: DownloadResult) -> bool:
        """Open the institution search behind a SeamlessAccess button; nothing is chosen here.

        The generic "Access through your institution" button is pressed. A button
        naming another remembered school is changed through its "change
        institution" link; the configured school's button is clicked by
        _assist_configured_institution. The button does nothing until the
        SeamlessAccess frame has loaded (RSC, 2026-11-01): it is pressed only
        then, and once more when the page has not moved on 10 seconds later.
        SeamlessAccess's newer button sits in its own frame (``/cta/``): looked for
        there when the page has none (AIP's institutional login, 2026-11-03); a
        button there naming the configured school is pressed as it is.
        """
        url = str(getattr(page, "url", "") or "")
        tries = sum(e["state"] == "seamlessaccess_chooser_opened" and e.get("detail") == url for e in result.events)
        if tries >= 2:
            return False
        try:
            where, change = page, ".js-sa-change-institution"
            button = page.locator(self._SA_BUTTON).first
            if button.is_visible() is not True:
                frames = page.frames if isinstance(page.frames, (list, tuple)) else []
                where = next((f for f in frames if str(getattr(f, "url", "") or "").startswith(self._SA_CTA_FRAME)), None)
                if where is None:
                    return False
                button, change = where.locator(self._SA_BUTTON).first, "#dsbutton"
                if button.is_visible() is not True:
                    return False
            label = " ".join(str(button.inner_text(timeout=1_000) or "").split()).lower()
            target = button
            if label not in self._SA_GENERIC_LABELS:
                ours = self._institution_match_score(re.sub(r"^access through\s+", "", label)) >= 2
                if tries or (ours and where is page):
                    return False
                if not ours:
                    target = where.locator(change).first
                    if target.is_visible() is not True:
                        return False
            if where is page and not any("seamlessaccess.org/ps" in str(getattr(frame, "url", "")) for frame in page.frames):
                return False
            target.click(timeout=5_000, no_wait_after=True)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return False
        self._event(result, "seamlessaccess_chooser_opened", url)
        if target is button:
            self._left_page(page, url, timeout_ms=10_000)
        return True

    def _assist_federation_discovery(self, page: Any, result: DownloadResult) -> bool:
        """On the school's federation's own discovery page (CARSI's), type the
        configured institution and click its entry.

        Publisher federation choosers are left alone: there the only automatic
        step is selecting the federation. Nothing is submitted here; the
        user confirms in the window. Without a match the page is left as is.
        """
        federation = self.federation
        if federation is None or not federation.on_discovery_page(str(getattr(page, "url", "") or "")):
            return False
        if any(event["state"] == "institution_selected" for event in result.events):
            return False
        for selector in (*_INSTITUTION_SEARCH_SELECTORS, "input[type='search']", "input[type='text']"):
            try:
                box = page.locator(selector).first
                if not box.is_visible(timeout=1_500):
                    continue
                if (box.input_value(timeout=2_000) or "").strip():
                    return False  # the user already typed; never overwrite
                box.fill(self.institution_query)
                self._event(result, "institution_search", f"{federation.code}:{selector}")
                pump_until(page, lambda: self._any_visible(page, self._institution_result_selectors()), 2_000)
                for result_selector in self._institution_result_selectors():
                    try:
                        option = page.locator(result_selector).first
                        if option.is_visible(timeout=1_500):
                            option.click(timeout=5_000, no_wait_after=True)
                            self._event(result, "institution_selected", result_selector)
                            return True
                    except Exception:
                        continue
                return False
            except Exception:
                continue
        return False

    def _click_institution_search_result(self, page: Any, result: DownloadResult) -> bool:
        for result_selector in self._institution_result_selectors():
            try:
                page.locator(result_selector).first.click(timeout=5_000)
                self._event(result, "institution_selected", result_selector)
                self._click_optional_continue(page, result, after_selection=True)
                return True
            except Exception:
                continue
        try:
            clicked = page.evaluate(
                """
                (query) => {
                  const needle = (query || '').toLowerCase();
                  if (!needle) return null;
                  const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                  };
                  const textOf = (el) => [
                    el.innerText || '',
                    el.textContent || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('title') || ''
                  ].join(' ').replace(/\\s+/g, ' ').trim();
                  const candidates = [...document.querySelectorAll('a,button,[role="button"],[role="option"],li,div,span')]
                    .filter(visible)
                    .filter((el) => {
                      const text = textOf(el).toLowerCase();
                      return text.includes(needle) && text.length < 300;
                    });
                  const target = candidates.find((el) => textOf(el).toLowerCase().includes(needle));
                  if (!target) return null;
                  const clickable = target.closest('a,button,[role="button"],[role="option"],li') || target;
                  const detail = textOf(clickable).slice(0, 160);
                  clickable.click();
                  return detail;
                }
                """,
                self.institution_query,
            )
            if clicked:
                self._event(result, "institution_selected", str(clicked))
                self._click_optional_continue(page, result, after_selection=True)
                return True
        except Exception:
            return False
        return False

    # Labels that name no institution; never treated as a remembered school.
    _GENERIC_INSTITUTION_LABELS = frozenset({
        "your institution", "your organization", "your organisation", "another organization",
        "another organisation", "another institution", "university", "institution",
    })

    # Campus identity-provider hostnames (idp.example.edu.cn, ids.lzu.edu.cn, sso.x.edu ...).
    _IDP_HOST_RE = re.compile(r"^(?:idp?|ids|sso|cas|login|passport|auth(?:server)?|shibboleth|webauth)\.[^/]+\.edu(?:\.cn)?$")
    # Identity services schools sign in with behind their identity provider (the
    # school's own tenant there): Microsoft Entra, Okta, OneLogin, Auth0, Ping,
    # SeciossLink (2026-11-11: four schools' logins went on to these).
    _IDENTITY_SERVICE_HOSTS = ("login.microsoftonline.com", "okta.com", "oktapreview.com", "onelogin.com",
                               "auth0.com", "pingone.com", "b2clogin.com", "secioss.com")

    def _institution_names(self) -> tuple[str, ...]:
        """The school being chosen, plus its English name when it is the one saved by setup.

        Setup saves both names from the federation's list; the package names no school itself.
        """
        query = (self.institution_query or "").strip()
        names = [query] if query else []
        if query and query == schools.name(self.config):
            names.extend(n for n in schools.names(self.config) if n not in names)
        return tuple(names)

    def _entity_id(self) -> str:
        """The configured school's SAML entityID (``schools.entity_id``), resolved once."""
        configured = str(self.config.get("idp_entity_id") or "").strip()
        if configured:
            return configured
        resolved = getattr(self, "_resolved_entity_id", None)
        if resolved is None:
            try:
                from ..config import DATA_DIR

                resolved = schools.entity_id(self.config, DATA_DIR)
            except Exception as exc:  # an unreadable copy: the names decide
                logger.info("institution: member list unreadable (%s)", type(exc).__name__)
                resolved = ""
            self._resolved_entity_id = resolved
        return resolved

    @staticmethod
    def _carries_entity_id(text: str, entity_id: str) -> bool:
        """True when ``text`` (an entry's link, data attributes and hidden fields) names
        exactly ``entity_id``, plain, URL-encoded once or twice, or JSON-escaped."""
        if not entity_id or not text:
            return False
        decoded = [text]
        for _ in range(2):
            decoded.append(unquote(decoded[-1]))
        pattern = re.compile(r"(?<![\w.:/-])" + re.escape(entity_id) + r"(?![\w.:/-])")
        return any(pattern.search(t.replace("\\/", "/")) for t in decoded)

    def _on_school_login_page(self, url: str) -> bool:
        """The configured school's own login page on a service shared by many
        schools (``schools.login_pages``: its OpenAthens sign-in page)."""
        return schools.on_login_page(self.config, url)

    def _is_idp_host(self, host: str) -> bool:
        """True for the configured school's identity provider or any generic campus IdP
        hostname, and for a host this item's login reached on the school's side
        (``_follow_login_route``)."""
        host = (host or "").lower().split(":")[0]
        if not host:
            return False
        return host in getattr(self, "_school_side_hosts", ()) or self._known_school_host(host)

    def _known_school_host(self, host: str) -> bool:
        """The school's side by the host alone: its login hosts and domains, the
        identity services schools sign in with, a generic campus IdP hostname."""
        if any(token in host for token in _school_auth_patterns(self.config)):
            return True
        if any(host == d or host.endswith("." + d) for d in (*schools.domains(self.config), *self._IDENTITY_SERVICE_HOSTS)):
            return True
        return bool(self._IDP_HOST_RE.match(host))

    # ---- the school's side, by the way this item's login went there

    def _follow_login_route(self, page: Any, result: DownloadResult):
        """Watch this item's main-frame navigations, every redirect hop included, by
        their addresses only (never form data); returns the function that stops.

        A login that went from the publisher through a federation, a login service
        or an address asking for an identity provider (``_route_hop``) and reached a
        host that is none of these, before it came back to the publisher, is on the
        school's side: its identity provider on a host of another domain, and what
        that signs in with. The host counts as the school's for the rest of the item
        (``_is_idp_host``), so nothing is chosen or typed there (2026-11-12: a
        school's OpenAthens sign-in went on to its university system's login host,
        where the school's name was typed into a field)."""
        self._school_side_hosts: set[str] = set()
        self._route_hosts: set[str] = set()
        self._publisher_hosts: set[str] = set()
        self._route_away = False
        self._route_last_host = ""
        self._school_unreachable = ""

        def requested(request: Any) -> None:
            if request.is_navigation_request() and request.frame == page.main_frame:
                self._note_route_hop(str(request.url or ""), result)

        def failed(request: Any) -> None:
            # A navigation to the school's side that the network ended (its login
            # server did not answer): the browser shows its own error page next.
            if request.is_navigation_request() and request.frame == page.main_frame:
                failure = str(request.failure or "")
                host = (urlparse(str(request.url or "")).hostname or "").lower()
                if "net::ERR_" in failure and "ERR_ABORTED" not in failure and self._is_idp_host(host):
                    self._school_unreachable = f"{host}: {failure}"

        page.on("request", requested)
        page.on("requestfailed", failed)

        def stop() -> None:
            page.remove_listener("request", requested)
            page.remove_listener("requestfailed", failed)
            self._school_side_hosts = set()
            self._school_unreachable = ""

        return stop

    def _note_route_hop(self, url: str, result: DownloadResult) -> None:
        kind = self._route_hop(url)
        if not kind:
            return
        host = (urlparse(url).hostname or "").lower()
        if kind in ("school", "route"):
            self._route_away = True
            if kind == "route" and self._names_identity_provider(url) and not self._login_service_host(host):
                # A publisher's or its platform's sign-in hub: its later pages are not the school's.
                self._route_hosts.add(host)
        elif kind == "publisher":
            self._route_away = False
            # Its other pages too (a journal site's sign-in step after its article).
            self._publisher_hosts.add(host)
        elif self._route_away and host not in self._route_hosts and host not in self._school_side_hosts:
            self._school_side_hosts.add(host)
            self._event(result, "school_side_host", f"{host} after {self._route_last_host}")
        self._route_last_host = host

    def _route_hop(self, url: str) -> str:
        """What one navigation hop is to the login: ``school`` (the school's side by
        its host or its login page on a shared service), ``route`` (a federation's
        or login service's page, or an address asking for an identity provider),
        ``publisher`` (its pages, its own chooser, a host this item saw as its own),
        ``other``; "" for no web address. The publisher's own chooser is no route:
        a page the browser passed on its way back to the journal site was taken for
        the school's (2026-11-12)."""
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or not host:
            return ""
        if self._known_school_host(host) or self._on_school_login_page(url):
            return "school"
        if self._names_identity_provider(url) or self._login_service_host(host) or federations.on_discovery_page(url):
            return "route"
        if (host in getattr(self, "_publisher_hosts", ()) or self._on_publisher_host(url)
                or self.adapter.is_institution_chooser(url)):
            return "publisher"
        return "other"

    # Query parameters by which a service provider or discovery service asks for
    # an identity provider (SAML discovery's ``entityID``, sign-in hubs' ``idp``).
    _IDP_PARAMS = frozenset({"entityid", "idp"})

    def _names_identity_provider(self, url: str) -> bool:
        """An address asking for an identity provider: it names the school's
        entityID, or an identity provider in ``_IDP_PARAMS``. An identity
        provider's own pages name none."""
        if self._carries_entity_id(url, self._entity_id()):
            return True
        return any(key.lower() in self._IDP_PARAMS and value.startswith(("http", "urn:"))
                   for key, values in parse_qs(urlparse(url).query).items() for value in values)

    @staticmethod
    def _login_service_host(host: str) -> bool:
        """A federation's own services or a login service shared by schools: never
        the school's side by its host."""
        return any(host == d or host.endswith("." + d)
                   for d in (*federations.service_domains(), *access_rules.AUTH_HOSTS))

    def _institution_result_selectors(self) -> tuple[str, ...]:
        """Result locators built from the configured institution name.

        Profile ``institution_result_selectors`` are templates: ``{institution}``
        is the only school they may name. Without a configured institution there
        is nothing to click, so the user picks by hand.
        """
        names = self._institution_names()
        if not names:
            return ()
        selectors: list[str] = []
        templates = tuple(self.profile.institution_result_selectors)
        for name in names:
            literal = name.replace("\\", "\\\\").replace("'", "\\'")
            selectors.extend((
                f"text={name}",
                f"button:has-text('{literal}')",
                f"a:has-text('{literal}')",
                f"[role='button']:has-text('{literal}')",
                f"[role='option']:has-text('{literal}')",
                f"li:has-text('{literal}')",
                f"div:has-text('{literal}')",
            ))
            selectors.extend(t.replace("{institution}", literal) for t in templates if "{institution}" in t)
        selectors.extend(t for t in templates if "{institution}" not in t)
        return tuple(dict.fromkeys(selectors))

    def _select_openathens_wayfinder(self, page: Any, result: DownloadResult) -> bool:
        current_url = str(getattr(page, "url", "") or "")
        parsed = urlparse(current_url)
        host = (parsed.netloc or "").lower()
        if not host.endswith("wayfinder.openathens.net"):
            return False
        entity_id = self._entity_id()
        if not entity_id.startswith("https://"):
            return False  # no configured IdP entityID: the user picks in the wayfinder
        return_url = parse_qs(parsed.query).get("return", [""])[0]
        if not return_url.startswith("https://connect.openathens.net/"):
            return False
        sep = "&" if "?" in return_url else "?"
        direct_url = return_url + sep + urlencode(
            {
                "entityID": entity_id,
                "target": current_url,
            }
        )
        try:
            open_page(page, direct_url, timeout_ms=30_000)
            self._event(result, "institution_selected", "OpenAthens entityID: configured idp_entity_id")
            return True
        except Exception as exc:
            self._event(result, "institution_select_error", f"{type(exc).__name__}: {exc}")
            return False

    _CHOOSER_URL_MARKERS = ("shibboleth.htm", "/action/ssostart", "wayfinder.openathens.net",
                            "/wayf", "/discovery", "/ds/", "institution-search")

    # A search box naming an institution in its placeholder or label, or in its id or
    # name (De Gruyter's LibLynx box has neither placeholder nor label, 2026-11-02).
    _INSTITUTION_INPUTS = ("input[placeholder*='nstitution']", "input[placeholder*='rganization']",
                           "input[placeholder*='机构']", "input[aria-label*='nstitution']",
                           "input[type='search'][id*='nstitution']", "input[type='search'][name*='nstitution']")

    def _institution_search_selectors(self, page: Any) -> tuple[str, ...]:
        """Inputs the school may be typed into. A publisher's broad selectors
        (``input[type='search']``, even ``input``) only on a page that asks for an
        institution: elsewhere they take the site's search box (jacc.org, 2026-10-31)."""
        if self.profile.institution_input_selectors and self._page_has_institution_chooser(page):
            return (*self.profile.institution_input_selectors, *self._INSTITUTION_INPUTS)
        return self._INSTITUTION_INPUTS

    def _page_has_institution_chooser(self, page: Any) -> bool:
        """True while the page asks the user to pick or type an institution.

        A long dropdown, an institution/organisation search field, a password
        field, or a known chooser URL means the user may still be choosing.
        A plain site-search box does not count. Errors count as "choosing": a missed
        Continue is harmless, a wrong one submits somebody else's school.
        """
        try:
            url = str(getattr(page, "url", "") or "").lower()
            if (any(marker in url for marker in self._CHOOSER_URL_MARKERS)
                    or any(domain in url for domain in federations.service_domains())):
                return True
            return bool(page.evaluate('''() => {
                const visible = (el) => !el.disabled && el.checkVisibility();
                const about = /institution|organi[sz]ation|university|school|federation|idp|机构|学校|单位|组织|联盟/i;
                const label = (el) => [el.getAttribute('placeholder'), el.getAttribute('name'), el.id,
                    el.getAttribute('aria-label'), el.getAttribute('title'),
                    el.labels && [...el.labels].map(l => l.innerText).join(' ')].join(' ');
                return [...document.querySelectorAll('select,input')].filter(visible).some(el => {
                    if (el.tagName === 'SELECT') return el.options.length >= 5 || about.test(label(el));
                    const type = (el.getAttribute('type') || 'text').toLowerCase();
                    if (type === 'password') return true;  // a login form is never submitted for the user
                    return ['text', 'search'].includes(type) && !el.readOnly && about.test(label(el));
                });
            }'''))
        except Exception:
            return True
