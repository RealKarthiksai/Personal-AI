"""Pydantic schemas for extracted entities and events."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class Hackathon(BaseModel):
    name: str = Field(..., description="Name of the hackathon or competition")
    organizer: Optional[str] = Field(default=None, description="Hosting institution or company")
    deadline: Optional[str] = Field(default=None, description="Registration deadline or end date")
    event_date: Optional[str] = Field(default=None, description="Dates when the event is held")
    location: Optional[str] = Field(default=None, description="Venue or Online/Virtual")
    eligibility: Optional[str] = Field(default=None, description="Who can participate (e.g. students, open to all)")
    prize: Optional[str] = Field(default=None, description="Prize pool or rewards")
    registration_url: Optional[str] = Field(default=None, description="Direct registration or application URL")
    source_url: str = Field(..., description="Webpage where this information was extracted")
    confidence: str = Field(default="HIGH", description="Confidence level (HIGH, MEDIUM, LOW, CONFLICTED)")


class GeneralEvent(BaseModel):
    title: str = Field(..., description="Event title")
    organizer: Optional[str] = None
    date: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None
    source_url: str
