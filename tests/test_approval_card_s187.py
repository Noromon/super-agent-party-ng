# S187：审批卡与 Vue 响应式冻结冲突根治（2026-10-31 三次实测）。
# 根因：冻结代码先 Object.freeze(block) 后经代理读 block.data——data 已成
# 不可配置只读属性而 approvalData 仍可扩展 → Vue 包装返回值≠原值 → V8 proxy
# 不变量违例（toast "proxy did not return its actual value" 逐字吻合）。
# 且卡被冻后任何经代理改写（点击转块/折叠）必失败 → 点击后卡保持原样。
# 钉桩：markRaw 审批数据；两处冻结 toRaw+跳过 approval；点击/折叠元素替换式；
# catch 不恢复回卡。
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

CHAT_JS = (_ROOT / "static" / "js" / "methods" / "10_chat_stream.js").read_text(encoding="utf-8")
RESUME_JS = (_ROOT / "static" / "js" / "methods" / "13_resume_stream.js").read_text(encoding="utf-8")
BLOCKS_JS = (_ROOT / "static" / "js" / "methods" / "11_tool_blocks.js").read_text(encoding="utf-8")


def _approval_body():
    i = CHAT_JS.index("async processToolApproval")
    return CHAT_JS[i:CHAT_JS.index("    updateUIBlock(msg, blockId, newHtml)")]


class TestMarkRawAndFreezeSafety:
    def test_approval_data_mark_raw_at_creation(self):
        i = RESUME_JS.index("if (isApproval && approvalData) {")
        assert "Vue.markRaw(approvalData)" in RESUME_JS[i:i + 400]

    def test_getblock_freeze_uses_toraw_and_skips_approval(self):
        i = CHAT_JS.index("const getBlock = (type, id = null, name = null)")
        seg = CHAT_JS[i:i + 2200]
        assert "Vue.toRaw(last)" in seg
        assert "_raw.type !== 'approval'" in seg
        # 冻结后不得再经代理读 .data（旧炸点：Object.freeze(last) 后 last.data）
        old = "Object.freeze(last);\n                if (typeof last.content === 'string')"
        assert old not in CHAT_JS

    def test_streamend_freeze_skips_approval(self):
        assert "_raw.type === 'approval' || _raw.type === 'ask') return;" in CHAT_JS
        i = CHAT_JS.index("冻结已完成消息的所有 displayBlocks")
        seg = CHAT_JS[i:i + 900]
        assert "Vue.toRaw(block)" in seg
        assert "if (!Object.isFrozen(block)) {" not in seg


class TestReplaceStyleMutation:
    def test_click_converts_via_element_replace(self):
        body = _approval_body()
        assert "displayBlocks.findIndex(b => b && b.id === toolCallId && b.type === 'approval')" in body
        assert "currentMsg.displayBlocks[_idx] = _nb;" in body
        assert "Object.assign({}, _src, {" in body
        # 旧的经代理原地改写已移除
        assert "targetBlock.type = 'tool_result';\n                targetBlock.name = action === 'deny' ? this.t('denying')" not in body

    def test_collapse_via_element_replace(self):
        assert "msg.displayBlocks[idx] = _nb;" in BLOCKS_JS
        assert "Vue.toRaw(b)" in BLOCKS_JS

    def test_getblock_name_write_guarded(self):
        i = CHAT_JS.index("const existing = blocks.find(b => b.type === type && b.id === id)")
        seg = CHAT_JS[i:i + 500]
        assert "Object.isFrozen(_rex)" in seg


class TestClickFlowOrder:
    def test_conversion_before_backend_call(self):
        body = _approval_body()
        assert body.index("currentMsg.displayBlocks[_idx] = _nb;") < body.index("executeToolBackend")

    def test_catch_writes_error_into_block(self):
        body = _approval_body()
        assert "targetBlock.name = `${toolName} 执行失败`;" in body
        assert "this._setResultDisplay(targetBlock, `执行失败: ${_cm}`);" in body
