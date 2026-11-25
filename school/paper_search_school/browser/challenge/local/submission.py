"""Find action controls within one verification form or local container."""

CANDIDATES = r'''(form, scope) => {
 const shown = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
 const label=el=>{
   const ids=(el.getAttribute('aria-labelledby')||'').split(/\s+/).filter(Boolean);
   const labelled=ids.map(id=>document.getElementById(id)?.textContent||'').join(' ').trim();
   return (labelled || el.getAttribute('aria-label') ||
     (el.tagName==='INPUT' ? el.getAttribute('value') || el.getAttribute('alt') : el.textContent) || '')
     .normalize('NFKC').trim().replace(/\s+/g,' ').replace(/[\s.!！。:：>→»]+$/g,'');
 };
 const forward=/^(?:(?:submit|verify|validate|check|confirm)(?: (?:the )?(?:code|captcha|answer))?|continue|proceed|next|提交|验证|驗證|确认|確認|继续|繼續|下一步|提交验证|提交驗證|送信|検証|認証|続行|확인|검증|제출|계속|vérifier|valider|confirmer|continuer|envoyer|suivant)$/i;
 const other=/^(?:refresh|reload|reset|cancel|back|new (?:code|captcha|challenge)|try again|刷新|换一张|換一張|重置|取消|返回)$/i;
 const candidates=[...document.querySelectorAll('button,input[type=submit],input[type=image],input[type=button],[role=button],[onclick],a[href],[tabindex]')]
   .filter(el=>shown(el) && (form
     ? (el.form ? el.form===form : scope.contains(el) && el.closest('form')===form)
     : scope.contains(el) && !el.form && !el.closest('form')))
   .filter(el=>{
     if((el.tagName==='INPUT' && !['button','submit','image'].includes(el.type)) ||
        ['TEXTAREA','SELECT','OPTION'].includes(el.tagName) || el.isContentEditable)return false;
     const name=label(el);
     if(el.type==='reset' || other.test(name))return false;
     // Browser-resolved type includes buttons whose type attribute is omitted.
     const native=['BUTTON','INPUT'].includes(el.tagName) && el.form===form &&
       !!form && ['submit','image'].includes(el.type);
     const link=el.tagName==='A' && /^(?:#?|javascript:\s*(?:void\(0\);?|;))$/i.test((el.getAttribute('href')||'').trim());
     const clickable=['BUTTON','INPUT'].includes(el.tagName) || el.getAttribute('role')==='button' ||
       el.hasAttribute('onclick') || link || (el.tagName!=='A' && el.tabIndex>=0 && el.getAttribute('contenteditable')!=='true');
     return native || (clickable && forward.test(name));
   });
 const submits=candidates.filter(el=>!candidates.some(child=>child!==el && el.contains(child)));
 return submits;
}'''
