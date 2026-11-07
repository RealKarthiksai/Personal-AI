"""Tests for deterministic rules fact extraction and strict grounding verification."""

from __future__ import annotations

import pytest

from app.memory.extractor import (
    extract_facts_rules,
    verify_grounding,
)


def test_rules_extraction_identity_name():
    facts = extract_facts_rules("Hello Karna, my name is Bruce Wayne.")
    assert len(facts) >= 1
    f = facts[0]
    assert f.profile_key == "name"
    assert f.profile_value == "Bruce Wayne"
    assert "Bruce Wayne" in f.text
    assert f.importance == 5


def test_rules_extraction_location_city():
    facts = extract_facts_rules("I live in Bengaluru, India.")
    assert len(facts) >= 1
    f = [x for x in facts if x.profile_key == "city"][0]
    assert "Bengaluru" in f.profile_value
    assert f.importance == 4


def test_rules_extraction_timezone():
    facts = extract_facts_rules("My timezone is Asia/Kolkata.")
    assert len(facts) >= 1
    f = [x for x in facts if x.profile_key == "timezone"][0]
    assert f.profile_value == "Asia/Kolkata"


def test_rules_extraction_language():
    facts = extract_facts_rules("My preferred language is Hindi.")
    assert len(facts) >= 1
    f = [x for x in facts if x.profile_key == "language"][0]
    assert f.profile_value == "Hindi"


def test_rules_extraction_explicit_remember():
    facts = extract_facts_rules("Please remember that my dog's name is Barnaby.")
    assert len(facts) >= 1
    f = facts[0]
    assert "Barnaby" in f.text
    assert f.importance == 4


def test_rules_extraction_projects():
    facts = extract_facts_rules("I am building an autonomous drone navigation system.")
    assert len(facts) >= 1
    f = [x for x in facts if x.profile_key == "current_project"][0]
    assert "autonomous drone navigation system" in f.profile_value


def test_grounding_verification_numbers_match():
    # Number matches exactly
    source = "I have 3 cats and 2 dogs at home."
    fact = "User owns 3 cats and 2 dogs."
    assert verify_grounding(fact, source, min_overlap=0.6) is True


def test_grounding_verification_numbers_hallucinated():
    # Fact contains number not present in source text
    source = "I have several cats and dogs at home."
    fact = "User owns 5 cats."
    assert verify_grounding(fact, source, min_overlap=0.6) is False

    source2 = "The invoice amount was 150 dollars."
    fact2 = "Invoice amount was 1500 dollars."
    assert verify_grounding(fact2, source2, min_overlap=0.6) is False


def test_grounding_verification_keyword_overlap():
    source = "We are launching a new satellite payload tomorrow morning from Sriharikota."
    fact_valid = "User mentions launching a satellite payload tomorrow from Sriharikota."
    assert verify_grounding(fact_valid, source, min_overlap=0.6) is True

    fact_invented = "User is building a quantum supercomputer with superconducting qubits."
    assert verify_grounding(fact_invented, source, min_overlap=0.6) is False
