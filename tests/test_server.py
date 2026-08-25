"""Wave 0 smoke tests: the server builds and carries no tools yet."""

from src.server import SERVER_NAME, build_server, configure_logging


async def test_server_starts_with_no_tools() -> None:
    """Tools land in waves 2 and 3, so the list has to be empty for now."""
    server = build_server()
    assert await server.list_tools() == []


def test_server_name_is_stable() -> None:
    """Clients pick the server by this name, so it should not drift."""
    assert build_server().name == SERVER_NAME


def test_server_reports_a_version() -> None:
    """An empty version in the handshake tells the client nothing."""
    assert build_server().version not in (None, "", "0.0.0")


def test_logging_accepts_an_unknown_level() -> None:
    """A typo in LOG_LEVEL must not take the server down on start."""
    configure_logging("not-a-level")
