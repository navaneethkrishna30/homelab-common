"""Shared base for Nav's homelab services."""

from homelab_common import db
from homelab_common.config import CommonSettings, load_config
from homelab_common.service_spec import ServiceSpec, load_service_spec

__all__ = ["CommonSettings", "ServiceSpec", "db", "load_config", "load_service_spec"]
