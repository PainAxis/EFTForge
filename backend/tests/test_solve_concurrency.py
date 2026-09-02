"""Tests for the per-IP / global concurrency guard on the solve endpoints
(main.py's _solve_slot). Added after a review found /build/optimize had no
protection against a spammed re-optimize button (or a script hitting the
endpoint directly) piling up overlapping 30s MILP solves on one worker.

The per-IP part is a lock file rather than an in-memory set, because prod
runs one Gunicorn worker *process* per CPU core and an in-memory set would
only catch a repeat request that happened to land on the same worker as the
first one. These tests drive the guard directly with threads rather than
through real solves or HTTP - no DB or network needed - including a
many-threads race on the raw file-lock functions, since the OS-level
O_CREAT|O_EXCL atomicity that protects against a thread race is the same
guarantee that protects against a cross-process race.

Skipped under the same conditions as the other optimizer tests: CI never
syncs tarkov.db and never sets IP_HASH_SECRET/ADMIN_API_KEY, and importing
main.py (which imports database/config) would crash collection before
pytest gets to the skip marker if those are missing.

Run with:  cd backend && python -m pytest tests/test_solve_concurrency.py
"""

import os
import threading
import time

import pytest

_HAS_DB = os.path.exists(os.path.join(os.path.dirname(__file__), "..", "tarkov.db"))

pytestmark = pytest.mark.skipif(
    not _HAS_DB,
    reason="requires a synced tarkov.db - run sync_tarkov_dev.py first",
)

if _HAS_DB:
    from fastapi import HTTPException

    import main


def test_same_ip_blocks_second_concurrent_solve():
    entered = threading.Event()
    release = threading.Event()

    def first():
        with main._solve_slot("1.2.3.4"):
            entered.set()
            release.wait(timeout=5)

    t = threading.Thread(target=first)
    t.start()
    assert entered.wait(timeout=5)

    with pytest.raises(HTTPException) as exc:
        with main._solve_slot("1.2.3.4"):
            pass
    assert exc.value.status_code == 429

    release.set()
    t.join(timeout=5)

    # Slot is freed once the first solve's `with` block exits.
    with main._solve_slot("1.2.3.4"):
        pass


def test_different_ips_do_not_block_each_other():
    with main._solve_slot("1.1.1.1"):
        with main._solve_slot("2.2.2.2"):
            pass  # no exception


def test_global_cap_rejects_excess_concurrent_solves():
    n = main._MAX_CONCURRENT_SOLVES
    barrier = threading.Barrier(n + 1, timeout=5)
    release = threading.Event()

    def hold(ip):
        with main._solve_slot(ip):
            barrier.wait()
            release.wait(timeout=5)

    threads = [threading.Thread(target=hold, args=(f"10.0.0.{i}",)) for i in range(n)]
    for t in threads:
        t.start()
    barrier.wait()  # all n workers are now holding a slot on distinct IPs

    with pytest.raises(HTTPException) as exc:
        with main._solve_slot("10.0.0.999"):
            pass
    assert exc.value.status_code == 429

    release.set()
    for t in threads:
        t.join(timeout=5)


def test_ip_lock_file_is_exclusive_under_a_thread_race():
    # Many threads racing os.open(..., O_EXCL) on the same path is the same
    # OS-level guarantee that makes the lock safe across separate worker
    # processes too - only the atomic create can determine a single winner.
    ip = "8.8.8.8"
    main._release_ip_solve_lock(ip)  # in case a previous failed run left it behind
    n = 20
    results = []
    lock = threading.Lock()
    barrier = threading.Barrier(n, timeout=5)

    def attempt():
        barrier.wait()
        won = main._acquire_ip_solve_lock(ip)
        with lock:
            results.append(won)

    threads = [threading.Thread(target=attempt) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert results.count(True) == 1
    assert results.count(False) == n - 1
    main._release_ip_solve_lock(ip)


def test_ip_lock_self_heals_after_going_stale():
    # A worker that crashes mid-solve never calls _release_ip_solve_lock, so
    # the lock file is left behind - it must expire on its own instead of
    # permanently blocking that IP.
    ip = "8.8.4.4"
    assert main._acquire_ip_solve_lock(ip)
    path = main._ip_solve_lock_path(ip)
    stale_time = time.time() - main._SOLVE_LOCK_STALE_SECONDS - 1
    os.utime(path, (stale_time, stale_time))

    assert main._acquire_ip_solve_lock(ip)  # stale lock cleared and reacquired
    main._release_ip_solve_lock(ip)
    assert not os.path.exists(path)


def test_rate_limit_blocks_rapid_repeat_requests_from_same_ip():
    # This is what actually stops an autoclicker spamming a build that's
    # already cached: cache hits never reach _solve_slot (there's no solve to
    # serialize), so without this a repeat-params spam wouldn't be throttled
    # at all despite still costing a DB session + query per request.
    ip = "203.0.113.5"
    main._solve_request_last.pop(ip, None)
    main._check_solve_rate_limit(ip)  # first request always allowed

    with pytest.raises(HTTPException) as exc:
        main._check_solve_rate_limit(ip)
    assert exc.value.status_code == 429
    assert exc.value.detail["reason_key"] == "optimizer.reason.tooManyRequests"


def test_rate_limit_does_not_block_different_ips():
    main._solve_request_last.pop("203.0.113.6", None)
    main._solve_request_last.pop("203.0.113.7", None)
    main._check_solve_rate_limit("203.0.113.6")
    main._check_solve_rate_limit("203.0.113.7")  # different IP, not throttled


def test_rate_limit_allows_request_after_cooldown_elapses():
    ip = "203.0.113.8"
    main._solve_request_last.pop(ip, None)
    main._check_solve_rate_limit(ip)
    time.sleep(main._SOLVE_REQUEST_COOLDOWN + 0.05)
    main._check_solve_rate_limit(ip)  # no exception - cooldown has passed
