import sys


def request_approval(action: str) -> bool:
    """Fail closed unless an interactive user explicitly approves in a TTY."""
    if not sys.stdin.isatty():
        return False
    try:
        from rich.prompt import Prompt

        reply = Prompt.ask(
            f"[bold yellow]Approval required for '{action}'. Proceed? (yes/no)[/]",
            default="no",
        )
        return reply.strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        return False
