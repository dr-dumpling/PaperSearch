"""The school's login survives between browsers for 30 days by default, and is saved after
each paper, not only when the browser closes (user, 2026-11-19; it was 12 hours)."""
from __future__ import annotations

import json
import time
from unittest.mock import Mock

import pytest

from paper_search_school.browser import backend, profiles

LOGIN = {"name": "JSESSIONID", "value": "synthetic", "domain": ".idp.example", "path": "/", "expires": -1}


def write_store(profile, cookies, saved_at):
    (profile / profiles.SESSION_COOKIES_FILE).write_text(
        json.dumps({"saved_at": saved_at, "cookies": cookies}), encoding="utf-8")


@pytest.mark.parametrize("days,restored", [(1, 1), (29, 1), (31, 0)])
def test_a_saved_login_is_restored_within_30_days(tmp_path, days, restored):
    write_store(tmp_path, [LOGIN], time.time() - days * 24 * 3600)
    context = Mock()
    assert profiles._restore_session_cookies(context, tmp_path) == restored
    if restored:
        # Still a session cookie: the browser drops it at close, the file brings it back.
        assert "expires" not in context.add_cookies.call_args.args[0][0]


@pytest.mark.parametrize("config,hours", [
    ({}, 720),
    ({"browser_login_session_max_age_hours": 24}, 24),
    ({"browser_login_session_max_age_hours": "48"}, 48),
    ({"browser_login_session_max_age_hours": 0}, 720),
    ({"browser_login_session_max_age_hours": "a day"}, 720),
])
def test_the_window_comes_from_config(config, hours):
    assert backend._login_session_window_sec(config) == hours * 3600


def test_a_shorter_window_from_config_leaves_an_older_login(tmp_path):
    write_store(tmp_path, [LOGIN], time.time() - 30 * 3600)
    context = Mock(spec=["add_cookies", "close", "cookies"])
    backend._keep_session_cookies(context, tmp_path, {"browser_login_session_max_age_hours": 24})
    context.add_cookies.assert_not_called()


def test_the_login_is_saved_after_a_paper_without_closing_the_browser(tmp_path):
    context = Mock(spec=["add_cookies", "close", "cookies"])
    context.cookies.return_value = [LOGIN, {"name": "analytics", "value": "x", "domain": ".cdn.example",
                                            "path": "/", "expires": time.time() + 1000}]
    closer = context.close
    backend._keep_session_cookies(context, tmp_path, {})
    store = tmp_path / profiles.SESSION_COOKIES_FILE
    assert not store.exists()
    context.paper_search_keep_login()
    saved = json.loads(store.read_text(encoding="utf-8"))
    assert [cookie["name"] for cookie in saved["cookies"]] == ["JSESSIONID"]  # session cookies only
    closer.assert_not_called()


IDP = {"idp_entity_id": "https://idp.school.example/idp/shibboleth"}


def jar(*cookies):
    context = Mock(spec=["add_cookies", "close", "cookies"])
    context.cookies.return_value = list(cookies)
    return context


def test_the_schools_login_hosts_and_domains_come_from_its_saved_entry():
    hosts, domains = profiles.school_login_hosts({**IDP, "idp_login_hosts": ["cas.school.example"],
                                                  "idp_domains": ["school.example"]})
    assert hosts == {"idp.school.example", "cas.school.example"} and domains == {"school.example"}
    assert profiles.school_login_hosts({"idp_entity_id": "urn:mace:school.example"}) == (set(), set())
    assert profiles.school_login_hosts({}) == (set(), set())


def test_any_sign_in_of_the_school_whatever_it_names_its_cookies():
    # Shibboleth, CAS on the school's domain, a parent-domain cookie, a shared service the
    # sign-in went through: the cookies are taken by where they are, not by their names.
    lax = {"value": "x", "path": "/", "expires": -1, "sameSite": "Lax"}
    cookies = [dict(lax, name="shib_idp_session", domain="idp.school.example"),
               dict(lax, name="TGC", domain="cas.school.example"),
               dict(lax, name="portal", domain=".school.example"),
               dict(lax, name="tenant", domain="sso.shared-login.example"),
               dict(lax, name="publisher", domain=".publisher.example")]
    context = jar(*cookies)
    assert profiles.cross_site_login(context, {"idp.school.example", "sso.shared-login.example"}, {"school.example"}) == 4
    assert {c.args[0][0]["name"] for c in context.add_cookies.call_args_list} == {"shib_idp_session", "TGC", "portal", "tenant"}


