"""Typed failures raised by exchange clients."""


class ExchangeError(Exception):
    """Base class for exchange communication failures."""


class ExchangeTimeoutError(ExchangeError):
    """The exchange did not produce a definitive response in time."""


class ExchangeAuthError(ExchangeError):
    """Authentication failed or the API key is not safe for trading."""


class ExchangeRateLimitError(ExchangeError):
    """The exchange rate limit remained exhausted after retries."""


class ExchangeAPIRejectError(ExchangeError):
    """The exchange definitively rejected a request."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class UnknownOrderStateError(ExchangeError):
    """An order submission may have succeeded, but cannot be confirmed."""

    def __init__(self, client_order_id: str) -> None:
        super().__init__(f"Unknown state for order {client_order_id!r}; do not resubmit blindly")
        self.client_order_id = client_order_id
