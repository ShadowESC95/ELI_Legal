class EliLegalError(Exception):
    """Base domain error."""


class PolicyDenied(EliLegalError):
    pass


class MatterAccessDenied(EliLegalError):
    pass


class VerificationGateFailed(EliLegalError):
    pass


class AuditIntegrityError(EliLegalError):
    pass


class MissingAuditKey(AuditIntegrityError):
    pass
