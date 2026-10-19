# -*- coding: utf-8 -*-
"""Source-level pins for the frontend single-source-of-truth invariants:
A1 (C-2/C-6): resume replay must share the same tool-frame ingest as the
main loop (backend_content bookkeeping + approval/async branches).
A2: system prompt edits must sync into the conversation copy so a restart
cannot let a stale copy clobber the restored top-level value."""
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
