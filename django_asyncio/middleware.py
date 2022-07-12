from django.contrib.sessions.middleware import SessionMiddleware as DjSessions
from django.contrib.auth import middleware as dj_auth_middleware
from django.conf import settings


class SessionMiddleware(DjSessions):
    def process_request(self, request):
        session_key = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
        context = getattr(request, 'aiohttp_context', None)
        session = None
        if context:
            session = context.get('session', None)
            if session:
                if session_key == session.session_key:
                    request.session = session
                    return
                else:
                    session = None
                    context['session_miss'] = context.get(
                        'session_miss', 0) + 1
        request.session = self.SessionStore(session_key)
        if context and session:
            context['session'] = request.session


def get_user(request):
    session_miss = False
    if not hasattr(request, '_cached_user'):
        context = getattr(request, 'aiohttp_context', {})
        if context:
            user = context.get('user', None)
            if user:
                session_key = request.sesson.session_key
                if session_key == context['session'].session_key:
                    request._cached_user = user
                    return request._cached_user
                else:
                    session_miss = True
        request._cached_user = dj_auth_middleware.auth.get_user(request)
        if context and not session_miss:
            context['user'] = request._cached_user
    return request._cached_user
