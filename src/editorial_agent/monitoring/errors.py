"""Sanitized errors raised by the independent Monitor."""


class MonitorError(RuntimeError):
    """Base class for safe Monitor failures."""


class MonitorModelError(MonitorError):
    """The model failed or returned malformed structured output."""


class MonitorValidationError(MonitorError):
    """The model report does not match the supplied evidence."""

    def __init__(
        self,
        message: str,
        *,
        returned_references: frozenset[str] | None = None,
        allowed_references: frozenset[str] | None = None,
        invalid_references: frozenset[str] | None = None,
        returned_axes: tuple[str, ...] | None = None,
        required_axes: tuple[str, ...] | None = None,
        missing_axes: frozenset[str] | None = None,
        duplicate_axes: frozenset[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.returned_references = returned_references
        self.allowed_references = allowed_references
        self.invalid_references = invalid_references
        self.returned_axes = returned_axes
        self.required_axes = required_axes
        self.missing_axes = missing_axes
        self.duplicate_axes = duplicate_axes


class MonitorPersistenceError(MonitorError):
    """A report could not be safely persisted."""
