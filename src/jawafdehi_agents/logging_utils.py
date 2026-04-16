from __future__ import annotations

import logging
from pathlib import Path

NOISY_LOGGERS = (
    "pdfminer",
    "httpx",
    "httpcore",
    "openai",
    "asyncio",
    "charset_normalizer",
    "markdown_it",
    "urllib3",
)


def configure_run_logging(logs_dir: Path, case_number: str) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "verbose.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    root_logger.propagate = False

    for logger_name in NOISY_LOGGERS:
        noisy_logger = logging.getLogger(logger_name)
        noisy_logger.setLevel(logging.WARNING)
        noisy_logger.propagate = True

    logging.getLogger(__name__).debug(
        "Configured verbose run logging for case %s at %s",
        case_number,
        log_path,
    )

    return log_path
