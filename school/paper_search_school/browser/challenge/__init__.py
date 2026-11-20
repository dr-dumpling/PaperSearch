"""Verification handling: avoid it, recognise it, press its widget, hand over the rest.

detection: verification evidence predicates, with no browser or task state.
interaction: one bounded press on an observed Turnstile widget, and its event record.
pointer: the pointer path and the hold before that press.
prompt: the other providers' own confirmation controls, one press each.
warmup: the site root visit before its first article, so the session starts on
    the site rather than on a deep article URL.

The engine owns waiting and decides whether verification ended; nothing here
answers a puzzle or reads a response token.
"""
from __future__ import annotations
