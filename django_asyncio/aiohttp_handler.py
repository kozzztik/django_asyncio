import asyncio
import tempfile
import functools
from concurrent.futures import ThreadPoolExecutor

from aiohttp import web
from django.core.handlers import asgi as dj_asgi
from django.conf import settings
from django.http import HttpResponse
from django.contrib.staticfiles import handlers as static
from django.urls import get_resolver, set_urlconf
from django.core.handlers.exception import convert_exception_to_response
from django.utils.module_loading import import_string
from django.core.handlers import base
from django.urls.exceptions import Resolver404
from django.utils.log import log_response


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
        self.threadpool = ThreadPoolExecutor(
            max_workers=getattr(settings, 'HTTP_THREADS', 10))
        set_urlconf(settings.ROOT_URLCONF)
        self.loop = asyncio.get_event_loop()

    def load_middleware(self, is_async=False):
        (self._middleware_chain, self._view_middleware,
            self._template_response_middleware, self._exception_middleware) = \
                self._load_middleware(False)
        (self._async_middleware_chain, self._async_view_middleware,
            self._async_template_response_middleware,
            self._async_exception_middleware) = \
                self._load_middleware(True)

    def _load_middleware(self, is_async=False):
        """
        Populate middleware lists from settings.MIDDLEWARE.

        Must be called after the environment is fixed (see __call__ in subclasses).
        """
        view_middleware = []
        template_response_middleware = []
        exception_middleware = []
        handler = self._get_response_async if is_async else self._get_response
        handler = convert_exception_to_response(handler)
        for middleware_path in reversed(settings.MIDDLEWARE):
            middleware = import_string(middleware_path)
            middleware_can_sync = getattr(middleware, 'sync_capable', True)
            middleware_can_async = getattr(middleware, 'async_capable', False)
            if not middleware_can_sync and not middleware_can_async:
                raise RuntimeError(
                    'Middleware %s must have at least one of '
                    'sync_capable/async_capable set to True.' % middleware_path
                )
            if not middleware_can_sync and not is_async:
                return None, None, None, None
            if not middleware_can_async and is_async:
                return None, None, None, None
            try:
                mw_instance = middleware(handler)
            except base.MiddlewareNotUsed as exc:
                if settings.DEBUG:
                    if str(exc):
                        base.logger.debug(
                            'MiddlewareNotUsed(%r): %s', middleware_path, exc)
                    else:
                        base.logger.debug(
                            'MiddlewareNotUsed: %r', middleware_path)
                continue

            if mw_instance is None:
                raise base.ImproperlyConfigured(
                    'Middleware factory %s returned None.' % middleware_path
                )

            if hasattr(mw_instance, 'process_view'):
                view_middleware.insert(0, mw_instance.process_view)
            if hasattr(mw_instance, 'process_template_response'):
                template_response_middleware.append(
                    mw_instance.process_template_response)
            if hasattr(mw_instance, 'process_exception'):
                # The exception-handling stack is still always synchronous for
                # now, so adapt that way.
                exception_middleware.append(mw_instance.process_exception)

            handler = convert_exception_to_response(mw_instance)

        # We only assign to this when initialization is complete as it is used
        # as a flag for initialization being complete.
        return (
            handler, view_middleware, template_response_middleware,
            exception_middleware)

    async def _create_request(self, scope, iorequest):
        body_file = tempfile.SpooledTemporaryFile(
            max_size=settings.FILE_UPLOAD_MAX_MEMORY_SIZE, mode='w+b')
        body_file.write(await iorequest.read())
        body_file.seek(0)
        dj_asgi.set_script_prefix(self.get_script_prefix(scope))
        dj_asgi.signals.request_started.send(
            sender=self.__class__, scope=scope)
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

    def resolve_request(self, request):
        match = getattr(request, 'resolver_match', None)
        if match:
            return match
        return super(AiohttpHandler, self).resolve_request(request)

    async def _get_response_async(self, request):
        """
        Resolve and call the view, then apply view, exception, and
        template_response middleware. This method is everything that happens
        inside the request/response middleware.
        """
        response = None
        callback, callback_args, callback_kwargs = self.resolve_request(request)
        # Apply view middleware.
        for middleware_method in self._async_view_middleware:
            if asyncio.iscoroutinefunction(middleware_method):
                response = await middleware_method(
                    request, callback, callback_args, callback_kwargs)
            else:
                # middlware said it is async capable bt provide sync method, so
                # just call it as is
                response = middleware_method(
                    request, callback, callback_args, callback_kwargs)
            if response:
                break

        if response is None:
            wrapped_callback = self.make_view_atomic(callback)
            # If it is a synchronous view, run it in a subthread
            try:
                response = await wrapped_callback(
                    request, *callback_args, **callback_kwargs)
            except Exception as e:
                response = await self.async_process_exception_by_middleware(
                    e, request)
                if response is None:
                    raise

        # Complain if the view returned None or an uncalled coroutine.
        self.check_response(response, callback)

        # If the response supports deferred rendering, apply template
        # response middleware and then render the response
        if hasattr(response, 'render') and callable(response.render):
            for middleware_method in self._async_template_response_middleware:
                response = await middleware_method(request, response)
                # Complain if the template response middleware returned None or
                # an uncalled coroutine.
                self.check_response(
                    response,
                    middleware_method,
                    name='%s.process_template_response' % (
                        middleware_method.__self__.__class__.__name__,
                    )
                )
            if not asyncio.iscoroutinefunction(response.render):
                raise RuntimeError('Cannot use sync render in async flow')
            try:
                response = await response.render()
            except Exception as e:
                response = await self.async_process_exception_by_middleware(
                    e, request)
                if response is None:
                    raise

        # Make sure the response is not a coroutine
        if asyncio.iscoroutine(response):
            raise RuntimeError('Response is still a coroutine.')
        return response

    async def get_response_async(self, request):
        """
        Asynchronous version of get_response.

        Funneling everything, including WSGI, into a single async
        get_response() is too slow. Avoid the context switch by using
        a separate async response path.
        """
        async_flow = False
        try:
            match = self.resolve_request(request)
            async_flow = asyncio.iscoroutinefunction(match[0])
        except Resolver404:
            pass
        if not async_flow:
            return await self.loop.run_in_executor(
                self.threadpool, self.get_response, request)
        response = await self._async_middleware_chain(request)
        response._resource_closers.append(request.close)
        if response.status_code >= 400:
            log_response(
                '%s: %s', response.reason_phrase, request.path,
                response=response,
                request=request,
            )
        return response

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
        for name in response.cookies:
            c = response.cookies[name]
            data = {name: value for name, value in c.items() if value}
            data['max_age'] = data.pop('max-age', None)
            result.set_cookie(name, c.value, **data)
        if getattr(settings, 'HTTP_KEEP_ALIVE', True):
            result.headers['Connection'] = 'keep-alive'
        response.close()
        return result

    async def async_process_exception_by_middleware(self, exception, request):
        """
        Pass the exception to the exception middleware. If no middleware
        return a response for this exception, return None.
        """
        for middleware_method in self._async_exception_middleware:
            response = await middleware_method(request, exception)
            if response:
                return response
        return None

    async def handle_static(self, scope, iorequest):
        # Get the request and check for basic issues.
        request, error_response = await self._create_request(scope, iorequest)
        if request is None:
            return await self.convert_response(error_response)

        response = await static.StaticFilesHandlerMixin.get_response_async(
            self, request)
        return await self.convert_response(response)
