"""Constants for the Darkbloom integration."""
from __future__ import annotations

DOMAIN = "darkbloom"
CONF_API_KEY = "api_key"
DEFAULT_SCAN_INTERVAL = 300  # seconds; one API call per cycle
STORE_VERSION = 1
STORE_KEY = "darkbloom_cache_{}"

EARNINGS_URL = "https://console.darkbloom.dev/api/me/earnings"
REQUEST_TIMEOUT = 30
