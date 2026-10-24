import io
import json
import logging
import os
import shutil
import sys
import time
import asyncio
import aiosqlite
from pathlib import Path
from appdirs import user_data_dir

try:
    from py import secret_box
except Exception:  # standalone importlib load (tests): resolve next to this file
    import importlib.util as _ilu
    _sb_spec = _ilu.spec_from_file_location(
        "secret_box", os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret_box.py"))
    secret_box = _ilu.module_from_spec(_sb_spec)
    _sb_spec.loader.exec_module(secret_box)

# ----------------- 1. 基础环境检测 (极速版) -----------------
APP_NAME = "Super-Agent-Party"
HOST = None
PORT = None

IS_DOCKER = os.environ.get("IS_DOCKER", "").lower() in ("1", "true")

def in_docker():
    return IS_DOCKER

def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    else:
        return os.path.abspath(".")

base_path = get_base_path()

# ----------------- 2. 路径定义 -----------------
if os.environ.get("SAP_DATA_DIR"):
    # 冲刺期数据隔离：开发/测试实例经环境变量指向独立目录，生产目录在切换日前对新代码只读
    USER_DATA_DIR = os.path.abspath(os.environ["SAP_DATA_DIR"])
elif IS_DOCKER:
    USER_DATA_DIR = '/app/data'
else:
    USER_DATA_DIR = user_data_dir(APP_NAME, roaming=True)

# --- 核心目录 ---
LOG_DIR = os.path.join(USER_DATA_DIR, 'logs')
MEMORY_CACHE_DIR = os.path.join(USER_DATA_DIR, 'memory_cache')
UPLOAD_FILES_DIR = os.path.join(USER_DATA_DIR, 'uploaded_files')
TOOL_TEMP_DIR = os.path.join(USER_DATA_DIR, 'tool_temp')
AGENT_DIR = os.path.join(USER_DATA_DIR, 'agents')
KB_DIR = os.path.join(USER_DATA_DIR, 'kb')
EXT_DIR = os.path.join(USER_DATA_DIR, "ext")
DEFAULT_ASR_DIR = os.path.join(USER_DATA_DIR, 'asr')
DEFAULT_TTS_DIR = os.path.join(USER_DATA_DIR, 'tts')
DEFAULT_EBD_DIR = os.path.join(USER_DATA_DIR, 'ebd')

# --- 跨平台全局Skills路径 ---
def get_global_skills_dir():
    r"""
    获取标准的全局Agent Skills目录，支持跨平台
    标准路径: ~/.agents/skills (macOS/Linux) 或 %USERPROFILE%\.agents\skills (Windows)
    """
    home_dir = Path.home()
    
    # 检查是否在Docker环境中
    if IS_DOCKER:
        # Docker环境中使用/app/.agents/skills
        docker_skills_dir = Path('/app/.agents/skills')
        docker_skills_dir.mkdir(parents=True, exist_ok=True)
        return str(docker_skills_dir)
    
    # 标准全局路径
    global_skills_dir = home_dir / '.agents' / 'skills'
    
    # 确保目录存在
    global_skills_dir.mkdir(parents=True, exist_ok=True)
    
    return str(global_skills_dir)

# 使用标准的全局skills路径
SKILLS_DIR = get_global_skills_dir()


# --- 配置文件 ---
SETTINGS_FILE = os.path.join(USER_DATA_DIR, 'settings.json')
CONFIG_BASE_PATH = os.path.join(base_path, 'config')
SETTINGS_TEMPLATE_FILE = os.path.join(CONFIG_BASE_PATH, 'settings_template.json')
BLOCKLIST_FILE = os.path.join(CONFIG_BASE_PATH, 'blocklist.json')

# --- 静态资源 ---
DEFAULT_VRM_DIR = os.path.join(base_path, 'vrm')
# S91(THA)：桌宠默认模型随包分发（base_path），用户上传模型进用户数据区
DEFAULT_THA_DIR = os.path.join(base_path, 'tha_models')
THA_USER_MODELS_DIR = os.path.join(UPLOAD_FILES_DIR, 'tha_models')
STATIC_DIR = os.path.join(base_path, "static")

# --- 数据库 ---
DATABASE_PATH = os.path.join(USER_DATA_DIR, 'super_agent_party.db')
COVS_PATH = os.path.join(USER_DATA_DIR, "conversations.db")

# 批量创建目录
dirs_to_create = [
    USER_DATA_DIR, LOG_DIR, MEMORY_CACHE_DIR, UPLOAD_FILES_DIR, 
    TOOL_TEMP_DIR, AGENT_DIR, KB_DIR, EXT_DIR, 
    DEFAULT_ASR_DIR, DEFAULT_TTS_DIR, DEFAULT_EBD_DIR, CONFIG_BASE_PATH, SKILLS_DIR,
    THA_USER_MODELS_DIR
]
for d in set(dirs_to_create):
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass

# ----------------- 3. 关键修复：恢复全局 BLOCKLIST 变量 -----------------
# 兼容 py/load_files.py 的导入需求
# 虽然有一点点 I/O，但为了保证不报错，这里必须直接执行
blocklist_data = []
if os.path.exists(BLOCKLIST_FILE):
    try:
        with open(BLOCKLIST_FILE, 'r', encoding='utf-8') as f:
            blocklist_data = json.load(f)
    except Exception:
        pass
BLOCKLIST = set(blocklist_data)

# ----------------- 4. 工具函数 -----------------

_cached_default_settings = None
_db_init_done = False
_covs_db_init_done = False

def get_blocklist():
    """保留这个函数供未来使用"""
    return BLOCKLIST

def configure_host_port(host, port):
    global HOST, PORT
    HOST = host
    PORT = port

def get_host():
    return HOST or "127.0.0.1"

def get_port():
    # 优先级：环境变量 > 全局PORT > 默认3456
    env_port = os.environ.get('DYNAMIC_PORT')
    if env_port:
        return int(env_port)
    return PORT or 3456

def change_port(new_port):
    global PORT
    PORT = new_port

def get_default_settings_sync():
    global _cached_default_settings
    if _cached_default_settings is not None:
        return _cached_default_settings
    
    if os.path.exists(SETTINGS_TEMPLATE_FILE):
        try:
            with open(SETTINGS_TEMPLATE_FILE, 'r', encoding='utf-8') as f:
                _cached_default_settings = json.load(f)
        except Exception:
            _cached_default_settings = {}
    else:
        _cached_default_settings = {}
    return _cached_default_settings

# ----------------- Agent Skills 初始化 -----------------

async def _copy_default_skills():
    """
    将项目根目录的 skills/ 复制到 USER_DATA_DIR/skills/。
    核心逻辑：若目标子目录已存在，则跳过该目录；不覆盖用户已有文件。
    """
    # 源目录：项目根目录下的 skills
    src_skills_root = os.path.join(base_path, 'skills')
    # 目标目录：用户数据目录下的 skills
    dst_skills_root = SKILLS_DIR  # 你在路径定义中已配置

    # 如果源目录根本不存在，说明这个版本没带默认技能，直接跳过
    if not os.path.isdir(src_skills_root):
        logging.info("[Skills] 项目根目录无 skills/ 文件夹，跳过初始化复制。")
        return

    # 确保目标根目录存在（你在 dirs_to_create 已包含，这里双重保障）
    os.makedirs(dst_skills_root, exist_ok=True)

    # 遍历源目录下的每一项（一级子目录/文件）
    try:
        for item_name in os.listdir(src_skills_root):
            src_path = os.path.join(src_skills_root, item_name)
            dst_path = os.path.join(dst_skills_root, item_name)

            # 仅处理目录 —— Skill 的根必须是文件夹
            if os.path.isdir(src_path):
                # 核心判断：如果目标目录已存在，完全跳过该 Skill 的复制
                if os.path.exists(dst_path):
                    logging.debug(f"[Skills] 目标技能已存在，跳过: {item_name}")
                    continue
                
                # 不存在则完整复制整个 Skill 文件夹
                # 使用 shutil.copytree，且不覆盖（因为已判断不存在）
                import shutil
                shutil.copytree(src_path, dst_path)
                logging.info(f"[Skills] 已安装默认技能: {item_name}")
            else:
                # 源根目录下的孤立文件（非标准 Skill 结构），根据你的策略可忽略或复制
                # 标准 Agent Skills 只认文件夹，这里建议忽略
                logging.debug(f"[Skills] 忽略非文件夹项: {item_name}")
    except Exception as e:
        logging.error(f"[Skills] 复制默认技能时发生错误: {e}", exc_info=True)

# ----------------- 5. 初始化逻辑 -----------------
_DB_INIT_LOCK = asyncio.Lock()
_COVS_INIT_LOCK = asyncio.Lock()


async def _try_wal(db):
    # WAL 切换需要短暂独占；并发连接在场时失败可容忍（下次启动再切）
    try:
        await db.execute('PRAGMA journal_mode=WAL')
    except Exception:
        pass


async def init_db():
    global _db_init_done
    if _db_init_done: return
    async with _DB_INIT_LOCK:
        if _db_init_done: return
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await _try_wal(db)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY,
                    data TEXT NOT NULL
                )
            ''')
            await db.commit()
        _db_init_done = True

async def _backfill_rows(db):
    """M4b shadow store: one-time row-level expansion when conversation_rows
    is still empty but the legacy blob already holds conversations."""
    try:
        async with db.execute('SELECT COUNT(*) FROM conversation_rows') as cur:
            n_rows = (await cur.fetchone())[0]
        if n_rows:
            return
        async with db.execute('SELECT data FROM settings WHERE id = 1') as cur:
            row = await cur.fetchone()
        if not row:
            return
        blob = json.loads(row[0])
        now = time.time()
        n = 0
        for conv in (blob.get("conversations") or []):
            if isinstance(conv, dict) and conv.get("id") is not None:
                await db.execute(
                    'INSERT OR REPLACE INTO conversation_rows (conv_id, data, updated_at) VALUES (?, ?, ?)',
                    (str(conv["id"]), json.dumps(conv, ensure_ascii=False), now))
                n += 1
        if n:
            logging.getLogger(__name__).info("conversation_rows backfilled from blob: %d rows", n)
    except Exception:
        logging.getLogger(__name__).warning("conversation_rows backfill failed (blob remains source of truth)", exc_info=True)


async def _sync_rows(db, conversations):
    """Align conversation_rows with the blob snapshot: upsert present ids,
    delete vanished ones. Shadow-only: callers must not let failures escape."""
    snap = {}
    for conv in conversations:
        if isinstance(conv, dict) and conv.get("id") is not None:
            snap[str(conv["id"])] = json.dumps(conv, ensure_ascii=False)
    async with db.execute("SELECT conv_id FROM conversation_rows WHERE conv_id NOT LIKE 'bot:%'") as cur:
        existing = {r[0] for r in await cur.fetchall()}
    now = time.time()
    for cid, blob in snap.items():
        await db.execute(
            'INSERT OR REPLACE INTO conversation_rows (conv_id, data, updated_at) VALUES (?, ?, ?)',
            (cid, blob, now))
    for cid in existing - set(snap):
        await db.execute('DELETE FROM conversation_rows WHERE conv_id = ?', (cid,))
    return len(snap), len(existing)


async def init_covs_db():
    global _covs_db_init_done
    if _covs_db_init_done: return
    async with _COVS_INIT_LOCK:
        if _covs_db_init_done: return
        Path(USER_DATA_DIR).mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(COVS_PATH) as db:
            await _try_wal(db)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY,
                    data TEXT NOT NULL
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS group_memory (
                    id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    source_chat_id TEXT NOT NULL,
                    source_message_id TEXT,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0.5,
                    status TEXT NOT NULL DEFAULT 'active',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    last_used_at INTEGER,
                    metadata_json TEXT
                )
            ''')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_group_memory_group_status ON group_memory(group_id, status)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_group_memory_source_chat ON group_memory(source_chat_id)')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS turn_log (
                    conversation_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    msg TEXT NOT NULL,
                    created_at REAL,
                    PRIMARY KEY (conversation_id, seq)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS conversation_rows (
                    conv_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at REAL
                )
            ''')
            await _backfill_rows(db)
            await db.commit()
        _covs_db_init_done = True

# ----------------- 6. 业务功能函数 -----------------

async def clean_temp_files_task():
    try:
        await asyncio.to_thread(_clean_temp_files_sync)
    except Exception:
        pass

def _clean_temp_files_sync():
    if not os.path.exists(TOOL_TEMP_DIR): return
    threshold = time.time() - 7 * 24 * 60 * 60
    for filename in os.listdir(TOOL_TEMP_DIR):
        file_path = os.path.join(TOOL_TEMP_DIR, filename)
        try:
            if os.path.isfile(file_path):
                if os.path.getmtime(file_path) < threshold:
                    os.remove(file_path)
        except Exception:
            pass

def convert_to_opus_simple(audio_data):
    try:
        from pydub import AudioSegment
        import imageio_ffmpeg
        
        if not getattr(AudioSegment, 'converter_configured', False):
            try:
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
                AudioSegment.converter = ffmpeg_path
                AudioSegment.converter_configured = True
            except Exception:
                logging.warning("imageio-ffmpeg execution failed")

        audio = None
        # 1. Container format
        try:
            audio_io = io.BytesIO(audio_data)
            audio = AudioSegment.from_file(audio_io)
        except Exception:
            pass
            
        # 2. Raw PCM
        if audio is None:
            try:
                audio = AudioSegment(
                    data=audio_data,
                    sample_width=2,
                    frame_rate=24000,
                    channels=1
                )
            except Exception as e:
                logging.error(f"Raw PCM read failed: {e}")
                return audio_data, False

        # 3. Export Opus
        audio = audio.set_frame_rate(16000).set_channels(1)
        out_io = io.BytesIO()
        audio.export(
            out_io,
            format="opus",
            codec="libopus",
            parameters=["-b:a", "16k", "-application", "voip"]
        )
        return out_io.getvalue(), True
    except ImportError:
        logging.error("pydub/ffmpeg not installed")
        return _wrap_pcm_to_wav(audio_data), False
    except Exception as e:
        logging.error(f"Opus conversion failed: {e}")
        return _wrap_pcm_to_wav(audio_data), False

def convert_to_amr_simple(audio_data: bytes) -> bytes:
    """
    将音频转换为企业微信 AMR 格式
    """
    try:
        from pydub import AudioSegment
        import io, os, subprocess, tempfile, shutil

        # 1. 自动定位 ffmpeg
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            logging.error("未找到 ffmpeg，请确保已安装并加入环境变量")
            return None

        # 2. 读取音频并标准化 (8000Hz, Mono)
        audio = AudioSegment.from_file(io.BytesIO(audio_data))
        audio = audio.set_frame_rate(8000).set_channels(1)
        
        # 3. 创建临时文件
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio.export(tmp.name, format="wav")
            wav_name = tmp.name
        amr_name = wav_name.replace(".wav", ".amr")
        
        try:
            # 4. 执行转换并捕获错误输出
            cmd = [
                ffmpeg_path, "-y", "-i", wav_name, 
                "-ar", "8000", "-ab", "12.2k", "-ac", "1", 
                "-c:a", "libopencore_amrnb", amr_name
            ]
            process = subprocess.run(cmd, capture_output=True, text=True)
            
            if process.returncode != 0:
                # 【核心日志】这里会告诉你为什么 exit 8
                logging.error(f"FFmpeg 转换失败 (Code {process.returncode})")
                logging.error(f"FFmpeg 错误详情: {process.stderr}")
                return None
            
            with open(amr_name, "rb") as f:
                return f.read()
        finally:
            if os.path.exists(wav_name): os.remove(wav_name)
            if os.path.exists(amr_name): os.remove(amr_name)

    except Exception as e:
        logging.error(f"AMR 转换流程异常: {e}")
        return None


def _wrap_pcm_to_wav(pcm_data):
    try:
        import wave
        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24000)
            wav_file.writeframes(pcm_data)
        return wav_io.getvalue()
    except Exception:
        return pcm_data

# ----------------- 7. 配置读写 -----------------
# D-1/D-8: 单写者锁；D-3: 读败隔离+拒存；D-2: 主配置 conversations 护栏
_SETTINGS_LOCK = asyncio.Lock()
_COVS_LOCK = asyncio.Lock()
_COVS_DEGRADED = False


def _quarantine_raw(db_path, raw, tag):
    """坏数据落盘保全，绝不静默覆盖（D-3）。"""
    try:
        dst = "{}.{}-corrupt-{}.json".format(db_path, tag, int(time.time()))
        with open(dst, "w", encoding="utf-8") as f:
            f.write(raw if isinstance(raw, str) else str(raw))
        return dst
    except Exception:
        return None



def _migrate_legacy_keys(target_dict):
    """E-6：旧键→新键一次性迁移通道（load_settings 合并默认值后执行，幂等）。
    未来任何键改名/搬家都追加到此表，勿在读取点散写兼容。返回是否有修改。"""
    changed = False
    sql = target_dict.get("sqlSettings")
    if isinstance(sql, dict) and "dbPath" in sql:
        legacy = sql.pop("dbPath")
        if legacy and not str(sql.get("dbpath", "")).strip():
            sql["dbpath"] = legacy
        changed = True
    return changed


def deep_update(target: dict, updates: dict) -> dict:
    """B8(b03e7c0e): 深合并——嵌套 dict 递归更新，其余类型直接覆盖。
    ws save_settings 等部分载荷的写入方必须走它，防止整库覆盖丢键。"""
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = value
    return target


async def load_settings():
    await init_db()
    defaults = get_default_settings_sync().copy()
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute('SELECT data FROM settings WHERE id = 1') as cursor:
            row = await cursor.fetchone()
            if row:
                parse_ok = True
                try:
                    user_settings = json.loads(row[0])
                except Exception:
                    parse_ok = False
                    _quarantine_raw(DATABASE_PATH, row[0], "settings")
                    logging.getLogger(__name__).error("settings JSON 已损坏：已隔离备份并按默认值运行，禁止回写覆盖")
                    user_settings = {}
                
                # Merge logic
                has_changes = [False]
                def merge_defaults(default_dict, target_dict):
                    for key, value in default_dict.items():
                        if key not in target_dict:
                            target_dict[key] = value
                            has_changes[0] = True
                        elif isinstance(value, dict) and isinstance(target_dict.get(key), dict):
                            merge_defaults(value, target_dict[key])
                
                merge_defaults(defaults, user_settings)
                if _migrate_legacy_keys(user_settings):
                    has_changes[0] = True
                if has_changes[0] and parse_ok:
                    await save_settings(user_settings)  # B8(b03e7c0e): 火忘任务改 await，防与后续保存竞态
                if not parse_ok:
                    return defaults if not IS_DOCKER else {**defaults, "isdocker": True}
                return secret_box.decrypt_settings(user_settings)
            else:
                if IS_DOCKER:
                    defaults["isdocker"] = True
                await save_settings(defaults)
                return defaults

async def save_settings(settings):
    # D-2 护栏：会话不属于主配置；用副本 pop，不改动调用方内存对象
    if "conversations" in settings:
        settings = {k: v for k, v in settings.items() if k != "conversations"}
    # M4c/X-12: 敏感字段 DPAPI 封装后落盘（内存对象保持明文）
    data = json.dumps(secret_box.encrypt_settings(settings), ensure_ascii=False, indent=2)
    async with _SETTINGS_LOCK:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute('INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)', (data,))
            await db.commit()

async def _rescue_from_rows():
    """M4-B2'：blob 损坏时从行级影子表救援全部会话（每次 save_covs 确定性同步，
    blob 单点损坏时行表通常完好）。任一行坏 = 整体放弃（宁可空不可半坏）。"""
    async with aiosqlite.connect(COVS_PATH) as db:
        async with db.execute(
                "SELECT data FROM conversation_rows WHERE conv_id NOT LIKE 'bot:%' "
                "ORDER BY updated_at") as cur:
            raw_rows = await cur.fetchall()
    convs = []
    for (raw,) in raw_rows:
        conv = json.loads(raw)
        if not isinstance(conv, dict) or conv.get("id") is None:
            raise ValueError("shadow row shape invalid")
        convs.append(conv)
    return convs


async def load_covs():
    global _COVS_DEGRADED
    try:
        await init_covs_db()
        async with aiosqlite.connect(COVS_PATH) as db:
            async with db.execute('SELECT data FROM settings WHERE id = 1') as cursor:
                row = await cursor.fetchone()
        if not row:
            _COVS_DEGRADED = False
            return {"conversations": []}
        data = json.loads(row[0])
        _COVS_DEGRADED = False
        return data
    except Exception:
        # D-3：坏数据先隔离备份，再降级返回空；本次进程内 save_covs 拒写空库
        try:
            async with aiosqlite.connect(COVS_PATH) as db:
                async with db.execute('SELECT data FROM settings WHERE id = 1') as cursor:
                    raw_row = await cursor.fetchone()
            if raw_row:
                _quarantine_raw(COVS_PATH, raw_row[0], "covs")
        except Exception:
            pass
        # M4-B2'：行级影子救援——"对话消失"降级前的最后防线
        try:
            rescued = await _rescue_from_rows()
        except Exception:
            rescued = []
        if rescued:
            logging.getLogger(__name__).error(
                f"conversations 读取/解析失败：坏数据已隔离备份；"
                f"已从行级影子救援 {len(rescued)} 条会话（下次保存自动修复 blob）")
            _COVS_DEGRADED = False
            return {"conversations": rescued}
        logging.getLogger(__name__).error("conversations 读取/解析失败：已隔离备份；空库回写将被拒绝")
        _COVS_DEGRADED = True
        return {"conversations": []}

async def save_covs(settings):
    global _COVS_DEGRADED
    if _COVS_DEGRADED and not settings.get("conversations"):
        raise RuntimeError("covs save refused: 上次读取失败，拒绝用空会话库覆盖（坏数据已隔离备份）")
    await init_covs_db()
    data = json.dumps(settings, ensure_ascii=False, indent=2)
    async with _COVS_LOCK:
        async with aiosqlite.connect(COVS_PATH) as db:
            await db.execute('INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)', (data,))
            await db.commit()
            try:
                # M4b shadow double-write: blob stays source of truth
                await _sync_rows(db, settings.get("conversations") or [])
                await db.commit()
            except Exception:
                logging.getLogger(__name__).warning("conversation_rows shadow sync failed (blob unaffected)", exc_info=True)
    _COVS_DEGRADED = False

# ----------------- 7. bot 渠道会话（"手机"行级存储，bot: 前缀命名空间） -----------------
# 与主会话 blob 完全隔离：blob 不含 bot 会话，_sync_rows 也不碰 bot: 行。

BOT_CONV_PREFIX = "bot:"
_BOT_CONV_LOCK = asyncio.Lock()


async def save_bot_conv(conv_id, messages):
    if not str(conv_id).startswith(BOT_CONV_PREFIX):
        raise ValueError(f"bot 会话 id 必须以 {BOT_CONV_PREFIX} 开头: {conv_id!r}")
    await init_covs_db()
    async with _BOT_CONV_LOCK:
        async with aiosqlite.connect(COVS_PATH) as db:
            await db.execute(
                'INSERT OR REPLACE INTO conversation_rows (conv_id, data, updated_at) VALUES (?, ?, ?)',
                (str(conv_id), json.dumps(messages, ensure_ascii=False), time.time()))
            await db.commit()


async def load_bot_conv(conv_id):
    await init_covs_db()
    async with aiosqlite.connect(COVS_PATH) as db:
        async with db.execute('SELECT data FROM conversation_rows WHERE conv_id = ?',
                              (str(conv_id),)) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    try:
        msgs = json.loads(row[0])
        return msgs if isinstance(msgs, list) else None
    except Exception:
        return None


async def list_bot_convs():
    """[{conv_id, updated_at, count, last_text}] newest first."""
    await init_covs_db()
    out = []
    async with aiosqlite.connect(COVS_PATH) as db:
        async with db.execute(
                "SELECT conv_id, data, updated_at FROM conversation_rows "
                "WHERE conv_id LIKE 'bot:%' ORDER BY updated_at DESC") as cur:
            async for conv_id, data, updated_at in cur:
                try:
                    msgs = json.loads(data)
                except Exception:
                    msgs = []
                if not isinstance(msgs, list):
                    msgs = []
                out.append({"conv_id": conv_id, "updated_at": updated_at,
                            "count": len(msgs), "last_text": _last_text_preview(msgs),
                            "archived": "::" in conv_id})
    return out


async def delete_bot_conv(conv_id):
    conv_id = str(conv_id)
    if not conv_id.startswith(BOT_CONV_PREFIX):
        raise ValueError(f"bot 会话 id 必须以 {BOT_CONV_PREFIX} 开头: {conv_id!r}")
    await init_covs_db()
    async with _BOT_CONV_LOCK:
        async with aiosqlite.connect(COVS_PATH) as db:
            await db.execute('DELETE FROM conversation_rows WHERE conv_id = ?', (conv_id,))
            await db.commit()


async def archive_bot_conv(conv_id):
    """Move the active row's content into a timestamped archive row and
    clear the active one, so the next inbound message starts fresh.
    Returns the new archive conv_id, or None when nothing to archive."""
    conv_id = str(conv_id)
    if not conv_id.startswith(BOT_CONV_PREFIX) or "::" in conv_id:
        raise ValueError(f"需要活动 bot 会话 id（{BOT_CONV_PREFIX} 前缀且不含 ::）: {conv_id!r}")
    await init_covs_db()
    archive_id = f"{conv_id}::{int(time.time() * 1000)}"
    async with _BOT_CONV_LOCK:
        async with aiosqlite.connect(COVS_PATH) as db:
            async with db.execute(
                    'SELECT data, updated_at FROM conversation_rows WHERE conv_id = ?',
                    (conv_id,)) as cur:
                row = await cur.fetchone()
            msgs = []
            if row:
                try:
                    msgs = json.loads(row[0])
                except Exception:
                    msgs = []
            if not isinstance(msgs, list) or not msgs:
                return None
            now = time.time()
            await db.execute(
                'INSERT OR REPLACE INTO conversation_rows (conv_id, data, updated_at) VALUES (?, ?, ?)',
                (archive_id, json.dumps(msgs, ensure_ascii=False), row[1] if row else now))
            await db.execute(
                'INSERT OR REPLACE INTO conversation_rows (conv_id, data, updated_at) VALUES (?, ?, ?)',
                (conv_id, "[]", now))
            await db.commit()
    return archive_id


async def swap_bot_conv(conv_id_a, conv_id_b):
    """Atomically exchange two bot rows' contents (activate an archive while
    demoting the current active conversation into it)."""
    a, b = str(conv_id_a), str(conv_id_b)
    for cid in (a, b):
        if not cid.startswith(BOT_CONV_PREFIX):
            raise ValueError(f"bot 会话 id 必须以 {BOT_CONV_PREFIX} 开头: {cid!r}")
    await init_covs_db()
    async with _BOT_CONV_LOCK:
        async with aiosqlite.connect(COVS_PATH) as db:
            rows = {}
            for cid in (a, b):
                async with db.execute(
                        'SELECT data, updated_at FROM conversation_rows WHERE conv_id = ?',
                        (cid,)) as cur:
                    rows[cid] = await cur.fetchone()
            payload = {}
            for cid in (a, b):
                if rows[cid]:
                    payload[cid] = (rows[cid][0], rows[cid][1])
                else:
                    payload[cid] = ("[]", time.time())
            await db.execute(
                'INSERT OR REPLACE INTO conversation_rows (conv_id, data, updated_at) VALUES (?, ?, ?)',
                (a, payload[b][0], payload[b][1]))
            await db.execute(
                'INSERT OR REPLACE INTO conversation_rows (conv_id, data, updated_at) VALUES (?, ?, ?)',
                (b, payload[a][0], payload[a][1]))
            await db.commit()


def _msg_text(msg):
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                return str(part["text"])
    return ""


def _last_text_preview(msgs):
    for msg in reversed(msgs):
        if isinstance(msg, dict) and _msg_text(msg).strip():
            return _msg_text(msg).strip()[:120]
    return ""


def redact_messages_for_view(messages):
    """API payload safety: data-URI images -> placeholder, long strings -> cut."""
    def red_str(s):
        if s.startswith("data:") and len(s) > 64:
            return f"[data-uri {len(s)} bytes]"
        if len(s) > 4000:
            return s[:1800] + "\n…\n" + s[-600:]
        return s

    def red_part(part):
        if not isinstance(part, dict):
            return part
        part = dict(part)
        if part.get("type") == "image_url" and isinstance(part.get("image_url"), dict):
            part["image_url"] = {"url": red_str(str(part["image_url"].get("url", "")))}
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            part["text"] = red_str(part["text"])
        return part

    out = []
    for msg in messages if isinstance(messages, list) else []:
        if not isinstance(msg, dict):
            continue
        msg = dict(msg)
        if isinstance(msg.get("content"), str):
            msg["content"] = red_str(msg["content"])
        elif isinstance(msg.get("content"), list):
            msg["content"] = [red_part(p) for p in msg["content"]]
        out.append(msg)
    return out
