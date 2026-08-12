import logging

from org_timeviz.logging_utils import setup_logger


def test_setup_logger_accepts_known_and_unknown_levels(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: calls.append(kwargs))
    setup_logger("DEBUG")
    setup_logger("not-a-level")
    assert calls[0]["level"] == logging.DEBUG
    assert calls[1]["level"] == logging.INFO
