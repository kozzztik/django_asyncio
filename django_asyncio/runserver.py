import asyncio
import logging

from aiohttp import web
from django.contrib.staticfiles import handlers as static_handlers
from django.core.management.commands import runserver as dj_runserver
from django.conf import settings
from django_asyncio import aiohttp_handler

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


class ASGIServer:
    def __init__(self, server_address, handler, ipv6):
        self.app = Application()
        self.server_address = server_address

    def set_app(self, wsgi_handler):
        if isinstance(wsgi_handler, static_handlers.StaticFilesHandler):
            self.app.handle_static = True

    def serve_forever(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        web.run_app(
            self.app,
            host=self.server_address[0],
            port=self.server_address[1],
            print=None,
            keepalive_timeout=getattr(settings, 'HTTP_KEEP_ALIVE', 75.0),
        )


def patch():
    dj_runserver.Command.server_cls = ASGIServer
