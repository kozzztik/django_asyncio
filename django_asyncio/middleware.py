import asyncio
from django.contrib.sessions.middleware import SessionMiddleware as DjSessions
from django.contrib.auth import middleware as dj_auth_middleware
from django.conf import settings


class SessionMiddleware(DjSessions):
    def process_request(self, request):
        session_key = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
        transport = getattr(request, 'asgi', None)
        if transport:
            session = getattr(transport, 'session', None)
            if session:
                print('use cached session!')
                request.session = session
                return
        request.session = self.SessionStore(session_key)
        if transport:
            transport.session = request.session


def AuthenticationMiddleware(get_response):
    if asyncio.iscoroutinefunction(get_response):
        return AsyncAuthenticationMiddleware(get_response)
    return SyncAuthenticationMiddleware(get_response)


class SyncAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _set_user(transport, request):
        if transport:
            user = getattr(transport, 'user', None)
            if user:
                print('use cached user!')
                request._cached_user = user
                return
        request.user = dj_auth_middleware.SimpleLazyObject(
            lambda: dj_auth_middleware.get_user(request))

    def __call__(self, request):
        transport = getattr(request, 'asgi', None)
        self._set_user(transport, request)
        response = self.get_response(request)
        if transport:
            transport.user = getattr(request, '_cached_user', None)
        return response


class AsyncAuthenticationMiddleware(SyncAuthenticationMiddleware):
    async def __call__(self, request):
        transport = getattr(request, 'asgi', None)
        self._set_user(transport, request)
        response = await self.get_response(request)
        if transport:
            transport.user = getattr(request, '_cached_user', None)
        return response
