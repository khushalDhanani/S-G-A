"""Domain exceptions."""


class AgentError(Exception):
    """Base agent error."""


class PolicyDenied(AgentError):
    """A tool request violates configured policy."""
