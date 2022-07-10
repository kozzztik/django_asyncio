from django.contrib.sessions.middleware import SessionMiddleware as DjSessions
from django.contrib.auth import middleware as dj_auth_middleware
from django.conf import settings


class SessionMiddleware(DjSessions):
    def process_request(self, request):
        session_key = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
        context = getattr(request, 'aiohttp_context', None)
        if context:
            session = context.get('session', None)
            if session:
                request.session = session
                return
        request.session = self.SessionStore(session_key)
        if context:
            context['session'] = request.session


def get_user(request):
    if not hasattr(request, '_cached_user'):
        context = getattr(request, 'aiohttp_context', {})
        if context:
            user = context.get('user', None)
            if user:
                request._cached_user = user
                return request._cached_user
        request._cached_user = dj_auth_middleware.auth.get_user(request)
        if context:
            context['user'] = request._cached_user
    return request._cached_user
