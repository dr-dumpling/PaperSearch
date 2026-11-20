"""A fake clock for the test's own thread only.

``time.time`` and ``time.sleep`` belong to every thread: patched for one test, they are
patched for any thread an earlier test left running as well. The browser watchdog sleeps
0.25 s in a loop; when it woke during such a test, its sleep moved the test's fake clock
on and the test failed now and then (Windows, 2026-11-18).
"""
import threading
import time
from typing import Any, Callable


def this_thread_only(fake_time: Callable[[], float],
                     fake_sleep: Callable[[float], Any]) -> tuple[Callable[[], float], Callable[[float], None]]:
    """``(time, sleep)`` to patch in: the fakes on the thread that calls this, the real
    functions on every other thread."""
    own, real_time, real_sleep = threading.get_ident(), time.time, time.sleep

    def time_() -> float:
        return fake_time() if threading.get_ident() == own else real_time()

    def sleep(seconds: float) -> None:
        if threading.get_ident() == own:
            fake_sleep(seconds)
        else:
            real_sleep(seconds)

    return time_, sleep
