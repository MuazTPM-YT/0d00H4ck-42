from sqlalchemy import select

from app.core.codes import CodeSequence, next_code
from app.core.idempotency import run_once


def test_codes_are_sequential_and_formatted(db):
    first = next_code(db, "YB")
    second = next_code(db, "YB")
    assert first.startswith("YB-") and len(first) == 9
    assert int(second[3:]) == int(first[3:]) + 1


def test_rollback_leaves_no_gap(db):
    first = next_code(db, "RC")
    savepoint = db.begin_nested()
    next_code(db, "RC")
    savepoint.rollback()
    assert int(next_code(db, "RC")[3:]) == int(first[3:]) + 1


def test_same_idempotency_key_returns_same_code_and_burns_one(db):
    def issue():
        return {"code": next_code(db, "R")}

    a = run_once(db, "scan-123", "roll.create", issue)
    b = run_once(db, "scan-123", "roll.create", issue)
    assert a == b
    seq = db.scalar(select(CodeSequence).where(CodeSequence.prefix == "R"))
    db.refresh(seq)
    assert f"R-{seq.last_value:06d}" == a["code"]


def test_idempotency_key_reused_for_other_action_is_409(db):
    import pytest

    from app.core.errors import Conflict

    run_once(db, "scan-9", "qc.decide", lambda: {"ok": True})
    with pytest.raises(Conflict):
        run_once(db, "scan-9", "dispatch.add", lambda: {"ok": True})
