from django.apps import AppConfig

from django_asyncio import runserver


class DjangoAsyncio(AppConfig):
    name = 'django_asyncio'
    label = 'django_asyncio'
    verbose_name = 'django_asyncio'

    def ready(self):
        runserver.patch()
