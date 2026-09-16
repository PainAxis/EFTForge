"""Exercise disconnects while real spawned solver processes are blocked."""

import asyncio
import contextlib
import threading
import time

import pytest
from starlette.concurrency import run_in_threadpool

from optimizer import process_runner
from optimizer.cancellation import SolveCancelled, SolveCancellationMiddleware, SolveStreamingResponse
from optimizer.solver import OptimizeParams


def _blocked_worker(connection, *args):
    time.sleep(60)


def _successful_worker(connection, *args):
    connection.send({"type": "result", "data": {"status": "optimal"}})
    connection.close()


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
@pytest.mark.parametrize("kind", ["explore", "optimize", "gunsmith"])
def test_disconnect_terminates_blocked_child(monkeypatch, kind, spec_version):
    started = threading.Event()
    children = []
    released = []
    original_start = process_runner._start_process

    def start(*args):
        process, connection = original_start(_blocked_worker)
        children.append(process)
        started.set()
        return process, connection

    monkeypatch.setattr(process_runner, "_start_process", start)

    def stream():
        try:
            with contextlib.closing(process_runner.stream_explore("unused", OptimizeParams(), "price", 10)) as events:
                for event in events:
                    yield str(event)
        except SolveCancelled:
            return

    def cleanup():
        assert not children or not children[0].is_alive()
        released.append(True)

    async def endpoint(scope, receive, send):
        # Consume a split request body, as FastAPI does before entering a route.
        assert (await receive())["more_body"]
        assert not (await receive())["more_body"]
        if kind == "explore":
            await SolveStreamingResponse(stream(), cleanup=cleanup)(scope, receive, send)
        else:
            try:
                if kind == "optimize":
                    await run_in_threadpool(process_runner.run_job, "optimize", "unused", OptimizeParams())
                else:
                    await run_in_threadpool(process_runner.run_gunsmith, "unused")
                pytest.fail("Disconnected solve returned a result")
            except SolveCancelled:
                pass
            finally:
                cleanup()

    async def run():
        messages = [
            {"type": "http.request", "body": b"{", "more_body": True},
            {"type": "http.request", "body": b"}", "more_body": False},
        ]

        async def receive():
            if messages:
                return messages.pop(0)
            while not started.is_set():
                await asyncio.sleep(0.01)
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        path = "/build/gunsmith-solve" if kind == "gunsmith" else f"/build/{kind}"
        await asyncio.wait_for(
            SolveCancellationMiddleware(endpoint)(
                {"type": "http", "method": "POST", "path": path, "asgi": {"spec_version": spec_version}}, receive, send
            ),
            timeout=8,
        )

    try:
        asyncio.run(run())
        assert len(children) == 1
        assert children[0].exitcode is not None
        assert released == [True]
    finally:
        for process in children:
            if process.is_alive():
                process_runner._stop_process(process)


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
def test_stream_send_failure_closes_iterator_and_releases_slot(spec_version):
    events = []

    def stream():
        try:
            yield "progress"
            pytest.fail("Must not resume the solve after a failed send")
        finally:
            events.append("closed")

    async def endpoint(scope, receive, send):
        await receive()
        await SolveStreamingResponse(stream(), cleanup=lambda: events.append("released"))(scope, receive, send)

    async def run():
        body_sent = False

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": b"{}"}
            await asyncio.Event().wait()

        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("connection closed")

        with pytest.raises(Exception):
            await SolveCancellationMiddleware(endpoint)(
                {"type": "http", "method": "POST", "path": "/build/explore", "asgi": {"spec_version": spec_version}},
                receive,
                send,
            )

    asyncio.run(run())
    assert events == ["closed", "released"]


def test_disconnect_before_body_finishes_does_not_start_child(monkeypatch):
    def start(*args):
        pytest.fail("Must not spawn a child for a disconnected request")

    monkeypatch.setattr(process_runner.multiprocessing, "get_context", start)

    async def endpoint(scope, receive, send):
        assert (await receive())["type"] == "http.disconnect"
        with pytest.raises(SolveCancelled):
            await run_in_threadpool(process_runner.run_job, "optimize", "unused", OptimizeParams())

    async def run():
        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        await SolveCancellationMiddleware(endpoint)(
            {"type": "http", "method": "POST", "path": "/build/optimize"}, receive, send
        )

    asyncio.run(run())


def test_cancelling_one_request_does_not_cancel_another(monkeypatch):
    started = threading.Event()
    children = []
    results = {}
    original_start = process_runner._start_process

    def start(target, kind, payload):
        worker = _blocked_worker if payload["weapon_id"] == "cancel" else _successful_worker
        process, connection = original_start(worker)
        children.append(process)
        if payload["weapon_id"] == "cancel":
            started.set()
        return process, connection

    monkeypatch.setattr(process_runner, "_start_process", start)

    async def endpoint(scope, receive, send):
        await receive()
        name = scope["test_request"]
        try:
            results[name] = await run_in_threadpool(process_runner.run_job, "optimize", name, OptimizeParams())
        except SolveCancelled:
            results[name] = "cancelled"

    app = SolveCancellationMiddleware(endpoint)

    async def request(name):
        body_sent = False

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": b"{}"}
            if name == "keep":
                await asyncio.Event().wait()
            while not started.is_set():
                await asyncio.sleep(0.01)
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        await app({"type": "http", "method": "POST", "path": "/build/optimize", "test_request": name}, receive, send)

    async def run():
        await asyncio.wait_for(asyncio.gather(request("cancel"), request("keep")), timeout=15)

    try:
        asyncio.run(run())
        assert results == {"cancel": "cancelled", "keep": {"status": "optimal"}}
        assert len(children) == 2
        assert all(not process.is_alive() for process in children)
    finally:
        for process in children:
            if process.is_alive():
                process_runner._stop_process(process)
