# -*- coding: utf-8 -*-
"""Source-level pins for the frontend single-source-of-truth invariants:
A1 (C-2/C-6): resume replay must share the same tool-frame ingest as the
main loop (backend_content bookkeeping + approval/async branches).
A2: system prompt edits must sync into the conversation copy so a restart
cannot let a stale copy clobber the restored top-level value."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "static" / "js" / "vue_methods.js").read_text(encoding="utf-8")


def _slice(name, src=SRC):
    start = src.index(name)
    return src[start:]


class TestToolFrameSingleSource:
    def test_helpers_defined(self):
        assert "_ingestToolProgress(progress, getBlock, toolCallStack)" in SRC
        assert "_ingestToolFrame(tool, delta, currentMsg, getBlock, toolCallStack)" in SRC

    def test_both_paths_call_helpers(self):
        # main loop + resume, exactly two call sites each
        assert SRC.count("this._ingestToolProgress(") == 2
        assert SRC.count("this._ingestToolFrame(") == 2

    def test_helper_carries_backend_and_approval_bookkeeping(self):
        body = _slice("_ingestToolFrame(tool, delta, currentMsg")
        assert "currentMsg.backend_content.push({ role: 'tool', tool_call_id: toolCallId" in body
        assert "approval_required" in body
        assert 'tool.content.startsWith(\'{"__sap_approval_v1__":1,\')' in body
        assert 'tool.content.includes(\'"approval_required"\')' not in body
        assert "this.approvalMap[toolCallId] = approvalData" in body
        assert "approvalData._stream_id = this._currentStreamId || null" in body
        assert "this.asyncToolsID.splice(index, 1)" in body

    def test_no_duplicated_ingest_remains(self):
        # inline re-ingest copies must be gone; only the helpers keep the logic
        assert SRC.count("const progress = delta.tool_progress;") == 0
        assert SRC.count("const tool = delta.tool_content;") == 0

    def test_resume_success_syncs_body(self):
        resume = _slice("_resumeStream(streamId, fromIndex, currentMsg")
        resume = resume[: resume.index("所有重试均失败")]
        assert "this._ingestToolFrame(" in resume
        assert "this._ingestToolProgress(" in resume
        assert "this._syncAssistantBody(currentMsg)" in resume
        assert "this.asyncToolsID.push(delta.async_tool_id)" in resume


class TestSystemPromptPersistence:
    def test_persist_helper(self):
        body = _slice("async _persistSystemPrompt()")
        body = body[: body.index("async resetMessage")]
        assert "conv.system_prompt = this.system_prompt" in body
        assert "this.markConvDirty(conv.id)" in body
        assert "await this.flushDirtyConversations()" in body

    def test_edit_paths_persist(self):
        assert SRC.count("await this._persistSystemPrompt();") == 3

    def test_load_no_conditional_space_override(self):
        assert 'this.system_prompt = conversation.system_prompt?conversation.system_prompt:" ";' not in SRC
        assert "const _spConv = conversation.system_prompt;" in SRC
        assert "_spConv.trim()" in SRC

    def test_load_heals_stale_copy(self):
        load = _slice("async loadConversation(convId)")
        load = load[: load.index("formatConversationTime")]
        assert "conversation.system_prompt !== this.system_prompt" in load
        assert "conversation.system_prompt = this.system_prompt" in load
        assert "this.markConvDirty(convId)" in load

    def test_send_message_update_syncs_copy(self):
        assert SRC.count("conv.system_prompt = this.system_prompt;") == 2

    @pytest.mark.parametrize("snippet", [
        "resetMessage(index)",
        "async saveEdit()",
    ])
    def test_smoke_snippets_exist(self, snippet):
        assert snippet in SRC


class TestDeadLinkCleanupPins:
    """R4 dead-code sweep: broken links fixed to real endpoints, dead branches gone."""

    def test_no_broken_llm_models_link(self):
        assert "fetch(`/llm_models`" not in SRC
        assert "fetch(`/v1/providers/models`" in SRC

    def test_add_vector_row_real_post(self):
        body = _slice("async addVectorRow()")
        body = body[: body.index("startEditRow")]
        assert "method: 'POST'" in body
        assert "content: this.newVectorText.trim()" in body
        assert "await this.loadVectorTable(mid)" in body

    def test_dead_branches_removed(self):
        # backend never sends tool_approval type frames nor 'behavior' WS events
        assert "tool.type === 'tool_approval'" not in SRC
        assert "data.type === 'behavior'" not in SRC
        # commented-out wx_bot era remnants stay removed
        assert "start_wx_bot" not in SRC
        assert "wx_bot_status" not in SRC


class TestBackupUiPins:
    """M4-lite Data Guard UI: endpoints wired, loading guards, i18n both langs."""

    HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    ZH = (ROOT / "static" / "js" / "locales" / "zh-CN.js").read_text(encoding="utf-8")
    EN = (ROOT / "static" / "js" / "locales" / "en-US.js").read_text(encoding="utf-8")

    def test_endpoints_wired(self):
        for url in ("/api/backup/list", "/api/backup/now", "/api/backup/verify"):
            assert url in SRC
        for fn in ("loadBackupList(", "backupNow(", "verifyBackup(", "formatBackupBytes("):
            assert fn in SRC

    def test_ui_buttons_connected(self):
        for hook in ('@click="backupNow"', '@click="loadBackupList"',
                     'v-model="systemSettings.backupIncludeUploads"',
                     'formatBackupBytes(scope.row.bytes)'):
            assert hook in self.HTML

    def test_reentrancy_guard(self):
        body = _slice("async backupNow()")
        assert "if (this.backupNowRunning) return;" in body

    def test_i18n_keys_in_both_languages(self):
        import re
        zh_keys = set(re.findall(r"'(dataGuard\w+)'", self.ZH))
        en_keys = set(re.findall(r"'(dataGuard\w+)'", self.EN))
        assert zh_keys and zh_keys == en_keys
        used = set(re.findall(r"t\('(dataGuard\w+)'\)", self.HTML)) | \
               set(re.findall(r"this\.t\('(dataGuard\w+)'\)", SRC))
        assert used and used <= zh_keys, f"missing i18n keys: {used - zh_keys}"


class TestScopeFixPins:
    """R1 undefined-reference sweep: real defects fixed, implicit globals
    declared, legacy eslint exemptions removed (repo-wide no-undef active)."""

    RENDERER = (ROOT / "static" / "js" / "renderer.js").read_text(encoding="utf-8")
    DATA = (ROOT / "static" / "js" / "vue_data.js").read_text(encoding="utf-8")

    def test_no_python_style_named_args_left(self):
        assert "isEnd=false" not in SRC and "isEnd = false)" not in SRC
        assert "role = 'system')" not in SRC
        assert "this.sendMessage('system')" in SRC

    def test_implicit_globals_now_declared(self):
        # fileName trio + url family + storage response/data
        assert SRC.count("const fileName = ") >= 3
        assert "\n        url = " not in SRC and "\n      fileName = " not in SRC
        assert "const HOST = " in self.DATA and "const PORT = " in self.DATA

    def test_catch_scope_fixes(self):
        # addA2AServer: newurl declared before try (catch cleanup needs it)
        head = SRC[SRC.index("async addA2AServer() {"):]
        assert head.index("const newurl") < head.index("try {")
        # batchDeleteFiles catch logs the exception, not an out-of-scope var
        batch = SRC[SRC.index("async batchDeleteFiles()"):]
        batch = batch[: batch.index("} catch (e) {") + 900]
        assert "console.log('batchDeleteFiles error:', e)" in batch

    def test_wecom_separators_computed_complete(self):
        seg = self.RENDERER[self.RENDERER.index("filteredWeComSeparators()"):]
        seg = seg[: seg.index("},")]
        assert "const custom = current" in seg
        assert self.RENDERER.count("...custom];") >= 2  # feishu + wecom


class TestResumeScopePin:
    """resume state must be declared BEFORE the main try so the catch-side
    resume branch can see it (was a ReferenceError swallowed-handler bug,
    first caught by eslint no-undef in M-2 rollout)."""

    def test_declarations_outside_try(self):
        decl = SRC.index("let _streamId = null;")
        fetch = SRC.index("const response = await fetch(`/v1/chat/completions`")
        assert decl < fetch, "resume declarations must live before the main try block"
        assert "let _streamId = null;" not in SRC[fetch:]
        # catch branch keeps consuming them
        assert "if (_enableStreamResume && _streamId && _chunkIndex > 0" in SRC


class TestStreamIdHeaderPin:
    """C-14: stream id captured from the response header (no meta-frame wait)."""

    def test_header_capture_before_meta_frame(self):
        assert "response.headers.get('X-Stream-Id')" in SRC
        # meta-frame fallback path stays intact (belt and braces)
        assert "delta.stream_id && !_streamId" in SRC
        # captured id feeds both resume and cancel paths
        hdr = _slice("const _hdrStreamId = response.headers.get('X-Stream-Id');")
        hdr = hdr[: hdr.index("while (true)")]
        assert "this._currentStreamId = _streamId" in hdr


class TestSettingsSchemaSingleSource:
    """批 0-④: settings save/restore driven by settings_schema.js (no hand lists)."""

    SCHEMA = (ROOT / "static" / "js" / "settings_schema.js").read_text(encoding="utf-8")

    def test_schema_defined_and_wired(self):
        assert "window.SETTINGS_SCHEMA" in self.SCHEMA
        assert "window.SETTINGS_SCHEMA.buildSettingsPayload(this)" in SRC
        assert "window.SETTINGS_SCHEMA.applySettingsPayload(this, data.data)" in SRC
        assert "window.SETTINGS_SCHEMA.buildSettingsFromWire(data.data)" in SRC

    def test_hand_written_lists_retired(self):
        # 恢复侧手写 `this.X = data.data.W ||` 只允许特例（≤4：isdocker+对话三元组）
        assert len(re.findall(r"this\.\w+ = data\.data\.\w+ \|\|", SRC)) <= 4
        # 保存侧：autoSaveSettings 函数体内不得再出现手写映射（函数外对象字面量不算）
        body = _slice("async autoSaveSettings()")
        body = body[: body.index("const correlationId")]
        assert not re.search(r"\w+:\s*this\.\w+,\n\s*\w+:\s*this\.\w+,", body), \
            "autoSaveSettings 手写清单回潮"

    def test_schema_pairs_self_consistent(self):
        pairs = re.findall(r"\['(\w+)',\s*'(\w+)'\]", self.SCHEMA)
        wires = [w for w, _ in pairs]
        states = [s for _, s in pairs]
        assert len(pairs) >= 60
        assert len(set(wires)) == len(wires), "PAIRS wire 键重复"
        assert len(set(states)) == len(states), "PAIRS state 字段重复"
        special = re.search(r"RESTORE_SPECIAL = new Set\(\[([\s\S]*?)\]\)", self.SCHEMA)
        special_keys = set(re.findall(r"'(\w+)'", special.group(1)))
        assert special_keys <= set(wires), "RESTORE_SPECIAL 引用了表外 wire 键"

    def test_pages_load_schema_before_methods(self):
        for page in ("index.html", "chat.html"):
            html = (ROOT / "static" / page).read_text(encoding="utf-8")
            assert html.index("settings_schema.js") < html.index("vue_methods.js"), page
