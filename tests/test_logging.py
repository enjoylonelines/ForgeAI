import json
import logging

import pytest

from core.logging import _JsonFormatter


@pytest.fixture()
def formatter():
    return _JsonFormatter()


def _make_record(msg, *args, level=logging.INFO):
    record = logging.LogRecord(
        name="test", level=level, pathname="", lineno=0,
        msg=msg, args=args, exc_info=None,
    )
    return record


def test_dict_log_produces_json_keys(formatter):
    record = _make_record({"event": "machine_stop", "tool_wear": 42})
    output = json.loads(formatter.format(record))

    assert output["event"] == "machine_stop"
    assert output["tool_wear"] == 42
    assert "message" not in output


def test_str_log_unchanged(formatter):
    record = _make_record("hello world")
    output = json.loads(formatter.format(record))

    assert output["message"] == "hello world"


def test_str_log_with_args(formatter):
    record = _make_record("value=%s", 99)
    output = json.loads(formatter.format(record))

    assert output["message"] == "value=99"


def test_standard_fields_present(formatter):
    record = _make_record("ping")
    output = json.loads(formatter.format(record))

    assert "timestamp" in output
    assert output["level"] == "INFO"
    assert output["name"] == "test"
