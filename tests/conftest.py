"""Fixtures."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    return


@pytest.fixture(autouse=True)
def mock_frontend():
    """Skip the real frontend (needs the hass_frontend package)."""
    with (
        patch(
            "homeassistant.components.frontend.async_setup",
            AsyncMock(return_value=True),
        ),
        patch("custom_components.essential_ipcam_recorder.add_extra_js_url"),
    ):
        yield
