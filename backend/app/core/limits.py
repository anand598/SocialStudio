"""Per-process upload protection; production also needs limits at its ingress."""
import time
from collections import defaultdict, deque
from fastapi import HTTPException
from starlette.responses import JSONResponse
from app.core.config import get_settings


class UploadLimitsMiddleware:
    def __init__(self, app):
        self.app = app
        self.requests = defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or not scope["path"].startswith("/api/v1/generations"):
            return await self.app(scope, receive, send)
        settings = get_settings()
        now = time.monotonic()
        client = scope.get("client") or ("unknown", 0)
        key = client[0]
        # Expire old keys so arbitrary source addresses cannot grow memory indefinitely.
        for expired in [ip for ip, times in self.requests.items() if not times or times[-1] < now - 60]:
            del self.requests[expired]
        times = self.requests[key]
        while times and times[0] < now - 60:
            times.popleft()
        if len(times) >= settings.requests_per_minute or len(self.requests) > 10000:
            return await JSONResponse({"detail": "Too many generation requests. Please wait a minute and try again."}, 429,
                                      headers={"Retry-After": "60"})(scope, receive, send)
        times.append(now)
        # Per-type limits are enforced while streaming; this is the outer bound for any upload
        # (the largest product file plus an optional music track).
        largest = max(settings.max_upload_size_mb, settings.max_video_upload_size_mb)
        limit = (largest + settings.max_music_upload_size_mb) * 1024 * 1024 + 64 * 1024
        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid request length."}, 400)(scope, receive, send)
        if declared > limit:
            return await JSONResponse({"detail": "The upload exceeds the request size limit."}, 413)(scope, receive, send)
        size = 0
        exceeded = False
        async def limited_receive():
            nonlocal size, exceeded
            message = await receive()
            size += len(message.get("body", b""))
            if size > limit:
                exceeded = True
                raise HTTPException(413, "The upload exceeds the request size limit.")
            return message
        async def limited_send(message):
            # Multipart parsers may map a receive exception to 400; keep the actual limit error.
            if exceeded:
                if message["type"] == "http.response.start":
                    await JSONResponse({"detail": "The upload exceeds the request size limit."}, 413)(scope, receive, send)
                return
            await send(message)
        await self.app(scope, limited_receive, limited_send)
