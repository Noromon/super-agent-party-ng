# -*- coding: utf-8 -*-
"""S133：重建 mem0 faiss 索引的 idx2id 映射（int 位置 -> uuid）。

背景：mem0 faiss provider 的 delete 只删 docstore/idx2id 不删 faiss 向量，
且 insert 用 starting_idx=len(idx2id) 分配 int id。一旦映射丢失/漂移，
后续写入互相覆盖映射，检索时大量命中被 _parse_output 静默丢弃——
表现为日记/思考轮长期记忆召回恒为同一条（其余记忆隐形）。

本工具按「文本重嵌入 -> faiss 向量最近邻」恢复 int 位置与 uuid 的对应：
对 docstore 每条记忆文本调用该卡配置的 embedding 服务重新编码，
与索引中全部位置向量做余弦匹配（一对一贪心、cos>=tau 才建映射，
宁可少召回不可错归因），重建 pkl。默认 dry-run，--apply 才落盘
（落盘前自动再备份一份）。

用法（后端须停止，避免旧内存态回写覆盖修复结果）：
    .venv\\Scripts\\python.exe scripts\\repair_memory_idx2id.py --card 7fb4 --apply
    .venv\\Scripts\\python.exe scripts\\repair_memory_idx2id.py --card all
"""
import argparse
import json
import os
import pickle
import shutil
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py.memory_store import idx2id_health, pad_idx2id, rebuild_idx2id  # noqa: E402


def _load_card_cfg(card_prefix: str):
    from py.get_setting import DATABASE_PATH
    con = sqlite3.connect(f"file:{DATABASE_PATH.replace(os.sep, '/')}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT data FROM settings WHERE id = 1").fetchone()
    finally:
        con.close()
    if not row:
        raise SystemExit("settings 表为空")
    settings = json.loads(row[0])
    mems = settings.get("memories") or []
    hits = [m for m in mems if str(m.get("id", "")).startswith(card_prefix)]
    if len(hits) != 1:
        raise SystemExit(f"卡前缀 {card_prefix!r} 命中 {len(hits)} 张（需唯一）")
    return hits[0]


def _list_cards():
    from py.get_setting import DATABASE_PATH
    con = sqlite3.connect(f"file:{DATABASE_PATH.replace(os.sep, '/')}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT data FROM settings WHERE id = 1").fetchone()
    finally:
        con.close()
    return [str(m.get("id")) for m in (json.loads(row[0]).get("memories") or []) if m.get("id")]


def _local_sap_token(base_url: str) -> str:
    """S133：内嵌 /minilm 的后端受 session-token 中间件保护，headless 客户端
    走持久化机器令牌（py/auth.ensure_machine_token 的 X-SAP-Token 通道）。"""
    if "127.0.0.1" not in base_url and "localhost" not in base_url:
        return ""
    tok = os.environ.get("SAP_MACHINE_TOKEN") or ""
    if not tok:
        from py.get_setting import USER_DATA_DIR
        p = os.path.join(USER_DATA_DIR, ".machine_token")
        if os.path.exists(p):
            tok = open(p, encoding="utf-8").read().strip()
    return tok


