"""seri_ssh package

Provides a small logging configuration helper for the package.
"""
import logging
from typing import Optional


def configure_logging(level: str = "INFO", logfile: Optional[str] = None) -> None:
	"""Configure basic logging for the package.

	Args:
		level: Logging level name (e.g. "INFO", "DEBUG").
		logfile: Optional path to a file to write logs to. If omitted, logs go to stderr.
	"""
	lvl = getattr(logging, level.upper(), logging.INFO)
	handlers = []
	if logfile:
		handlers.append(logging.FileHandler(logfile))
	else:
		handlers.append(logging.StreamHandler())
	logging.basicConfig(level=lvl, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)


logger = logging.getLogger("seri_ssh")

__all__ = ["cli", "server", "configure_logging", "logger"]
