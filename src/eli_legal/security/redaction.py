def minimise_for_audit(text: str, max_chars: int = 256) -> str:
    """Avoid copying full privileged/personal content into audit events."""
    compact = " ".join((text or "").split())
    return compact[:max_chars]