def test_the_idps_cookies_go_with_a_publishers_saml_post(tmp_path):
    # A school tested, 2026-11-19: shib_idp_session without SameSite (Lax) was left out of the
    # cross-site POST of Nature, Taylor & Francis and Science, which then asked for the password.
    session = {"name": "shib_idp_session", "value": "s", "domain": "idp.school.example", "path": "/idp",
               "expires": -1, "httpOnly": True, "secure": False, "sameSite": "Lax"}
    conversation = {"name": "JSESSIONID", "value": "j", "domain": "idp.school.example", "path": "/idp",
                    "expires": 1_900_000_000, "httpOnly": True, "secure": True, "sameSite": "Lax"}
    done = dict(conversation, name="already", sameSite="None")
    other = {"name": "sid", "value": "u", "domain": "uis.school.example", "path": "/", "expires": -1, "sameSite": "Lax"}
    publisher = {"name": "SESSION", "value": "p", "domain": ".publisher.example", "path": "/", "expires": -1, "sameSite": "Lax"}
    context = jar(session, conversation, done, other, publisher)
    assert profiles.cross_site_login(context, {"idp.school.example"}) == 2
    added = [call.args[0][0] for call in context.add_cookies.call_args_list]
    assert [(c["name"], c["sameSite"], c["secure"]) for c in added] == [("shib_idp_session", "None", True), ("JSESSIONID", "None", True)]
    assert "expires" not in added[0] and added[1]["expires"] == 1_900_000_000  # a session cookie stays one
    assert profiles.cross_site_login(jar(session), set()) == 0


def test_kept_after_each_paper_and_when_restored(tmp_path):
    session = {"name": "shib_idp_session", "value": "s", "domain": "idp.school.example", "path": "/idp",
               "expires": -1, "sameSite": "Lax"}
    write_store(tmp_path, [session], time.time())
    context = jar(session)
    backend._keep_session_cookies(context, tmp_path, IDP)
    # Restored, then sent cross-site; again after the paper, then saved.
    assert [c.args[0][0].get("sameSite") for c in context.add_cookies.call_args_list] == [session["sameSite"], "None"]
    context.paper_search_keep_login()
    assert context.add_cookies.call_args.args[0][0]["sameSite"] == "None"
    assert (tmp_path / profiles.SESSION_COOKIES_FILE).exists()
    # A host the sign-in went through (a shared service) counts too.
    shared = {"name": "tenant", "value": "t", "domain": "sso.shared-login.example", "path": "/", "expires": -1, "sameSite": "Lax"}
    context.cookies.return_value = [shared]
    context.paper_search_keep_login({"sso.shared-login.example"})
    assert context.add_cookies.call_args.args[0][0]["name"] == "tenant"


# The ways schools' sign-ins are listed in federation metadata (20 federations, 2,931 identity
# providers, 2026-11-19): fictional schools, one per way.
SHAPES = [
    # entityID, SingleSignOnService host
    ("https://idp.redmagnolia.example/idp/shibboleth", "idp.redmagnolia.example"),   # the same host (73%)
    ("https://idp.oldname.example/idp/shibboleth", "idp.newname.example"),           # its own other host (17%)
    ("https://sts.windows.net/00000000-0000-0000-0000-000000000000/", "login.microsoftonline.com"),  # Microsoft
    ("https://idp.redmagnolia.example/openathens", "login.openathens.net"),          # OpenAthens
    ("urn:mace:redmagnolia.example", "idp.redmagnolia.example"),                     # a URN entityID
    ("http://adfs.redmagnolia.example/adfs/services/trust", "adfs.redmagnolia.example"),  # an http entityID (ADFS)
]


def metadata(entity_id, sso_host):
    return f"""<md:EntitiesDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
        xmlns:shibmd="urn:mace:shibboleth:metadata:1.0"><md:EntityDescriptor entityID="{entity_id}">
      <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
        <md:Extensions><shibmd:Scope regexp="false">redmagnolia.example</shibmd:Scope></md:Extensions>
        <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="https://{sso_host}/sso/post"/>
      </md:IDPSSODescriptor><md:Organization><md:OrganizationDisplayName xml:lang="en">Red Magnolia University</md:OrganizationDisplayName></md:Organization>
    </md:EntityDescriptor></md:EntitiesDescriptor>"""


@pytest.mark.parametrize("entity_id,sso_host", SHAPES)
def test_where_the_publishers_post_lands_is_the_schools_whatever_its_entity_id(entity_id, sso_host):
    import xml.etree.ElementTree as ET
    from paper_search_school.federations import by_code
    from paper_search_school.schools import lookup

    federation = by_code("ukfederation")
    (school, _names, _scopes), = lookup._metadata_schools(federation, ET.fromstring(metadata(entity_id, sso_host)))
    config: dict = {}
    lookup.save(config, school)
    hosts, domains = profiles.school_login_hosts(config)
    assert sso_host in hosts
    assert domains == {"redmagnolia.example"}
