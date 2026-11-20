"""Browser support for paper-search-school.

backend: browser selection, launch and context lifecycle (chrome, ego, attach).
profiles: persistent session state and profile ownership.
challenge/: everything about a verification check — the site root visit that
    keeps a session from starting at a deep URL, the detection predicates, the
    bounded press on the widget, the pointer path before it, and the other
    providers' confirmation controls, with the widget's own event record.
watchdog: browser-call cancellation and generic operation budgets.
engine/login/cookies/preview: browser operations and application integration.
"""
