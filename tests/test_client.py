"""The client against a real Odoo from docker compose.

Skipped as a whole when the stand is down, see the odoo_url fixture.
"""

import socket
import threading
import time
from typing import Any

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from src.client import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_RECORDS,
    OdooClient,
    OdooConfig,
    page_size,
)
from src.errors import (
    OdooAccessError,
    OdooApiError,
    OdooAuthError,
    OdooError,
    OdooValidationError,
)


def _a_socket_that_never_answers() -> str:
    """A listener that accepts and then says nothing, and its URL."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def sit_there() -> None:
        try:
            connection, _ = listener.accept()
            time.sleep(5)
            connection.close()
        except OSError:
            pass
        finally:
            listener.close()

    threading.Thread(target=sit_there, daemon=True).start()
    return f"http://127.0.0.1:{port}"


async def test_authenticate_returns_a_uid(odoo_client: OdooClient) -> None:
    """Without a uid nothing else can be called."""
    uid = await odoo_client.authenticate()
    assert isinstance(uid, int)
    assert uid > 0


async def test_a_wrong_password_is_refused(odoo_config: OdooConfig) -> None:
    """Odoo answers a bad login with False, which has to become a real error.

    The password must not travel back in the message: the agent sees it and so
    does the log of whoever runs the server.
    """
    config = odoo_config.model_copy(update={"password": SecretStr("definitely-not-it")})
    with pytest.raises(OdooAuthError) as caught:
        await OdooClient(config).authenticate()
    assert "definitely-not-it" not in caught.value.message
    assert odoo_config.user in caught.value.message


async def test_an_unknown_database_is_refused(odoo_config: OdooConfig) -> None:
    """A typo in ODOO_DB should name the problem, not dump a traceback."""
    config = odoo_config.model_copy(update={"db": "no_such_db"})
    with pytest.raises(OdooAuthError) as caught:
        await OdooClient(config).authenticate()
    assert "Traceback" not in caught.value.message


async def test_the_uid_comes_from_cache(
    odoo_client: OdooClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Logging in once per client, not once per call."""
    calls = 0
    login = odoo_client._authenticate_blocking

    def counted() -> int:
        nonlocal calls
        calls += 1
        return login()

    monkeypatch.setattr(odoo_client, "_authenticate_blocking", counted)
    first = await odoo_client.authenticate()
    second = await odoo_client.authenticate()
    await odoo_client.search_read("res.partner", [], ["name"], limit=1)

    assert first == second
    assert calls == 1


async def test_search_read_finds_demo_partners(odoo_client: OdooClient) -> None:
    """The basic working call, against the demo data."""
    partners = await odoo_client.search_read("res.partner", [], ["name"], limit=5)
    assert partners.rows
    assert len(partners.rows) <= 5
    assert all("name" in partner for partner in partners.rows)


async def test_search_read_paginates(odoo_client: OdooClient) -> None:
    """Offset has to move the window."""
    first_page = await odoo_client.search_read("res.partner", [], ["name"], limit=2)
    second_page = await odoo_client.search_read("res.partner", [], ["name"], limit=2, offset=2)
    assert [row["id"] for row in first_page.rows] != [row["id"] for row in second_page.rows]


def test_the_cap_holds_whatever_is_asked_for() -> None:
    """One record over the cap is asked for on purpose: it is how we learn there is more."""
    assert page_size(5) == 6
    assert page_size(MAX_RECORDS) == MAX_RECORDS + 1
    assert page_size(10_000) == MAX_RECORDS + 1
    assert page_size(None) == MAX_RECORDS + 1


async def test_a_full_page_says_it_is_not_everything(odoo_client: OdooClient) -> None:
    """The demo carries dozens of partners, so five of them cannot be all of them."""
    partners = await odoo_client.search_read("res.partner", [], ["name"], limit=5)
    assert len(partners.rows) == 5
    assert partners.truncated is True


