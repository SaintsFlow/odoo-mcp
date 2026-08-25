"""Talking to Odoo over XML-RPC.

Odoo exposes two endpoints: /xmlrpc/2/common for the login and /xmlrpc/2/object
for everything else. The standard library speaks that protocol and it blocks, so
every call is handed to a worker thread and the event loop stays free.

Nothing above this module knows about models, domains or field names. It knows
about calls that either return records or raise one of the errors in errors.py.
"""

import asyncio
import os
import time
import xmlrpc.client
from typing import Any

import structlog
from pydantic import BaseModel, SecretStr

from src.errors import OdooApiError, OdooAuthError, OdooError, fault_message, translate_fault
from src.models import link_id

COMMON_ENDPOINT = "/xmlrpc/2/common"
OBJECT_ENDPOINT = "/xmlrpc/2/object"

# Odoo translates the messages it raises, and our tools pass them straight to
# the agent. Pinning the language keeps them English, which is the language of
# this project, and keeps the parsing in errors.py predictable.
DEFAULT_CONTEXT: dict[str, Any] = {"lang": "en_US"}

REQUIRED_ENV = ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_PASSWORD")
COMPANIES_ENV = "ODOO_COMPANY_IDS"


def _companies_from_env() -> list[int] | None:
    """Which companies the answers may come from, empty meaning the user's own."""
    raw = os.getenv(COMPANIES_ENV, "").strip()
    if not raw:
        return None

    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts or not all(part.isdigit() for part in parts):
        raise OdooError(
            f"{COMPANIES_ENV} has to be one company id or several separated by commas, "
            f"like 1 or 1,3. It is {raw!r}."
        )
    return [int(part) for part in parts]


class OdooConfig(BaseModel):
    """Everything needed to reach one Odoo database."""

    url: str
    db: str
    user: str
    # SecretStr so that a stray repr of the config cannot print the password.
    password: SecretStr
    # Which companies the answers come from. Left empty it is the one the user
    # belongs to. Several are allowed, and then every answer names its own.
    company_ids: list[int] | None = None

    @classmethod
    def from_env(cls) -> "OdooConfig":
        """Build the config from the environment, naming what is missing."""
        missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
        if missing:
            raise OdooError(f"Odoo is not configured: set {', '.join(missing)}. See .env.example.")

        return cls(
            url=os.environ["ODOO_URL"],
            db=os.environ["ODOO_DB"],
            user=os.environ["ODOO_USER"],
            password=SecretStr(os.environ["ODOO_PASSWORD"]),
            company_ids=_companies_from_env(),
        )

    def endpoint(self, path: str) -> str:
        """Full URL of one XML-RPC endpoint."""
        return f"{self.url.rstrip('/')}{path}"


