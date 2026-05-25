import logging
from logging.config import dictConfig


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structured, production-style logging for the API service."""
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                }
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                }
            },
            "root": {"handlers": ["default"], "level": log_level.upper()},
        }
    )

    logging.getLogger(__name__).info("Logging configured", extra={"log_level": log_level.upper()})
