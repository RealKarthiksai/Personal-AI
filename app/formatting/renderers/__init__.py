"""Renderers package for platform-specific message formatting."""

from app.formatting.renderers.base import BaseRenderer, split_into_chunks
from app.formatting.renderers.telegram import TelegramRenderer
from app.formatting.renderers.web import WebRenderer
from app.formatting.renderers.whatsapp import WhatsAppRenderer

__all__ = [
    "BaseRenderer",
    "WhatsAppRenderer",
    "TelegramRenderer",
    "WebRenderer",
    "split_into_chunks",
]
