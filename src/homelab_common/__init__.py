"""Shared base for Nav's homelab services."""

from homelab_common import db
from homelab_common.config import CommonSettings, load_config

__all__ = ["CommonSettings", "db", "load_config"]
