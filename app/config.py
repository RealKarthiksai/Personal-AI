"""Thin wrapper re-exporting the single source-of-truth settings.

This file exists solely so that every other module can continue to
do `from app.config import config` without any changes.  The actual
configuration lives in ``config.settings`` (pydantic ``BaseSettings``)
and is never duplicated here.
"""

from config.settings import settings as _base_settings

config = _base_settings  # noqa: F811  (assigned after definition)
