# -*- coding: utf-8 -*-
"""M-5 logging infrastructure tests (audit 09 item 8).

Covers: rotating-file bootstrap (py/log_setup.py) and the print-ratchet
that keeps the 434-site conversion from regressing back to bare print().
"""
import ast
import glob
import importlib.util
import io
import logging
import os
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("log_setup", _ROOT / "py" / "log_setup.py")
_ls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ls)
BACKUP_COUNT, MAX_BYTES, setup_logger = _ls.BACKUP_COUNT, _ls.MAX_BYTES, _ls.setup_logger

# print() forms deliberately kept by the sweep (multi-arg / sep / end / file)
PRINT_BASELINE = 38


def test_setup_logger_rotating_and_idempotent(tmp_path):
    logging.getLogger("app").handlers.clear()
    try:
        lg = setup_logger(str(tmp_path))
        n1 = len(lg.handlers)
        lg2 = setup_logger(str(tmp_path))
        assert lg2 is lg and len(lg2.handlers) == n1  # idempotent
        fhs = [h for h in lg.handlers if type(h).__name__ == "RotatingFileHandler"]
        assert len(fhs) == 1
        fh = fhs[0]
        assert fh.maxBytes == MAX_BYTES and fh.backupCount == BACKUP_COUNT
        assert os.path.basename(fh.baseFilename) == "backend.log"
        lg.info("m5-rotation-probe")
        with io.open(fh.baseFilename, encoding="utf-8") as f:
            assert "m5-rotation-probe" in f.read()
    finally:
        for h in logging.getLogger("app").handlers:
            h.close()
        logging.getLogger("app").handlers.clear()


def test_print_ratchet():
    files = ["server.py"] + [f for f in glob.glob("py/**/*.py", recursive=True)]
    total = 0
    for path in files:
        norm = "/" + path.replace("\\", "/")
        if "/blivedm/" in norm:
            continue
        if norm == "/py/dynamic_island.py":
            continue  # S139(R6)：上游逐字节文件，print 日志原样，同 blivedm 豁免
        try:
            tree = ast.parse(io.open(path, encoding="utf-8-sig").read())
        except (SyntaxError, UnicodeDecodeError):
            continue
        total += sum(
            1 for nd in ast.walk(tree)
            if isinstance(nd, ast.Call) and isinstance(nd.func, ast.Name)
            and nd.func.id == "print"
        )
    assert total <= PRINT_BASELINE, (
        "bare print() grew beyond baseline %d (now %d): new logging must go "
        "through logging.getLogger(\"app\")" % (PRINT_BASELINE, total)
    )
