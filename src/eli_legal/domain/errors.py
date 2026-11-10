class EliLegalError(Exception):
    """Base domain error."""


class PolicyDenied(EliLegalError):
    pass


class MatterAccessDenied(EliLegalError):
    pass


class AuthenticationFailed(EliLegalError):
    pass


class StepUpRequired(AuthenticationFailed):
    """Signed in, but this decision needs the passphrase again."""


class AccountLocked(AuthenticationFailed):
    """Too many failed attempts. The account is refused until the lock expires or is lifted."""


class SecondFactorRequired(AuthenticationFailed):
    """The passphrase was right; the code from the person's authenticator is still needed."""


class VerificationGateFailed(EliLegalError):
    pass


class AuditIntegrityError(EliLegalError):
    pass


class MissingAuditKey(AuditIntegrityError):
    pass


class NetworkDenied(EliLegalError):
    """Outbound network use that the approved-source policy does not permit."""


class NotFound(EliLegalError):
    pass


class InvalidState(EliLegalError):
    """An operation was attempted in a lifecycle state that does not allow it."""


class IngestionError(EliLegalError):
    pass


class UnsupportedDocument(IngestionError):
    pass


class InferenceUnavailable(EliLegalError):
    pass


class ConnectorError(EliLegalError):
    pass


class HoldRaised(EliLegalError):
    """Raised by a workflow step to stop itself and everything that depends on it."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)
        self.reason_code = reason_code
        self.detail = detail


class EntitlementDenied(EliLegalError):
    """The hosting ELI licence does not entitle this edition."""


class InvalidInput(EliLegalError, ValueError):
    """The request is missing something a governed action requires, such as a reason."""


class RunStopped(EliLegalError):
    """A person stopped the run while a step was working; the step ends where it is."""
