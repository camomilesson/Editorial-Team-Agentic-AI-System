"""Sanitized application errors for local editorial services."""


class EditorialServiceError(RuntimeError):
    """Base error safe to show at an application boundary."""


class EntityNotFoundError(EditorialServiceError):
    """A requested structured entity does not exist."""


class DuplicateEntityError(EditorialServiceError):
    """A unique structured entity already exists."""


class AuthorizationError(EditorialServiceError):
    """The current user is not permitted to perform an operation."""


class InvalidAccessGrantError(EditorialServiceError):
    """A document access grant is invalid or unauthorized."""


class SequenceConflictError(EditorialServiceError):
    """An append-only run sequence is already occupied."""


class PersistedDataError(EditorialServiceError):
    """Persisted structured data cannot be safely decoded."""


class PrivateMemoryError(EditorialServiceError):
    """Private memory cannot be safely read or written."""


class UnsupportedMemorySchemaError(PrivateMemoryError):
    """A private-memory file uses an unsupported schema version."""


class TrustedRuleError(EditorialServiceError):
    """A trusted rule document cannot be loaded safely."""