async def test_a_short_page_says_nothing_was_cut(odoo_client: OdooClient) -> None:
    partners = await odoo_client.search_read("res.partner", [], ["name"], limit=10_000)
    assert partners.rows
    assert len(partners.rows) <= MAX_RECORDS
    assert partners.truncated is False


async def test_a_hanging_call_is_cut_off_and_says_so(odoo_config: OdooConfig) -> None:
    """A socket that accepts the connection and then keeps quiet, like a stuck Odoo.

    Without a deadline of our own this call would sit there for as long as the
    operating system allows, and the agent would simply never hear back.
    """
    url = _a_socket_that_never_answers()
    config = odoo_config.model_copy(update={"url": url, "timeout": 0.5})

    started = time.perf_counter()
    with pytest.raises(OdooApiError) as caught:
        await OdooClient(config).authenticate()
    waited = time.perf_counter() - started

    assert waited < 5, "the call was not cut off by our own deadline"
    message = caught.value.message
    assert "0.5" in message
    assert "timed out" not in message, f"raw socket wording reached the agent: {message}"
    assert "Traceback" not in message


def test_the_timeout_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real Odoo behind a slow report needs a longer rope than the default."""
    for name, value in (
        ("ODOO_URL", "http://odoo.invalid"),
        ("ODOO_DB", "odoo"),
        ("ODOO_USER", "admin"),
        ("ODOO_PASSWORD", "secret"),
    ):
        monkeypatch.setenv(name, value)

    monkeypatch.delenv("ODOO_TIMEOUT", raising=False)
    assert OdooConfig.from_env().timeout == DEFAULT_TIMEOUT_SECONDS

    monkeypatch.setenv("ODOO_TIMEOUT", "5")
    assert OdooConfig.from_env().timeout == 5.0

    monkeypatch.setenv("ODOO_TIMEOUT", "half a minute")
    with pytest.raises(OdooError):
        OdooConfig.from_env()

    # Zero would mean "give up before asking", which is a typo and not a wish.
    for nonsense in ("0", "-5"):
        monkeypatch.setenv("ODOO_TIMEOUT", nonsense)
        with pytest.raises(OdooError):
            OdooConfig.from_env()


async def test_an_unknown_model_gives_a_short_api_error(odoo_client: OdooClient) -> None:
    """The agent never picks models, so this is our bug and it must read as one."""
    with pytest.raises(OdooApiError) as caught:
        await odoo_client.execute_kw("no.such.model", "search_read", [[]])
    message = caught.value.message
    assert "Traceback" not in message
    assert "\n" not in message
    assert len(message) < 200


async def test_an_unknown_field_gives_a_short_api_error(odoo_client: OdooClient) -> None:
    """Odoo answers this one with a 28 line traceback."""
    with pytest.raises(OdooApiError) as caught:
        await odoo_client.search_read("res.partner", [], ["no_such_field"], limit=1)
    message = caught.value.message
    assert "Traceback" not in message
    assert "no_such_field" in message
    assert len(message) < 200


async def test_the_traceback_goes_to_the_log_and_not_to_the_agent(
    odoo_client: OdooClient,
) -> None:
    """Whoever debugs the server needs the whole thing, the agent does not."""
    with capture_logs() as events, pytest.raises(OdooApiError) as caught:
        await odoo_client.execute_kw("res.partner", "no_such_method", [[]])

    faults = [event for event in events if event["event"] == "odoo_fault_received"]
    assert faults, "the raw fault was never logged"
    assert faults[0]["log_level"] == "debug"
    assert "Traceback" in faults[0]["fault_string"]
    assert "Traceback" not in caught.value.message


async def test_a_call_without_rights_gives_an_access_error(demo_client: OdooClient) -> None:
    """Login fine, rights missing. A real instance will hit this constantly."""
    with pytest.raises(OdooAccessError):
        await demo_client.search_read("ir.config_parameter", [], ["key"], limit=1)


async def test_a_missing_required_field_gives_a_validation_error(
    odoo_client: OdooClient,
) -> None:
    """Odoo refuses the write, so nothing is created by this test."""
    with pytest.raises(OdooValidationError) as caught:
        await odoo_client.execute_kw("sale.order", "create", [{"note": "no partner here"}])
    assert "partner_id" in caught.value.message


async def test_a_wrong_password_inside_a_call_is_an_auth_error(
    odoo_config: OdooConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cached uid with a password that stopped working. Odoo answers code 3."""
    uid = await OdooClient(odoo_config).authenticate()
    stale = OdooClient(odoo_config.model_copy(update={"password": SecretStr("stale-secret")}))
    monkeypatch.setattr(stale, "_authenticate_blocking", lambda: uid)

    with pytest.raises(OdooAuthError):
        await stale.search_read("res.partner", [], ["name"], limit=1)


