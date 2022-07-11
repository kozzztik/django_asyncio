import asyncio

from aiohttp import web
from django.contrib.staticfiles import handlers as static_handlers
from django.core.management.commands import runserver as dj_runserver
from django.conf import settings

from django_asyncio.app import Application


class ASGIServer:
    def __init__(self, server_address, handler, ipv6):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.app = Application()
        self.server_address = server_address

    def set_app(self, wsgi_handler):
        if isinstance(wsgi_handler, static_handlers.StaticFilesHandler):
            self.app.handle_static = True

    def serve_forever(self):
        web.run_app(
            self.app,
            host=self.server_address[0],
            port=self.server_address[1],
            print=None,
            keepalive_timeout=getattr(settings, 'HTTP_KEEP_ALIVE', 75.0),
            loop=self.loop
        )


def patch():
    dj_runserver.Command.server_cls = ASGIServer
