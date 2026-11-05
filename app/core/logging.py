"""Structured Logging Configuration Module.

This file sets up logging for BYKERS.
Non-negotiable Privacy Rule: Never log OTPs, tokens, full phone numbers, or passwords.
This module includes a redaction filter to scrub sensitive data before printing to logs.
"""

import logging
import re

# Regex patterns to scrub sensitive data from log lines
SENSITIVE_PATTERNS = [
    (
        re.compile(
            r'(?i)(password|secret|token|otp|authorization|key)[\s:=]+["\']?([^"\'\s,]+)["\']?'
        ),
        r"\1=[REDACTED]",
    ),
    (re.compile(r"(\+91\d{2})\d{6}(\d{2})"), r"\1******\2"),  # Mask Indian phone numbers partially
]


class SensitiveDataFilter(logging.Filter):
    """Logging filter that scrubs sensitive fields like passwords, tokens, and OTPs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern, replacement in SENSITIVE_PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)

        if record.args:
            cleaned_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    for pattern, replacement in SENSITIVE_PATTERNS:
                        arg = pattern.sub(replacement, arg)
                cleaned_args.append(arg)
            record.args = tuple(cleaned_args)

        return True


def setup_logging(env: str = "dev") -> None:
    """Configures structured console logging with privacy redaction."""
    log_level = logging.DEBUG if env == "dev" else logging.INFO

    # Custom format including timestamp, logger name, log level, and message
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(SensitiveDataFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        root_logger.addHandler(handler)
    else:
        root_logger.handlers = [handler]

    # Silence overly verbose third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
