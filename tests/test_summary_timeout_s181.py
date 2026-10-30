# S181: the diary chat-summary used a hardcoded 120s wait and a fixed 300s retry
# backoff. With locally-hosted models (serial inference; the summary request queues
# behind active generation) 120s is routinely exceeded -> ReadTimeout(''). Both the
# response timeout and the retry interval are now user-configurable per character
# (chatSummary.timeoutSeconds / chatSummary.retrySeconds), sanitized in the engine
# and clamped in the integration (read 10..1800s, retry 10..3600s); defaults keep
# the previous behavior (120/300).
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTEG = (ROOT / "py" / "diary_chat_integration.py").read_text(encoding="utf-8")
ENGINE = (ROOT / "py" / "diary_engine.py").read_text(encoding="utf-8")
TPL = (ROOT / "static" / "templates" / "page_role.html").read_text(encoding="utf-8")
DATA_JS = (ROOT / "static" / "js" / "data" / "60_cards_options.js").read_text(encoding="utf-8")
ZH = (ROOT / "static" / "js" / "locales" / "zh-CN.js").read_text(encoding="utf-8")
EN = (ROOT / "static" / "js" / "locales" / "en-US.js").read_text(encoding="utf-8")


class TestIntegrationKnobs:
    def test_signature_accepts_knobs(self):
        assert "async def summarize_and_save_buffers(idle_minutes: int = 15, timeout_seconds=None, retry_cooldown=None)" in INTEG

    def test_defaults_preserved(self):
        assert "_RETRY_COOLDOWN = 300.0" in INTEG
        assert "_DEFAULT_READ_TIMEOUT = 120.0" in INTEG

    def test_clamps_present(self):
        assert "min(max(read_timeout, 10.0), 1800.0)" in INTEG
        assert "min(max(retry_eff, 10.0), 3600.0)" in INTEG

    def test_connect_stays_short_read_gets_the_knob(self):
        assert "httpx.Timeout(_CONNECT_TIMEOUT, read=read_timeout" in INTEG
        assert "httpx.AsyncClient(timeout=http_cfg)" in INTEG

    def test_failure_backoff_uses_effective_retry(self):
        assert "_RETRY_AFTER[key] = time.time() + retry_eff" in INTEG
        assert "{retry_eff:.0f}s 后重试" in INTEG


class TestEnginePassthrough:
    def test_reads_both_keys_from_config(self):
        assert '_cfg_num("timeoutSeconds")' in ENGINE
        assert '_cfg_num("retrySeconds")' in ENGINE

    def test_passes_knobs_into_task(self):
        assert "summarize_and_save_buffers(idle_min, summary_timeout, summary_retry)" in ENGINE

    def test_illegal_values_coerce_to_zero_then_defaults(self):
        assert "int(summary_cfg.get(name, 0) or 0)" in ENGINE
        assert "except (TypeError, ValueError)" in ENGINE


class TestUiSurface:
    def test_inputs_bound_in_template(self):
        assert "diarySettings.chatSummary.timeoutSeconds" in TPL
        assert "diarySettings.chatSummary.retrySeconds" in TPL
        assert ':max="1800"' in TPL
        assert ':max="3600"' in TPL

    def test_defaults_in_data_js(self):
        assert "timeoutSeconds: 120" in DATA_JS
        assert "retrySeconds: 300" in DATA_JS

    def test_locale_keys_present(self):
        for src in (ZH, EN):
            assert "diaryChatSummaryTimeout" in src
            assert "diaryChatSummaryRetry" in src
