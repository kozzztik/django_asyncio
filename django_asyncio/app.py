import asyncio
import logging

from aiohttp import web
import django
from django_asyncio import aiohttp_handler
from django.conf import settings

logger = logging.getLogger('django.server')


class Application(web.Application):
    def __init__(self, *args, **kwargs):
        super(Application, self).__init__(*args, **kwargs)
        self.handler = aiohttp_handler.AiohttpHandler()
        self.handle_static = False

    @staticmethod
    def create_scope(request):
        if request.headers.get('Upgrade') == 'websocket':
            connection_type = 'websocket'
        else:
            connection_type = 'http'
        return {
            'type': connection_type,
            'root_path': '',
            'path': request.path,
            'raw_path': request.raw_path,
            'method': request.method,
            'query_string': request.query_string,
            'client': request._transport_peername,
            'server': ('host', 0),
            'headers': [(n.lower(), v) for n, v in request.raw_headers],
        }

    async def _handle(self, request):
        status_code = 500
        try:
            scope = self.create_scope(request)
            if self.handle_static and self.handler._should_handle(
                    request.path):
                response = await self.handler.handle_static(scope, request)
            else:
                response = await self.handler.process(scope, request)
            status_code = response.status
            return response
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(e)
            return web.Response(status=500)
        finally:
            if status_code >= 500:
                level = logger.error
            elif status_code >= 400:
                level = logger.warning
            else:
                level = logger.info
            level('%s %s %s', request.method, request.path, status_code)


def run_app():
    django.setup(set_prefix=False)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = Application()
    if settings.DEBUG:
        app.handle_static = True
    web.run_app(
        app,
        host=getattr(settings, 'HTTP_HOST', '0.0.0.0'),
        port=getattr(settings, 'HTTP_PORT', 8000),
        print=None,
        keepalive_timeout=getattr(settings, 'HTTP_KEEP_ALIVE', 75.0),
        loop=loop
    )