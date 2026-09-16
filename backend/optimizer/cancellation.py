"""Propagate HTTP disconnects to native solver workers without blocking the event loop."""

import threading
from contextvars import ContextVar

import anyio
from starlette.exceptions import HTTPException
from starlette.responses import StreamingResponse

_current_cancel_event: ContextVar[threading.Event | None] = ContextVar("solve_cancel_event", default=None)
SOLVE_PATHS = {"/build/explore", "/build/optimize", "/build/gunsmith-solve"}


class SolveCancelled(HTTPException):
    def __init__(self):
        super().__init__(status_code=499, detail="Solve cancelled")


def check_cancelled():
    event = _current_cancel_event.get()
    if event is not None and event.is_set():
        raise SolveCancelled()


class SolveCancellationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] not in SOLVE_PATHS:
            await self.app(scope, receive, send)
            return

        cancelled = threading.Event()
        body_complete = anyio.Event()
        disconnected = anyio.Event()
        token = _current_cancel_event.set(cancelled)

        async def receive_body():
            # Let FastAPI consume the body before handing receive to the monitor.
            # Give streaming responses the same disconnect without racing for it.
            if body_complete.is_set():
                await disconnected.wait()
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.disconnect":
                cancelled.set()
                disconnected.set()
                body_complete.set()
            elif message["type"] == "http.request" and not message.get("more_body", False):
                body_complete.set()
            return message

        async def monitor():
            await body_complete.wait()
            while not disconnected.is_set():
                message = await receive()
                if message["type"] == "http.disconnect":
                    cancelled.set()
                    disconnected.set()

        async def send_response(message):
            try:
                await send(message)
            except OSError:
                cancelled.set()
                raise

        try:
            async with anyio.create_task_group() as group:
                group.start_soon(monitor)
                try:
                    await self.app(scope, receive_body, send_response)
                finally:
                    cancelled.set()
                    group.cancel_scope.cancel()
        finally:
            _current_cancel_event.reset(token)


class SolveStreamingResponse(StreamingResponse):
    def __init__(self, content, *, cleanup, **kwargs):
        super().__init__(content, **kwargs)
        self.solve_iterator = content
        self.cleanup = cleanup

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            event = _current_cancel_event.get()
            if event is not None:
                event.set()
            # Wait for worker termination before releasing its slot, including
            # send failures and disconnects before the first iterator advance.
            with anyio.CancelScope(shield=True):
                try:
                    await anyio.to_thread.run_sync(self.solve_iterator.close)
                finally:
                    self.cleanup()
