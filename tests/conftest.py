"""Fixtures for the tests that talk to a real Odoo.

Wave 1 is the network layer, and a mocked XML-RPC would only prove the mock
works. The Odoo from docker compose is local and carries demo data, so the tests
use it for real. When it is not running they skip and say how to start it.
"""

import os
import urllib.request

import pytest
from pydantic import SecretStr

from src.client import OdooClient, OdooConfig

# From the host the stand answers on localhost. Inside compose the service name
# is odoo, which is why the URL can be overridden.
DEFAULT_URL = "http://localhost:8069"
DEFAULT_DB = "odoo"
DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "admin"

# The demo database ships with this second user. It has no access to system
# models, which is exactly what the access error test needs.
DEMO_USER = "demo"
DEMO_PASSWORD = "demo"


def _odoo_answers(url: str) -> bool:
    """Ask the same health endpoint the compose healthcheck uses."""
    try:
        with urllib.request.urlopen(f"{url}/web/health", timeout=5) as response:
            return bool(response.status == 200)
    except OSError:
        return False


@pytest.fixture(scope="session")
def odoo_url() -> str:
    """URL of a running Odoo, or a skip with the command that starts one."""
    url = os.getenv("ODOO_URL", DEFAULT_URL).rstrip("/")
    if _odoo_answers(url):
        return url

    trouble = f"no Odoo at {url}, start the stand with: make up"
    # CI starts the stand on purpose, so a skip there would mean these tests
    # silently stopped covering anything. ODOO_REQUIRED turns that into noise.
    if os.getenv("ODOO_REQUIRED"):
        pytest.fail(f"ODOO_REQUIRED is set and {trouble}", pytrace=False)
    pytest.skip(trouble)


@pytest.fixture(scope="session")
def odoo_config(odoo_url: str) -> OdooConfig:
    """Admin credentials of the demo database."""
    return OdooConfig(
        url=odoo_url,
        db=os.getenv("ODOO_DB", DEFAULT_DB),
        user=os.getenv("ODOO_USER", DEFAULT_USER),
        password=SecretStr(os.getenv("ODOO_PASSWORD", DEFAULT_PASSWORD)),
    )


@pytest.fixture
def odoo_client(odoo_config: OdooConfig) -> OdooClient:
    """A fresh client per test, so the uid cache starts empty every time."""
    return OdooClient(odoo_config)


@pytest.fixture
def demo_client(odoo_config: OdooConfig) -> OdooClient:
    """A client logged in as the unprivileged demo user."""
    return OdooClient(
        odoo_config.model_copy(update={"user": DEMO_USER, "password": SecretStr(DEMO_PASSWORD)})
    )
