"""Constants for the Moonside integration."""

from __future__ import annotations

from datetime import timedelta
from logging import Logger, getLogger

from homeassistant.const import Platform

LOGGER: Logger = getLogger(__package__)

DOMAIN = "moonside"
PLATFORMS = [Platform.LIGHT, Platform.BUTTON]

CONF_THEME_SWITCHES = "theme_switches"
CONF_ENABLE_POLLING = "enable_polling"
CONF_POLLING_INTERVAL = "polling_interval"

DEFAULT_NAME = "Moonside"
DEFAULT_ENABLE_POLLING = False
DEFAULT_POLLING_INTERVAL = 60
FIREBASE_API_KEY = "AIzaSyCC-qQZqcZhxqsbO7GB0nXZShab9gV06Bk"

STREAM_RECONNECT_DELAY = timedelta(seconds=5)
POLLING_MIN_INTERVAL = 5
