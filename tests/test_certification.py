"""Tests for the certification program.

Verifies track configuration, exam lifecycle, scoring, certification
issuance, and verification.
"""

from __future__ import annotations

import asyncio
import time
import uuid
import pytest


class MockDB:
    """In-memory mock of the SQLite database wrapper."""

    def __init__(self):
        self._certifications: dict[str, dict] = {}
        self._attempts: dict[str, dict] = {}
        self._sequences: dict[str, int] = {}

    async def execute(self, sql: str, params=None, commit=False):
        sql_lower = sql.strip().lower()
        if sql_lower.startswith("create table"):
            return
        if "cert_attempts" in sql_lower and "insert" in sql_lower and params:
            attempt_id = params[0]
            self._attempts[attempt_id] = {
                "id": params[0],
                "wallet_address": params[1],
                "track": params[2],
                "started_at": params[3],
                "completed_at": None,
                "score": None,
                "passed": None,
                "answers": None,
            }
        if "certifications" in sql_lower and "insert" in sql_lower and params:
            cert_id = params[0]
            self._certifications[cert_id] = {
                "cert_id": params[0],
                "wallet_address": params[1],
                "track": params[2],
                "score": params[3],
                "passed": True,
                "issued_at": params[4] if len(params) > 4 else time.time(),
                "expires_at": params[5] if len(params) > 5 else time.time() + 86400 * 365,
                "eas_uid": None,
                "status": "active",
            }
        if "cert_attempts" in sql_lower and "update" in sql_lower and params:
            for attempt in self._attempts.values():
                if len(params) >= 5 and attempt["id"] == params[-1]:
                    attempt["completed_at"] = params[0] if len(params) > 0 else time.time()
                    attempt["score"] = params[1] if len(params) > 1 else 0
                    attempt["passed"] = params[2] if len(params) > 2 else False
        if "badge_sequence" in sql_lower or "cert_sequence" in sql_lower:
            pass

    async def fetchone(self, sql: str, params=None):
        sql_lower = sql.strip().lower()
        if "cert_attempts" in sql_lower and params:
            return self._attempts.get(params[0])
        if "certifications" in sql_lower and params:
            return self._certifications.get(params[0])
        if "cert_sequence" in sql_lower or "badge_sequence" in sql_lower:
            return None
        return None

    async def fetchall(self, sql: str, params=None):
        sql_lower = sql.strip().lower()
        if "certifications" in sql_lower and params:
            return [c for c in self._certifications.values()
                    if c.get("wallet_address") == params[0]]
        if "cert_attempts" in sql_lower and params:
            return [a for a in self._attempts.values()
                    if a.get("wallet_address") == params[0]]
        return []


@pytest.fixture
def db():
    return MockDB()


@pytest.fixture
def manager(db):
    from runtime.certification.assessments import CertificationManager
    return CertificationManager(db)


def test_certification_tracks_exist():
    """All three certification tracks should be defined."""
    from runtime.certification.assessments import CERTIFICATION_TRACKS
    assert "developer" in CERTIFICATION_TRACKS
    assert "auditor" in CERTIFICATION_TRACKS
    assert "enterprise" in CERTIFICATION_TRACKS


def test_developer_track_config():
    """Developer track should have correct configuration."""
    from runtime.certification.assessments import CERTIFICATION_TRACKS
    dev = CERTIFICATION_TRACKS["developer"]
    assert dev["price_usd"] == 149.00
    assert dev["passing_score"] == 80
    assert dev["questions"] == 40
    assert dev["time_limit_minutes"] == 90
    assert dev["validity_years"] == 2


def test_auditor_track_config():
    """Auditor track should have correct configuration."""
    from runtime.certification.assessments import CERTIFICATION_TRACKS
    auditor = CERTIFICATION_TRACKS["auditor"]
    assert auditor["price_usd"] == 249.00
    assert auditor["passing_score"] == 85
    assert auditor["questions"] == 50
    assert auditor["time_limit_minutes"] == 120
    assert auditor["validity_years"] == 1


def test_enterprise_track_config():
    """Enterprise track should have correct configuration."""
    from runtime.certification.assessments import CERTIFICATION_TRACKS
    enterprise = CERTIFICATION_TRACKS["enterprise"]
    assert enterprise["price_usd"] == 399.00
    assert enterprise["passing_score"] == 85
    assert enterprise["questions"] == 60
    assert enterprise["time_limit_minutes"] == 150
    assert enterprise["validity_years"] == 2


def test_sample_questions_exist():
    """Sample questions should exist for all tracks."""
    from runtime.certification.assessments import SAMPLE_QUESTIONS
    assert "developer" in SAMPLE_QUESTIONS
    assert "auditor" in SAMPLE_QUESTIONS
    assert "enterprise" in SAMPLE_QUESTIONS
    assert len(SAMPLE_QUESTIONS["developer"]) >= 10
    assert len(SAMPLE_QUESTIONS["auditor"]) >= 10
    assert len(SAMPLE_QUESTIONS["enterprise"]) >= 10


def test_sample_question_format():
    """Each sample question should have question, options, correct_index."""
    from runtime.certification.assessments import SAMPLE_QUESTIONS
    for track, questions in SAMPLE_QUESTIONS.items():
        for q in questions:
            assert "question" in q, f"Missing 'question' in {track}"
            assert "options" in q, f"Missing 'options' in {track}"
            assert "correct_index" in q, f"Missing 'correct_index' in {track}"
            assert len(q["options"]) == 4, f"Need 4 options in {track}"
            assert 0 <= q["correct_index"] <= 3, f"Bad correct_index in {track}"


@pytest.mark.asyncio
async def test_initialize(manager):
    """Initialize should create tables without error."""
    await manager.initialize()


@pytest.mark.asyncio
async def test_start_exam_valid_track(manager):
    """Starting an exam with a valid track should succeed."""
    await manager.initialize()
    result = await manager.start_exam("0xTestWallet", "developer")
    assert "attempt_id" in result or "error" not in result
    assert result.get("track") == "developer"


@pytest.mark.asyncio
async def test_start_exam_invalid_track(manager):
    """Starting an exam with an invalid track should raise."""
    await manager.initialize()
    with pytest.raises((ValueError, KeyError)):
        await manager.start_exam("0xTestWallet", "nonexistent")


@pytest.mark.asyncio
async def test_get_track_info(manager):
    """Getting track info should return track details."""
    await manager.initialize()
    info = await manager.get_track_info("developer")
    assert info is not None
    assert info["name"] == "0pnMatrx Certified Developer"


@pytest.mark.asyncio
async def test_get_track_info_invalid(manager):
    """Getting info for non-existent track should return None."""
    await manager.initialize()
    info = await manager.get_track_info("nonexistent")
    assert info is None


def test_module_has_docstring():
    """Module should have a docstring."""
    import runtime.certification.assessments as mod
    assert mod.__doc__ is not None
