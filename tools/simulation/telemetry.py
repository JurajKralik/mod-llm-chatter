"""Public decisions and chat traces; never model private reasoning or credentials."""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

_logger = logging.getLogger('simulation.events')
_lock = threading.Lock()


def record(kind, **fields):
    with _lock:
        if not _logger.handlers:
            path = Path(os.getenv('LLM_SIM_TRACE_PATH', str(Path(__file__).resolve().parents[1] / 'simulation-events.jsonl')))
            handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(message)s'))
            _logger.addHandler(handler)
            _logger.setLevel(logging.INFO)
            _logger.propagate = False
    _logger.info(json.dumps({'time': datetime.now(timezone.utc).isoformat(), 'kind': kind, **fields}, ensure_ascii=False))
