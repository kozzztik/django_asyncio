from django.apps import AppConfig

from django_asyncio import runserver


class DjangoAsyncio(AppConfig):
    name = 'django_asyncio'
    label = 'django_asyncio'
    verbose_name = 'django_asyncio'

    def ready(self):
        runserver.patch()
        from django_asyncio import middleware
        from django.contrib.sessions.middleware import SessionMiddleware
        SessionMiddleware.process_request = \
            middleware.SessionMiddleware.process_request
        from django.contrib.auth import middleware as dj_auth_middleware
        dj_auth_middleware.get_user = middleware.get_user