def _embed_texts(cfg, texts, batch=32):
    from openai import OpenAI
    tok = _local_sap_token(cfg.get("base_url") or "")
    client = OpenAI(base_url=cfg.get("base_url"), api_key=cfg.get("api_key") or "local",
                    default_headers=({"X-SAP-Token": tok} if tok else None))
    model = cfg["model"]
    out = []
    for start in range(0, len(texts), batch):
        chunk = texts[start:start + batch]
        resp = client.embeddings.create(model=model, input=chunk)
        out.extend([d.embedding for d in resp.data])
        if (start // batch) % 20 == 0:
            print(f"  embed {start + len(chunk)}/{len(texts)}")
    return out


def _reconstruct_vectors(index):
    import numpy as np
    n = index.ntotal
    mat = np.empty((n, index.d), dtype=np.float32)
    for i in range(n):
        mat[i] = index.reconstruct(i)
    return mat


def repair_card(card_id: str, apply: bool, tau: float, batch: int):
    from py.memory_store import get_faiss_path, get_pkl_path
    import faiss

    pkl_path = get_pkl_path(card_id)
    faiss_path = get_faiss_path(card_id)
    if not (os.path.exists(pkl_path) and os.path.exists(faiss_path)):
        print(f"[{card_id[:8]}] 缺文件，跳过")
        return

    with open(pkl_path, "rb") as f:
        docstore, idx2id = pickle.load(f)
    index = faiss.read_index(faiss_path)
    health = idx2id_health(index.ntotal, len(docstore), len(idx2id))
    print(f"[{card_id[:8]}] 修复前: {health}")

    cfg = _load_card_cfg(card_id)
    print(f"[{card_id[:8]}] embed 模型: {cfg.get('model')} @ {cfg.get('base_url')} (dims={cfg.get('embedding_dims')})")

    keys = list(docstore.keys())
    texts = [(docstore[k].get("data") or "") for k in keys]
    print(f"[{card_id[:8]}] 重嵌入 {len(texts)} 条文本 ...")
    t0 = time.time()
    qvecs = _embed_texts(cfg, texts, batch=batch)
    dims = len(qvecs[0]) if qvecs else 0
    if dims and dims != index.d:
        raise SystemExit(f"[{card_id[:8]}] 维度不匹配: embed={dims} index={index.d}（勿修，先查卡配置）")
    print(f"[{card_id[:8]}] 嵌入完成 {time.time() - t0:.0f}s")

    ivec = _reconstruct_vectors(index)
    mapping, scores = rebuild_idx2id(ivec, keys, qvecs, tau=tau)
    matched = len(mapping)
    scores_arr = list(scores.values())
    avg = sum(scores_arr) / len(scores_arr) if scores_arr else 0.0
    worst = min(scores_arr) if scores_arr else 0.0
    kept_old = sum(1 for p, u in mapping.items() if idx2id.get(p) == u)
    print(f"[{card_id[:8]}] 匹配: {matched}/{len(keys)} uuid 建映射（平均 cos={avg:.4f} 最低={worst:.4f}），"
          f"与旧 idx2id 一致 {kept_old} 条")
    lost = [k for k in keys if k not in scores][:8]
    if lost:
        print(f"[{card_id[:8]}] 未匹配示例: {lost}")

    padded = pad_idx2id(dict(mapping), index.ntotal)  # 预览补齐数（不改 mapping）
    print(f"[{card_id[:8]}] 将补齐占位墓碑 {padded} 条（len(idx2id)==ntotal，恢复 id 计数器不变式）")
    if not apply:
        print(f"[{card_id[:8]}] dry-run 结束（加 --apply 落盘）")
        return
    if matched < 0.8 * len(keys):
        raise SystemExit(f"[{card_id[:8]}] 匹配率过低（{matched}/{len(keys)}），疑似嵌入服务异常，拒绝落盘")
    pad_idx2id(mapping, index.ntotal)

    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for src in (pkl_path, faiss_path):
        shutil.copy2(src, f"{src}.bak-pre-repair-{ts}")
    tmp = pkl_path + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump((docstore, mapping), f)
    os.replace(tmp, pkl_path)
    print(f"[{card_id[:8]}] 已写回 pkl（备份 *.bak-pre-repair-{ts}）。映射 {len(mapping)} 条")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", required=True, help="卡 id 前缀或 all")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--tau", type=float, default=0.995)
    ap.add_argument("--batch", type=int, default=32)
    args = ap.parse_args()

    cards = _list_cards() if args.card == "all" else None
    if cards is None:
        cards = [(_load_card_cfg(args.card)["id"])]
    for cid in cards:
        repair_card(str(cid), args.apply, args.tau, args.batch)


if __name__ == "__main__":
    main()
