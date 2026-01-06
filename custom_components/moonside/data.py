"""Runtime data containers for the Moonside integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .api import MoonsideApiClient, ThemeDefinition
from .coordinator import MoonsideDataUpdateCoordinator


@dataclass(slots=True)
class MoonsideRuntimeData:
    """Stores objects tied to a single config entry."""

    api: MoonsideApiClient
    coordinator: MoonsideDataUpdateCoordinator
    themes: list[ThemeDefinition]
    unsubscribe: Callable[[], None] | None = None
