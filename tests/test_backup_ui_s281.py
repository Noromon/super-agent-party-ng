# build=S295
# S281：备份 UI——类型列/构成展开行/内容与容量面板/按项勾选。源码级静态锁。
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

HTML = (_ROOT / "static" / "templates" / "page_system.html").read_text(encoding="utf-8")
JS = (_ROOT / "static" / "js" / "methods" / "62_backup.js").read_text(encoding="utf-8")
DATA = (_ROOT / "static" / "js" / "data" / "20_brain_settings.js").read_text(encoding="utf-8")
ZH = (_ROOT / "static" / "js" / "locales" / "zh-CN.js").read_text(encoding="utf-8")
EN = (_ROOT / "static" / "js" / "locales" / "en-US.js").read_text(encoding="utf-8")


def test_backup_js_contract():
    # 目录与后端 BACKUP_ITEM_IDS 同序同集
    m = re.search(r"const BACKUP_ITEM_IDS = \[([^\]]+)\]", JS)
    assert m
    ids = re.findall(r'"(\w+)"', m.group(1))
    assert ids == ["settings", "appdb", "convdb", "txtidx", "memory_cache",
                   "agents", "kb", "diary", "ext", "uploads"]
    for api in ("/api/backup/estimate", "loadBackupEstimate(", "backupItemLabel(",
                "backupItemDefaultAuto(", "setBackupSel(", "saveBackupAutoItems("):
        assert api in JS, api
    # 手动备份必须带 include 体（空选择有拦截）
    assert "JSON.stringify(inc ? { include: inc } : {})" in JS
    assert "dataGuardSelEmpty" in JS
    # 全选回落 null：不把目录写死，新增项不被旧配置挡住
    assert "this.systemSettings.backupAutoItems = (sel.length === BACKUP_ITEM_IDS.length) ? null : sel;" in JS
    assert "await this.autoSaveSettings();" in JS
    # 遗留开关推导：False → 排除 uploads
    assert "backupIncludeUploads === false" in JS
    # 负值守卫（disk_free 取不到显示占位）
    assert "if (n < 0) return '--';" in JS


def test_template_hooks():
    for hook in ('v-if="backupEstimate"', '@click="loadBackupEstimate"',
                 "@change=\"v => setBackupSel('auto', it.id, v)\"",
                 "@change=\"v => setBackupSel('manual', it.id, v)\"",
                 'type="expand"', "scope.row.items", "scope.row.trigger === 'manual'"):
        assert hook in HTML, hook
    # 旧的全量开关已移除（构成面板取代）
    assert "backupIncludeUploads" not in HTML
    assert "dataGuardIncludeUploads" not in HTML


def test_data_defaults():
    assert "backupAutoItems: null," in DATA
    for k in ("backupEstimate: null", "backupEstimateLoading: false",
              "backupSelAuto: []", "backupSelManual: []", "backupSelInit: false"):
        assert k in DATA, k


def _keys(text, prefix):
    return set(re.findall(r"'(" + prefix + r"\w*)':", text))


def test_i18n_new_keys_parity_and_used():
    zh = _keys(ZH, "dataGuard") | _keys(ZH, "backupItem_")
    en = _keys(EN, "dataGuard") | _keys(EN, "backupItem_")
    assert zh and zh == en
    used = set(re.findall(r"t\('(dataGuard\w+)'\)", HTML))
    used |= set(re.findall(r"this\.t\('(dataGuard\w+)'\)", JS))
    used.add("dataGuardEstFail")  # JS 动态拼接不在正则内？不——上面已含；保留冗余防重构漏网
    assert used <= zh, used - zh
    # 10 个项标签双语齐备
    for pid in ("settings", "appdb", "convdb", "txtidx", "memory_cache",
                "agents", "kb", "diary", "ext", "uploads"):
        assert "backupItem_" + pid in zh and "backupItem_" + pid in en, pid


def test_obsolete_switch_gone():
    assert "dataGuardIncludeUploads" not in ZH
    assert "dataGuardIncludeUploads" not in EN
