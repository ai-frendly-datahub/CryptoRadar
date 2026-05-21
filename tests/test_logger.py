from __future__ import annotations

import structlog

from cryptoradar.logger import configure_logging, get_logger


def test_configure_logging_console_and_json_modes() -> None:
    configure_logging(log_level="DEBUG", use_json=False)
    console_processors = structlog.get_config()["processors"]
    assert any(type(processor).__name__ == "ConsoleRenderer" for processor in console_processors)

    configure_logging(log_level="INFO", use_json=True)
    json_processors = structlog.get_config()["processors"]
    assert any(type(processor).__name__ == "JSONRenderer" for processor in json_processors)


def test_get_logger_returns_bound_logger() -> None:
    configure_logging(log_level="INFO", use_json=True)

    logger = get_logger("cryptoradar.tests")

    assert hasattr(logger, "info")
    assert hasattr(logger, "bind")
