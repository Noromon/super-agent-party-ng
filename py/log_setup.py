# -*- coding: utf-8 -*-
"""Central logging bootstrap (R1 / audit 09 item 8, M-5).

One rotating file (backend.log, 5 MB x 5) under the shared LOG_DIR plus a
stdout stream handler: the stdout handler keeps the console output that
print() used to produce (Electron's main process shows it), while the file
handler adds persistence with rotation -- the previous scheme wrote one
uncapped backend_<timestamp>.log per launch and never cleaned them up.

Every print() converted by the M-5 sweep calls this logger through a module
local handle (`_applog = logging.getLogger("app")`), which is importable
before setup_logger runs: early records go to logging's last-resort handler
and are picked up by the real handlers as soon as setup attaches them.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5


def setup_logger(log_dir):
    """Attach rotating-file + stdout handlers to the shared "app" logger.

    Idempotent: repeated calls (server restart in-process, tests) never
    duplicate handlers.

    S102: SAP_LOG_DIR env overrides log_dir -- Roaming logs were externally
    deleted mid-run (Defender quarantine suspect); the launcher bat points
    the file log at the repo dir so it is user-visible and machine-readable.
    """
    log_dir = os.environ.get("SAP_LOG_DIR") or log_dir
    logger = logging.getLogger("app")
    # S134：mem0.* 记录（Invalid JSON / Total existing memories 等）此前只进
    # console，backend.log 里完全不可见；同一对 handler 也挂到 "mem0"。
    mem0_logger = logging.getLogger("mem0")
    if not logger.handlers and not mem0_logger.handlers:
        fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        os.makedirs(log_dir, exist_ok=True)
        fh = RotatingFileHandler(os.path.join(log_dir, "backend.log"),
                                 maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                                 encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        for lg in (logger, mem0_logger):
            lg.setLevel(logging.INFO)
            lg.addHandler(fh)
            lg.addHandler(sh)
    return logger
