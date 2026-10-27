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
    root = logging.getLogger()
    saved_root_h, saved_root_level = list(root.handlers), root.level
    logging.getLogger("app").handlers.clear()
    logging.getLogger("mem0").handlers.clear()
    root.handlers.clear()
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
        # S155：root 挂同一 file handler（bot 线程 root logging.* 入档）、
        # app 不再双写、高噪声库压到 WARNING
        assert any(getattr(h, "baseFilename", "") == fh.baseFilename
                   for h in root.handlers)
        assert logging.getLogger("app").propagate is False
        assert logging.getLogger("openai").level == logging.WARNING
        logging.info("root-rotation-probe-s155")
        with io.open(fh.baseFilename, encoding="utf-8") as f:
            body = f.read()
        assert body.count("m5-rotation-probe") == 1  # app→root 双写防住
        assert "root-rotation-probe-s155" in body
    finally:
        seen = set()
        for lg in (logging.getLogger("app"), logging.getLogger("mem0"), root):
            for h in list(lg.handlers):
                if id(h) not in seen:
                    seen.add(id(h))
                    h.close()
            lg.handlers.clear()
        logging.getLogger("mem0").propagate = True
        logging.getLogger("app").propagate = True
        root.handlers[:] = saved_root_h
        root.setLevel(saved_root_level)


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
