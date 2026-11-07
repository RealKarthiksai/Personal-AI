"""Tests for Telegram user authorization and sender allowlist."""

from __future__ import annotations

import pytest

from app.security.authorization import is_sender_authorized, is_telegram_user_authorized


def test_is_telegram_user_authorized() -> None:
    import app.config as cfg_module

    orig_raw = cfg_module.config.telegram_allowed_user_ids
    orig_parsed = cfg_module.config.allowed_telegram_user_ids

    cfg_module.config.telegram_allowed_user_ids = "123456789,987654321"
    cfg_module.config.allowed_telegram_user_ids = [123456789, 987654321]
    try:
        assert is_telegram_user_authorized(123456789) is True
        assert is_telegram_user_authorized(987654321) is True
        assert is_telegram_user_authorized(555555555) is False
    finally:
        cfg_module.config.telegram_allowed_user_ids = orig_raw
        cfg_module.config.allowed_telegram_user_ids = orig_parsed


def test_is_sender_authorized_allowlist() -> None:
    import app.config as cfg_module

    orig_raw = cfg_module.config.telegram_allowed_user_ids
    orig_parsed = cfg_module.config.allowed_telegram_user_ids

    cfg_module.config.telegram_allowed_user_ids = "123456789,987654321"
    cfg_module.config.allowed_telegram_user_ids = [123456789, 987654321]
    try:
        assert is_sender_authorized("123456789") is True
        assert is_sender_authorized("987654321") is True
        assert is_sender_authorized("555555555") is False
        assert is_sender_authorized("") is False
    finally:
        cfg_module.config.telegram_allowed_user_ids = orig_raw
        cfg_module.config.allowed_telegram_user_ids = orig_parsed


def test_is_sender_authorized_empty_allowlist() -> None:
    import app.config as cfg_module

    orig_raw = cfg_module.config.telegram_allowed_user_ids
    orig_parsed = cfg_module.config.allowed_telegram_user_ids

    cfg_module.config.telegram_allowed_user_ids = ""
    cfg_module.config.allowed_telegram_user_ids = []
    try:
        assert is_sender_authorized("123456789") is False
        assert is_telegram_user_authorized(123456789) is False
    finally:
        cfg_module.config.telegram_allowed_user_ids = orig_raw
        cfg_module.config.allowed_telegram_user_ids = orig_parsed