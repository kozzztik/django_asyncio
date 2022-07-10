import tempfile
import functools

from aiohttp import web
from asgiref.sync import sync_to_async
from django.core.handlers import asgi as dj_asgi
from django.conf import settings
from django.http import HttpResponse
from django.contrib.staticfiles import handlers as static


def websocket_view(func):
    @functools.wraps(func)
    async def wrapper(request, *args, **kwargs):
        ws = web.WebSocketResponse()
        await ws.prepare(request.aiohttp_request)
        request.aio_websock = ws
        try:
            await func(request, ws, *args, **kwargs)
            # for django middleware
            return HttpResponse(status=101)
        finally:
            if not ws.closed:
                await ws.close()
    return wrapper


class AiohttpHandler(dj_asgi.ASGIHandler, static.StaticFilesHandlerMixin):
    def __init__(self):
        super(AiohttpHandler, self).__init__()
        self.base_url = static.urlparse(self.get_base_url())

    async def _create_request(self, scope, iorequest):
        body_file = tempfile.SpooledTemporaryFile(
            max_size=settings.FILE_UPLOAD_MAX_MEMORY_SIZE, mode='w+b')
        body_file.write(await iorequest.read())
        body_file.seek(0)
        dj_asgi.set_script_prefix(self.get_script_prefix(scope))
        await dj_asgi.sync_to_async(
            dj_asgi.signals.request_started.send, thread_sensitive=True
        )(sender=self.__class__, scope=scope)
        return self.create_request(scope, body_file)

    async def process(self, scope, iorequest):
        # Get the request and check for basic issues.
        request, error_response = await self._create_request(scope, iorequest)
        if request is None:
            return await self.convert_response(error_response)
        # Get connection level context
        request.aio_websock = None
        request.aiohttp_request = iorequest
        iorequest.transport.django_context = context = getattr(
            iorequest.transport, 'django_context', {'requests': 0})
        context['requests'] += 1
        request.aiohttp_context = context
        # Get the response, using the async mode of BaseHandler.
        response = await self.get_response_async(request)
        response._handler_class = self.__class__
        # Increase chunk size on file responses (ASGI servers handles low-level
        # chunking).
        if isinstance(response, dj_asgi.FileResponse):
            response.block_size = self.chunk_size
        if request.aio_websock:
            return request.aio_websock
        return await self.convert_response(response)

    async def convert_response(self, response):
        body = []
        if response.streaming:
            for part in response:
                for chunk, _ in self.chunk_bytes(part):
                    body.append(chunk)
        else:
            body = (chunk for chunk, _ in self.chunk_bytes(response.content))
        result = web.Response(
            status=response.status_code,
            headers=response.items(),
            body=b''.join(body)
        )
        for c in response.cookies:
            result.set_cookie(c)
        if getattr(settings, 'HTTP_KEEP_ALIVE', True):
            result.headers['Connection'] = 'keep-alive'
        await sync_to_async(response.close, thread_sensitive=True)()
        return result

    async def handle_static(self, scope, iorequest):
        # Get the request and check for basic issues.
        request, error_response = await self._create_request(scope, iorequest)
        if request is None:
            return await self.convert_response(error_response)

        response = await static.StaticFilesHandlerMixin.get_response_async(
            self, request)
        return await self.convert_response(response)