async def test_the_call_log_carries_model_method_and_timing(odoo_client: OdooClient) -> None:
    """Without these three a slow call cannot be traced back to its caller.

    Asked through execute_kw on purpose: that line of the log counts what came
    over the wire, and search_read asks for one record more than it keeps.
    """
    with capture_logs() as events:
        await odoo_client.execute_kw(
            "res.partner", "search_read", [[]], {"fields": ["name"], "limit": 3}
        )

    finished = [event for event in events if event["event"] == "odoo_call_finished"]
    assert len(finished) == 1
    entry: dict[str, Any] = finished[0]
    assert entry["model"] == "res.partner"
    assert entry["method"] == "search_read"
    assert entry["records"] == 3
    assert entry["duration_ms"] >= 0


async def test_hitting_the_cap_leaves_a_line_in_the_log(odoo_client: OdooClient) -> None:
    """An agent that keeps hitting the cap is asking the wrong question."""
    with capture_logs() as events:
        await odoo_client.search_read("res.partner", [], ["name"], limit=3)

    capped = [event for event in events if event["event"] == "records_capped"]
    assert len(capped) == 1
    assert capped[0]["model"] == "res.partner"
    assert capped[0]["kept"] == 3


def test_one_company_or_several_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A demo showing two companies at once is set up with one variable."""
    for name, value in (
        ("ODOO_URL", "http://odoo.invalid"),
        ("ODOO_DB", "odoo"),
        ("ODOO_USER", "admin"),
        ("ODOO_PASSWORD", "secret"),
    ):
        monkeypatch.setenv(name, value)

    monkeypatch.delenv("ODOO_COMPANY_IDS", raising=False)
    assert OdooConfig.from_env().company_ids is None

    monkeypatch.setenv("ODOO_COMPANY_IDS", "1")
    assert OdooConfig.from_env().company_ids == [1]

    monkeypatch.setenv("ODOO_COMPANY_IDS", " 1 , 3 ")
    assert OdooConfig.from_env().company_ids == [1, 3]


def test_a_company_that_is_not_a_number_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A company name where an id belongs would silently widen every answer."""
    for name, value in (
        ("ODOO_URL", "http://odoo.invalid"),
        ("ODOO_DB", "odoo"),
        ("ODOO_USER", "admin"),
        ("ODOO_PASSWORD", "secret"),
        ("ODOO_COMPANY_IDS", "AT Company"),
    ):
        monkeypatch.setenv(name, value)

    with pytest.raises(OdooError):
        OdooConfig.from_env()


async def test_the_password_never_reaches_the_log(odoo_config: OdooConfig) -> None:
    """A structured log is still a log, and it gets shipped somewhere."""
    secret = "keep-this-out-of-the-log"
    client = OdooClient(odoo_config.model_copy(update={"password": SecretStr(secret)}))

    with capture_logs() as events, pytest.raises(OdooAuthError):
        await client.authenticate()

    assert secret not in str(events)
