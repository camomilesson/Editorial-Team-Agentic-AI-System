"""Sanitized errors raised by the independent Monitor."""


class MonitorError(RuntimeError):
    """Base class for safe Monitor failures."""


class MonitorModelError(MonitorError):
    """The model failed or returned malformed structured output."""


class MonitorValidationError(MonitorError):
    """The model report does not match the supplied evidence."""


class MonitorPersistenceError(MonitorError):
    """A report could not be safely persisted."""
