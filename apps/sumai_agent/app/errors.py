class AppCheckInvalidError(Exception):
    """Raised when a request does not provide a valid App Check attestation."""


class InvalidImageError(Exception):
    """Raised when uploaded bytes cannot be accepted as a supported image."""


class ImageTooLargeError(Exception):
    """Raised when an image exceeds a configured byte or pixel limit."""


class ServiceLimitedError(Exception):
    """Raised when a transient service limit prevents safe request handling."""


class GeminiUnavailableError(Exception):
    """Raised when real Gemini analysis is required but unavailable."""
