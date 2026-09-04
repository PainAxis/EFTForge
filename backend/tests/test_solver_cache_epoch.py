"""Tests for cross-process solver-cache invalidation generations."""

import os

os.environ.setdefault("IP_HASH_SECRET", "test-ip-hash-secret")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

import solver_cache_epoch
from solver_cache_epoch import SolverCacheEpochTracker


def test_two_workers_observe_the_same_published_generation(tmp_path, monkeypatch):
    epoch_file = tmp_path / "solver_cache_epoch"
    monkeypatch.setattr(solver_cache_epoch, "CACHE_EPOCH_FILE", str(epoch_file))
    monkeypatch.setattr(solver_cache_epoch, "RUNTIME_DIR", str(tmp_path))

    worker_a = SolverCacheEpochTracker(solver_cache_epoch.read_solver_cache_epoch)
    worker_b = SolverCacheEpochTracker(solver_cache_epoch.read_solver_cache_epoch)
    assert worker_a.value == worker_b.value == ""

    published = solver_cache_epoch.bump_solver_cache_epoch()

    assert worker_a.refresh() == (published, True)
    assert worker_b.refresh() == (published, True)
    assert worker_a.refresh() == (published, False)


def test_each_publish_changes_the_generation(tmp_path, monkeypatch):
    epoch_file = tmp_path / "solver_cache_epoch"
    monkeypatch.setattr(solver_cache_epoch, "CACHE_EPOCH_FILE", str(epoch_file))
    monkeypatch.setattr(solver_cache_epoch, "RUNTIME_DIR", str(tmp_path))

    first = solver_cache_epoch.bump_solver_cache_epoch()
    second = solver_cache_epoch.bump_solver_cache_epoch()

    assert first != second
    assert solver_cache_epoch.read_solver_cache_epoch() == second
