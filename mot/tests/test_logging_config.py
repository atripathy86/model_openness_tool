import json
import logging

from model_openness_tool.logging_config import JsonFormatter


def test_json_formatter_emits_standard_and_structured_fields() -> None:
    record = logging.LogRecord(
        name="model_openness_tool.worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="job claimed",
        args=(),
        exc_info=None,
    )
    record.event = "job_claimed"
    record.job_id = "job-1"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "info"
    assert payload["logger"] == "model_openness_tool.worker"
    assert payload["message"] == "job claimed"
    assert payload["event"] == "job_claimed"
    assert payload["job_id"] == "job-1"
    assert payload["timestamp"].endswith("+00:00")
