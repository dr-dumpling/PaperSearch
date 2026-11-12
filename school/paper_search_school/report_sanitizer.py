"""Sanitization for shareable copies, never for the original local diagnosis.

HTML is a structural specimen, not an executable/offline copy of a website.
Unknown query parameters are dropped; keeping publisher paths and selector
attributes is enough to investigate entries without retaining signed sessions.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

MAX_HTML_BYTES = 256 * 1024
MAX_TEXT_CHARS = 6000
_URL = re.compile(r'https?://[^\s<>"\x27]+', re.I)
_AUTH = re.compile(r'login|sign[ _-]?in|saml|oauth|shibboleth|\bsso\b|identity|authenticate|authorize|idp|登录|登入|认证', re.I)
_SECRET = re.compile(r'cookie|header|authorization|password|passwd|secret|token|ticket|session|saml|relaystate|credential|storage|api.?key|csrf|nonce|signature', re.I)
_ASSIGNMENT = re.compile(
    r'(?i)\b(?:cookie|set-cookie|authorization|password|passwd|secret|[\w-]*token|ticket|'
    r'[\w-]*session[\w-]*|samlrequest|samlresponse|relaystate|code|csrf|nonce|signature)'
    r'\b[\s"\x27]*[:=]\s*(?:"[^"\n]*"|\x27[^\x27\n]*\x27|[^\s<>;,]+)')
_SAFE_QUERY = frozenset({'doi', 'article', 'articleid', 'id', 'pii', 'issue', 'volume', 'year', 'page', 'format', 'type'})
_OMIT = frozenset({'full_text', 'text_excerpt', 'pdf_path', 'file', 'record_path', 'diagnostic_path',
                   'traceback', 'browser', 'browser_start', 'screenshots', 'screenshot', 'html', 'path'})


def decoded(value: str) -> str:
    for _ in range(8):
        new = html.unescape(unquote(value))
        if new == value:
            break
        value = new
    if html.unescape(unquote(value)) != value:
        return '[ENCODED_VALUE_REMOVED]'
    return value


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or '').lower()
    except ValueError:
        return ''


class Redactor:
    def __init__(self, config: dict | None = None):
        self.terms: set[str] = set()
        self.school_hosts: set[str] = set()
        cfg = config or {}
        for key in ('school_name', 'school_name_en', 'idp_entity_id', 'institution_domain', 'idp_domain'):
            value = str(cfg.get(key) or '').strip()
            if len(value) > 2:
                self.terms.add(value)
                host = host_of(value) or (value if key.endswith('_domain') else '')
                if host:
                    self.school_hosts.add(host)
        # The hosts of the school's login pages, as its federation lists them.
        for value in cfg.get('idp_login_hosts') or ():
            host = str(value or '').strip().lower()
            if len(host) > 2:
                self.terms.add(host)
                self.school_hosts.add(host)
        for value in cfg.get('idp_domains') or ():
            host = str(value or '').strip().lower()
            if len(host) > 3:
                self.terms.add(host)
                self.school_hosts.add(host)
        for value in cfg.get('idp_login_pages') or ():
            page = str(value or '').strip()
            if len(page) > 2:
                self.terms.add(page)
        # The configured IdP often lives below the institution's domain.
        for host in list(self.school_hosts):
            if host.split('.')[0] in {'idp', 'sso', 'login', 'auth'} and host.count('.') >= 2:
                self.school_hosts.add(host.split('.', 1)[1])
        self.home = str(Path.home())
        self.usernames: set[str] = {Path.home().name}
        self.secrets: set[str] = set()
        for key, value in cfg.items():
            if _SECRET.search(key) and isinstance(value, str) and len(value) >= 6:
                self.secrets.add(value)

    def observe(self, data, depth: int = 0) -> None:
        """Discover school URLs from explicitly labelled school/IdP evidence.

        Generic federation login hosts are not automatically school domains.
        A bare login URL still loses its query and its screenshot is excluded.
        """
        if depth > 30:
            return
        if isinstance(data, dict):
            state = str(data.get('state') or '').lower()
            for key, value in data.items():
                if _SECRET.search(str(key)) and isinstance(value, str) and len(value) >= 6:
                    self.secrets.add(value)
                if isinstance(value, str) and (
                    key in {'idp_entity_id', 'idp_url', 'school_url', 'institution_domain'}
                    or ('school' in state and key in {'detail', 'url'})
                ):
                    for url in _URL.findall(decoded(value)):
                        host = host_of(url)
                        if host:
                            self.school_hosts.add(host)
                self.observe(value, depth + 1)
        elif isinstance(data, str):
            value = decoded(data)
            self.usernames.update(re.findall(r'(?i)(?:[A-Z]:[\\/](?:Users|Documents and Settings)[\\/]|/(?:Users|home)/)([^/\\\s"\x27]+)', value))
        elif isinstance(data, list):
            for row in data:
                self.observe(row, depth + 1)

    def school_url(self, url: str) -> bool:
        host = host_of(url)
        return any(host == h or host.endswith('.' + h) for h in self.school_hosts)

    def private_page(self, url: str, title: str = '', why: str = '') -> bool:
        return (not host_of(url) or self.school_url(url) or bool(_AUTH.search(url + ' ' + title))
                or bool(re.search(r'school|学校|账号', why, re.I)))

    def url(self, raw: str) -> str:
        value = decoded(raw)
        try:
            parts = urlsplit(value)
            if parts.scheme not in {'http', 'https', ''} or not parts.netloc and parts.scheme:
                return '[URL_REMOVED]'
            private = self.school_url(value)
            host = 'school.invalid' if private else (parts.hostname or '')
            if parts.port and not private:
                host += ':' + str(parts.port)
            auth = private or bool(_AUTH.search(parts.netloc + parts.path))
            path = '/[AUTH_PATH]' if private else parts.path
            path = re.sub(r'(?i)(/(?:token|ticket|session|code|saml|oauth|auth)/).*', r'\1[REDACTED]', path)
            path = re.sub(r'(?i);[^/]*', '', path)
            path = re.sub(r'(?<![\w-])[A-Za-z0-9_-]{48,}(?![\w-])', '[REDACTED]', path)
            query = [] if auth else [(k, v) for k, v in parse_qsl(parts.query)
                                     if k.lower() in _SAFE_QUERY and len(v) <= 160
                                     and not _SECRET.search(k) and '://' not in v
                                     and (v.isdigit() or (k.lower() == 'doi' and re.fullmatch(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', v))
                                          or (k.lower() in {'format', 'type'} and v.lower() in {'pdf', 'html', 'xml', 'epdf', 'article'}))]
            return self._terms(urlunsplit((parts.scheme, host, path, urlencode(query), '')))
        except ValueError:
            return '[URL_REMOVED]'

    def _terms(self, text: str) -> str:
        for secret in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(secret, '[SECRET_REMOVED]')
        for name in self.usernames:
            if len(name) >= 3:
                text = re.sub(r'(?<![\w.-])' + re.escape(name) + r'(?![\w.-])', '[USER]', text, flags=re.I)
        for term in sorted(self.terms | self.school_hosts, key=len, reverse=True):
            text = re.sub(re.escape(term), '[INSTITUTION]', text, flags=re.I)
        return text

    def text(self, text: str) -> str:
        text = decoded(text)
        # Strip entire header lines, not merely the first word of a Cookie value.
        text = re.sub(r'(?im)\b(?:cookie|set-cookie|authorization|proxy-authorization)\s*[:=][^\n]*', '[SECRET_REMOVED]', text)
        text = _URL.sub(lambda m: self.url(m.group()), text)
        text = _ASSIGNMENT.sub('[SECRET_REMOVED]', text)
        text = text.replace(self.home, '~')
        text = re.sub(r'(?i)(?:[A-Z]:[\\/](?:Users|Documents and Settings)[\\/]|/(?:Users|home)/)[^/\\\s"\x27]+', '~', text)
        text = re.sub(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[EMAIL]', text)
        text = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[SECRET_REMOVED]', text)
        return self._terms(text)

    def clean(self, value, depth: int = 0):
        if depth > 30:
            return '[DEPTH_LIMIT]'
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(str(k)): self.clean(v, depth + 1) for k, v in value.items()
                    if str(k).lower() not in _OMIT and not _SECRET.search(str(k))}
        if isinstance(value, list):
            return [self.clean(v, depth + 1) for v in value]
        return value if value is None or isinstance(value, (bool, int, float)) else None


TAGS = frozenset('html head body title main article section nav header footer aside div span p h1 h2 h3 h4 h5 h6 ul ol li dl dt dd a button form label input select option textarea table thead tbody tr th td details summary br hr strong em b i img'.split())
DROP = frozenset('script style noscript iframe object embed svg math template canvas'.split())
ATTRS = frozenset({'id', 'class', 'role', 'name', 'type', 'title', 'alt', 'aria-label', 'aria-labelledby',
                   'aria-describedby', 'aria-expanded', 'aria-controls', 'data-testid', 'data-test',
                   'href', 'action', 'data-href', 'data-action', 'disabled'})
VOID = frozenset('input img br hr meta link base area col source track wbr embed param'.split())


class StructureParser(HTMLParser):
    def __init__(self, redactor: Redactor):
        super().__init__(convert_charrefs=True)
        self.redactor = redactor
        self.parts: list[str] = []
        self.stack: list[tuple[str, bool]] = []
        self.skip = 0
        self.size = 0
        self.text_left = MAX_TEXT_CHARS
        self.truncated = False

    def emit(self, value: str) -> None:
        size = len(value.encode('utf-8'))
        if self.size + size > MAX_HTML_BYTES - 1024:
            self.truncated = True
            return
        self.parts.append(value)
        self.size += size

    def handle_starttag(self, tag, attrs):
        hidden = tag in DROP or (tag == 'input' and (dict(attrs).get('type') or '').lower() == 'hidden')
        value_field = tag in {'textarea', 'select'}
        parent_skip = self.skip > 0
        if tag not in VOID:
            self.stack.append((tag, hidden or value_field))
            if hidden or value_field:
                self.skip += 1
        if parent_skip or hidden or tag not in TAGS:
            return
        fields = []
        for key, value in attrs:
            if key not in ATTRS or value is None or _SECRET.search(key):
                continue
            if key in {'href', 'action', 'data-href', 'data-action'}:
                key = 'data-' + key if not key.startswith('data-') else key
                value = self.redactor.url(value)
            else:
                value = self.redactor.text(value[:500])
            fields.append(f' {key}="{html.escape(value, quote=True)}"')
        self.emit('<' + tag + ''.join(fields) + '>')
        if value_field:
            self.emit('</' + tag + '>')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        # Malformed input must not prematurely escape a dropped subtree.
        if not self.stack or self.stack[-1][0] != tag:
            return
        was_skip = self.skip
        _, hidden = self.stack.pop()
        if hidden:
            self.skip -= 1
        if not was_skip and tag in TAGS:
            self.emit('</' + tag + '>')

    def handle_data(self, data):
        if self.skip or not data.strip() or self.text_left <= 0:
            return
        value = self.redactor.text(data.strip())[:min(160, self.text_left)]
        self.text_left -= len(value)
        self.emit(html.escape(value))


def sanitize_html(source: str, redactor: Redactor) -> tuple[str, bool]:
    parser = StructureParser(redactor)
    parser.feed(source[:MAX_HTML_BYTES * 4])
    parser.close()
    prefix = '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; form-action \'none\'; base-uri \'none\'">\n'
    return prefix + ''.join(parser.parts), parser.truncated or len(source) > MAX_HTML_BYTES * 4 or parser.text_left <= 0
