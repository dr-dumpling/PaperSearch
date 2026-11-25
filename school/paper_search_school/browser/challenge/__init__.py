"""Publisher verification: detection, local controls, image services and handlers.

local/: native browser controls; interaction owns Cloudflare/Turnstile clicks,
    pointer owns movement/presses, prompt owns other checkboxes and outer submit.
services/: server requests and decoded image answers, with no browser actions.
handlers/: aws_waf, recaptcha_hcaptcha and text_captcha extract puzzles and
    apply the service answers in the same browser.
continuation: bounded dispatch into the handlers.
detection: verification evidence predicates, with no browser or task state.
warmup: visit a site root before its first article.
kinds: which kind of verification a page is (reCAPTCHA v2, hCaptcha's puzzle, ...), for
    the record only.

The engine owns waiting and decides whether the publisher has allowed access.
No response tokens are read or injected.
"""