class OdooClient:
    """One database, one login, many calls.

    The uid is fetched once and kept. Everything else is stateless, which is
    what makes the client safe to share between concurrent tool calls.
    """

    def __init__(self, config: OdooConfig) -> None:
        self._config = config
        self._session: tuple[int, list[int]] | None = None
        # Without the lock a burst of first calls would all log in at once.
        self._login_lock = asyncio.Lock()

    async def authenticate(self) -> int:
        """Return the uid, logging in on the first call only."""
        uid, _ = await self._open_session()
        return uid

    async def _open_session(self) -> tuple[int, list[int]]:
        """The uid and the companies every call is pinned to, resolved once."""
        cached = self._session
        if cached is not None:
            return cached

        async with self._login_lock:
            # Someone may have logged in while this call waited for the lock.
            cached = self._session
            if cached is not None:
                return cached
            uid = await asyncio.to_thread(self._authenticate_blocking)
            companies = self._config.company_ids
            if companies is None:
                companies = [await asyncio.to_thread(self._company_blocking, uid)]
            self._session = (uid, companies)
            structlog.get_logger().info(
                "odoo_authenticated",
                db=self._config.db,
                user=self._config.user,
                uid=uid,
                company_ids=companies,
            )
            return self._session

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Call any method on any model. The generic door into Odoo."""
        uid, companies = await self._open_session()
        call_kwargs = dict(kwargs or {})
        # The caller's own context wins, it usually knows better than we do.
        call_kwargs["context"] = {
            **DEFAULT_CONTEXT,
            "allowed_company_ids": list(companies),
            **(call_kwargs.get("context") or {}),
        }

        log = structlog.get_logger().bind(model=model, method=method)
        started = time.perf_counter()
        try:
            result = await asyncio.to_thread(
                self._execute_kw_blocking, uid, model, method, args, call_kwargs
            )
        except xmlrpc.client.Fault as fault:
            # The whole traceback belongs here and nowhere near the agent.
            log.debug(
                "odoo_fault_received",
                fault_code=fault.faultCode,
                fault_string=str(fault.faultString),
            )
            error = translate_fault(fault)
            log.warning(
                "odoo_call_failed",
                duration_ms=_elapsed_ms(started),
                error=type(error).__name__,
                message=error.message,
            )
            raise error from fault
        except (xmlrpc.client.Error, OSError) as exc:
            log.warning(
                "odoo_call_failed", duration_ms=_elapsed_ms(started), error=type(exc).__name__
            )
            raise OdooApiError(f"The call to Odoo did not go through: {exc}") from exc

        log.info(
            "odoo_call_finished", duration_ms=_elapsed_ms(started), records=_record_count(result)
        )
        return result

    async def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str],
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Search and read in one round trip. The workhorse of every read tool."""
        kwargs: dict[str, Any] = {"fields": list(fields), "offset": offset}
        if limit is not None:
            kwargs["limit"] = limit

        result = await self.execute_kw(model, "search_read", [list(domain)], kwargs)
        if not isinstance(result, list) or not all(isinstance(row, dict) for row in result):
            raise OdooApiError(f"Odoo answered {model}.search_read with something unexpected.")
        return result

    def _authenticate_blocking(self) -> int:
        """The login itself. Runs in a worker thread."""
        proxy = self._proxy(COMMON_ENDPOINT)
        try:
            uid = proxy.authenticate(
                self._config.db,
                self._config.user,
                self._config.password.get_secret_value(),
                {},
            )
        except xmlrpc.client.Fault as fault:
            structlog.get_logger().debug(
                "odoo_fault_received",
                endpoint=COMMON_ENDPOINT,
                fault_code=fault.faultCode,
                fault_string=str(fault.faultString),
            )
            raise OdooAuthError(f"Odoo refused the login: {fault_message(fault)}") from fault
        except (xmlrpc.client.Error, OSError) as exc:
            raise OdooApiError(f"Odoo at {self._config.url} did not answer: {exc}") from exc

        # A wrong password is not a fault here, Odoo simply answers False.
        if isinstance(uid, bool) or not isinstance(uid, int) or uid <= 0:
            raise OdooAuthError(
                f"Odoo rejected the credentials of user '{self._config.user}' "
                f"on database '{self._config.db}'."
            )
        return uid

    def _company_blocking(self, uid: int) -> int:
        """Which company the user belongs to. Runs in a worker thread.

        This one goes straight to the proxy instead of through execute_kw,
        because execute_kw needs the answer to build its own context.
        """
        proxy = self._proxy(OBJECT_ENDPOINT)
        try:
            rows = proxy.execute_kw(
                self._config.db,
                uid,
                self._config.password.get_secret_value(),
                "res.users",
                "read",
                [[uid]],
                {"fields": ["company_id"], "context": DEFAULT_CONTEXT},
            )
        except xmlrpc.client.Fault as fault:
            raise translate_fault(fault) from fault
        except (xmlrpc.client.Error, OSError) as exc:
            raise OdooApiError(f"Odoo at {self._config.url} did not answer: {exc}") from exc

        company = None
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            company = link_id(rows[0].get("company_id"))
        if company is None:
            raise OdooApiError(
                f"Odoo did not say which company user '{self._config.user}' belongs to. "
                f"Set {COMPANIES_ENV} to pick one."
            )
        return company

    def _execute_kw_blocking(
        self,
        uid: int,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any],
    ) -> Any:
        """The call itself. Runs in a worker thread, raises Fault as Odoo sent it."""
        proxy = self._proxy(OBJECT_ENDPOINT)
        return proxy.execute_kw(
            self._config.db,
            uid,
            self._config.password.get_secret_value(),
            model,
            method,
            args,
            kwargs,
        )

    def _proxy(self, path: str) -> xmlrpc.client.ServerProxy:
        """A fresh proxy for every call.

        ServerProxy keeps an HTTP connection inside and is not thread safe,
        while asyncio.to_thread spreads calls over a pool. Sharing one would
        buy a race on that connection; a new one costs a local TCP handshake.
        """
        return xmlrpc.client.ServerProxy(self._config.endpoint(path), allow_none=True)


def _elapsed_ms(started: float) -> float:
    """Milliseconds since the given perf counter reading."""
    return round((time.perf_counter() - started) * 1000, 1)


def _record_count(result: Any) -> int | None:
    """How many records came back, when the answer is a list of them."""
    if isinstance(result, list):
        return len(result)
    return None
