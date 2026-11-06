"""Bounded, inert page specimens shared by download diagnostics and issues."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .report_sanitizer import MAX_HTML_BYTES, Redactor, sanitize_html

# Walk live DOM without copying a script, a form value or an entire article.
# The RPC is bounded in time, number of nodes, depth, text and returned size.
_STRUCTURE = r"""(root, limit) => {
  let size = 0, nodes = 0, textLeft = 6000, truncated = false;
  const out = [], drop = new Set(['SCRIPT','STYLE','NOSCRIPT','IFRAME','OBJECT','EMBED','SVG','MATH','TEMPLATE','CANVAS']);
  const attrs = new Set(['id','class','role','name','type','title','alt','aria-label','aria-labelledby','aria-describedby','aria-expanded','aria-controls','data-testid','data-test','href','action','disabled']);
  const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  const push = s => { if (size + s.length <= limit) { out.push(s); size += s.length; } else truncated = true; };
  const walk = (node, depth) => {
    if (++nodes > 6000 || depth > 60 || size >= limit - 1024) { truncated = true; return; }
    if (node.nodeType === 3) {
      const s = node.textContent.trim().slice(0, Math.min(160, textLeft));
      textLeft -= s.length; if (s) push(esc(s)); return;
    }
    if (node.nodeType !== 1 || drop.has(node.tagName) || (node.tagName === 'INPUT' && node.type === 'hidden')) return;
    const tag = node.tagName.toLowerCase();
    push('<' + tag + Array.from(node.attributes).filter(a => attrs.has(a.name)).map(a => ' ' + a.name + '="' + esc(a.value.slice(0,500)) + '"').join('') + '>');
    if (['textarea','select'].includes(tag)) { push('</' + tag + '>'); return; }
    for (const child of node.childNodes) { if (nodes >= 6000 || size >= limit - 1024) { truncated = true; break; } walk(child, depth + 1); }
    if (!['input','img','br','hr','meta','link'].includes(tag)) push('</' + tag + '>');
  };
  walk(root, 0); return {html: out.join(''), truncated: truncated || textLeft <= 0,
    private: !!root.querySelector('input[type=password],input[autocomplete=username],input[autocomplete=current-password]')};
}"""


def capture_structure(page: Any, path: Path, config: dict | None = None) -> dict:
    """Optional evidence failure is recorded, never changes the download result."""
    try:
        from .browser import watchdog
        if watchdog.fired:
            return {'html_omitted': 'browser_stopped'}
        raw = page.locator('html').evaluate(_STRUCTURE, MAX_HTML_BYTES // 2, timeout=3000)
        if not isinstance(raw, dict) or not isinstance(raw.get('html'), str):
            return {'html_omitted': 'capture_unavailable'}
        content, truncated = sanitize_html(raw['html'], Redactor(config))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return {'html': str(path), 'html_truncated': bool(truncated or raw.get('truncated')),
                'screenshot_private': bool(raw.get('private'))}
    except Exception as exc:
        return {'html_omitted': type(exc).__name__}


def masked_screenshot(page: Any, path: Path) -> dict:
    try:
        from .browser import watchdog
        if watchdog.fired:
            return {'screenshot_omitted': 'browser_stopped'}
        path.parent.mkdir(parents=True, exist_ok=True)
        encoding = {"type": "jpeg", "quality": 50} if path.suffix.lower() in {".jpg", ".jpeg"} else {"type": "png"}
        page.screenshot(path=str(path), **encoding, full_page=False, timeout=3000,
                        mask=[page.locator('input, textarea, select, [contenteditable]')])
        return {'screenshot': str(path), 'screenshot_masked': True}
    except Exception as exc:
        return {'screenshot_omitted': type(exc).__name__}
