"""Application failures independent of HTTP response construction."""


class ApplicationError(Exception):
    """Base for expected application failures."""


class ResourceNotFoundError(ApplicationError):
    """No resource is visible to the current identity."""


class DuplicateEmailError(ApplicationError):
    """The normalized email is already registered."""


class AuthenticationError(ApplicationError):
    """Credentials or a token cannot establish an identity."""


class ServiceUnavailableError(ApplicationError):
    """A required service is temporarily unavailable."""
