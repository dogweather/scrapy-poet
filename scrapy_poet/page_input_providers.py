"""The Injection Middleware needs a standard way to build the Page Inputs dependencies
that the Page Objects uses to get external data (e.g. the HTML). That's why we
have created a repository of ``PageObjectInputProviders``.

The current module implements a ``PageObjectInputProviders`` for
:class:`web_poet.page_inputs.ResponseData`, which is in charge of providing the response
HTML from Scrapy. You could also implement different providers in order to
acquire data from multiple external sources, for example,
Splash or Auto Extract API.
"""
import abc
import json
from typing import Set, Union, Callable, ClassVar, List, Any, Sequence

import attr
from scrapy import Request
from scrapy.http import Response
from scrapy.crawler import Crawler
from scrapy.utils.reqser import request_to_dict
from scrapy.utils.request import request_fingerprint

from scrapy_poet.injection_errors import MalformedProvidedClassesError
from web_poet import ResponseData


class PageObjectInputProvider:
    """
    This is the base class for creating Page Object Input Providers.

    A Page Object Input Provider (POIP) takes responsibility for providing
    instances of some types to Scrapy callbacks. The types a POIP provides must
    be declared in the class attribute ``provided_classes``.

    POIPs are initialized when the spider starts by invoking the ``__init__`` method,
    which receives the crawler instance as argument.

    The ``__call__`` method must be overridden, and it is inside this method
    where the actual instances must be build. The default ``__call__`` signature
    is as follows:

    .. code-block:: python

        def __call__(self, to_provide: Set[Callable]) -> Sequence[Any]:

    Therefore, it receives a list of types to be provided and return a list
    with the instances created (don't get confused by the
    ``Callable`` annotation. Think on it as a synonym of ``Type``).

    Additional dependencies can be declared in the ``__call__`` signature
    that will be automatically injected. Currently, scrapy-poet is able
    to inject instances of the following classes:

    - :class:`~scrapy.http.Request`
    - :class:`~scrapy.http.Response`
    - :class:`~scrapy.crawler.Crawler`
    - :class:`~scrapy.settings.Settings`
    - :class:`~scrapy.statscollectors.StatsCollector`

    Finally, ``__call__`` function can execute asynchronous code. Just
    either prepend the declaration with ``async`` to use futures or annotate it with
    ``@inlineCallbacks`` for deferred execution. Additionally, you
    might want to configure Scrapy ``TWISTED_REACTOR`` to support ``asyncio``
    libraries.

    The available POIPs should be declared in the spider setting using the key
    ``SCRAPY_POET_PROVIDERS``. It must be a dictionary that follows same
    structure than the
    :ref:`Scrapy Middlewares <scrapy:topics-downloader-middleware-ref>`
    configuration dictionaries.

    A simple example of a provider:

    .. code-block:: python

        class BodyHtml(str): pass

        class BodyHtmlProvider(PageObjectInputProvider):
            provided_classes = {BodyHtml}

            def __call__(self, to_provide, response: Response):
                return [BodyHtml(response.css("html body").get())]

    The **provided_classes** class attribute is the ``set`` of classes
    that this provider provides.
    Alternatively, it can be a function with type ``Callable[[Callable], bool]`` that
    returns ``True`` if and only if the given type, which must be callable,
    is provided by this provider.
    """

    provided_classes: ClassVar[Union[Set[Callable], Callable[[Callable], bool]]]
    name: ClassVar[str] = ""  # It must be a unique name. Used by the cache mechanism

    @classmethod
    def is_provided(cls, type_: Callable):
        """
        Return ``True`` if the given type is provided by this provider based
        on the value of the attribute ``provided_classes``
        """
        if isinstance(cls.provided_classes, Set):
            return type_ in cls.provided_classes
        elif callable(cls.provided_classes):
            return cls.provided_classes(type_)
        else:
            raise MalformedProvidedClassesError(
                f"Unexpected type '{type_}' for 'provided_classes' attribute of"
                f"'{cls}.'. Expected either 'set' or 'callable'")

    def __init__(self, crawler: Crawler):
        """Initializes the provider. Invoked only at spider start up."""
        pass

    # Remember that is expected for all children to implement the ``__call__``
    # method. The simplest signature for it is:
    #
    #   def __call__(self, to_provide: Set[Callable]) -> Sequence[Any]:
    #
    # But some adding some other injectable attributes are possible
    # (see the class docstring)
    #
    # The technical reason why this method was not declared abstract is that
    # injection breaks the method overriding rules and mypy then complains.


class CacheDataProviderMixin(abc.ABC):
    """Providers that intend to support the ``SCRAPY_POET_CACHE`` should inherit
    from this mixin class.
    """

    @abc.abstractmethod
    def fingerprint(self, to_provide: Set[Callable], request: Request) -> str:
        """
        Return a fingerprint that identifies this particular request. It will be used to implement
        the cache and record/replay mechanism
        """
        pass

    @abc.abstractmethod
    def serialize(self, result: Sequence[Any]) -> Any:
        """
        Serializes the results of this provider. The data returned will be pickled.
        """
        pass

    @abc.abstractmethod
    def deserialize(self, data: Any) -> Sequence[Any]:
        """
        Deserialize some results of the provider that were previously serialized using the method
        :meth:`serialize`.
        """
        pass

    @property
    def has_cache_support(self):
        return True


class ResponseDataProvider(PageObjectInputProvider, CacheDataProviderMixin):
    """This class provides ``web_poet.page_inputs.ResponseData`` instances."""

    provided_classes = {ResponseData}
    name = "response_data"

    def __call__(self, to_provide: Set[Callable], response: Response):
        """Builds a ``ResponseData`` instance using a Scrapy ``Response``"""
        return [ResponseData(url=response.url, html=response.text)]

    def fingerprint(self, to_provide: Set[Callable], request: Request) -> str:
        request_keys = {"url", "method", "body"}
        request_data = {
            k: str(v)
            for k, v in request_to_dict(request).items()
            if k in request_keys
        }
        fp_data = {
            "SCRAPY_FINGERPRINT": request_fingerprint(request),
            **request_data,
        }
        return json.dumps(fp_data, ensure_ascii=False, sort_keys=True)

    def serialize(self, result: Sequence[Any]) -> Any:
        return [attr.asdict(response_data) for response_data in result]

    def deserialize(self, data: Any) -> Sequence[Any]:
        return [ResponseData(**response_data) for response_data in data]
