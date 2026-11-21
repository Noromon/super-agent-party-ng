# -*- coding: utf-8 -*-
"""S266 一次性抢救：把 .bak-s205 手工备份中被 500 上限挤掉的旧日记合并回主本。

用法（不带 SAP_DATA_DIR 覆盖，指向真实 Roaming 数据目录）：
    python scripts/rescue_diary_s266.py            # 干跑：只报告可救条数
    python scripts/rescue_diary_s266.py --apply    # 合并落盘（先自动备份现状）

合并走 diary_system.save_diary_data：按当前 diarySettings 策略落盘
（默认 500+自动归档 → 救回的旧条目自然进归档区，不占主本名额）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
from datetime import datetime  # noqa: E402

import py.diary_system as ds  # noqa: E402

BOOK = "7fb41746-d8b9-4ac9-8af1-f423661c4706"
BAK = Path(ds.DIARY_DIR) / f"{BOOK}.json.bak-s205-20261109-103950"


async def main(apply_: bool):
    cur = await ds.load_diary_data(BOOK)
    with open(BAK, encoding="utf-8") as f:
        old = json.load(f)
    old_entries = old.get("entries", []) if isinstance(old, dict) else []
    cur_ids = {e.get("id") for e in cur.get("entries", []) if isinstance(e, dict)}
    rescue = [e for e in old_entries if isinstance(e, dict) and e.get("id") not in cur_ids]
    print(f"主本现有 {len(cur.get('entries', []))} 条；备份内 {len(old_entries)} 条；"
          f"可救回 {len(rescue)} 条")
    if not apply_:
        print("干跑模式：未落盘。加 --apply 执行合并。")
        return
    if not rescue:
        print("无可救回条目，结束。")
        return
    snap = Path(ds.DIARY_DIR) / f"{BOOK}.json.bak-s266-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(ds._book_file(BOOK), snap)
    print(f"现状已备份: {snap.name}")
    merged = ds.merge_entries(cur.get("entries", []), rescue)
    cur["entries"] = merged
    await ds.save_diary_data(cur, BOOK)
    limit, archive_on = await ds.get_diary_policy()
    after = await ds.load_diary_data(BOOK)
    arch = await ds.load_archive(BOOK)
    print(f"合并后按策略(上限={limit or '无上限'}, 归档={'开' if archive_on else '关'})落盘："
          f"主本 {len(after.get('entries', []))} 条，归档 {len(arch)} 条")


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
