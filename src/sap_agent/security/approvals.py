"""Human approval gate for any future write-risk operation."""


def request_approval(action: str) -> bool:
    """Fail closed. No write action is approved automatically."""
    del action
    return False
