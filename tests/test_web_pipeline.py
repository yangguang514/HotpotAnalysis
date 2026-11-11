# coding=utf-8
"""
TrendRadar Web 管线离线测试（不依赖外网）

用 mock 抓取器验证：
1. run_crawl：跨次抓取合并语义（count 累加、first/last_time、rank_timeline）
2. build_report：多日合并 + 词表过滤 + 分组 + 排序
3. evaluate_schedule：监控时间槽位判定（到点执行/未到点跳过/补抓/去重/星期过滤）
4. 配置往返：结构化词表序列化后再解析与原文件一致
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from trendradar.core.frequency import load_frequency_words, matches_word_groups  # noqa: E402
from trendradar.web.pipeline import (  # noqa: E402
    _split_word_blocks,
    build_report,
    evaluate_schedule,
    keywords_to_text,
    run_crawl,
    seed_config_from_files,
)
from trendradar.web.stores import ConfigStore, DataStore  # noqa: E402

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


# ── 准备：独立的数据目录，避免污染开发数据 ──
TEST_DIR = Path(__file__).resolve().parent / "web_data_test"
import shutil  # noqa: E402

if TEST_DIR.exists():
    shutil.rmtree(TEST_DIR)

import os  # noqa: E402

os.environ["WEB_DATA_DIR"] = str(TEST_DIR)

config_store = ConfigStore()
data_store = DataStore()

# 种子化（读 config/config.yaml + config/frequency_words.txt）
config = seed_config_from_files(config_store)
check("种子化：19 个动物词组", len(config["keywords"]["groups"]) == 19)
check("种子化：11 个平台", len(config["platforms"]) == 11)
check("种子化：weekly/7天", config["report"]["mode"] == "weekly" and config["report"]["range_days"] == 7)

# ── 1. 词表序列化往返 ──
print("\n── 1. 词表序列化往返 ──")
text = keywords_to_text(config["keywords"])
g_web, _, gf_web = load_frequency_words.__wrapped__ if False else (None, None, None)
from trendradar.core.frequency import parse_frequency_words  # noqa: E402

g_web, f_web, gf_web = parse_frequency_words(text)
g_file, f_file, gf_file = load_frequency_words("config/frequency_words.txt")
check("序列化后再解析：词组数一致", len(g_web) == len(g_file), f"({len(g_web)} vs {len(g_file)})")
check(
    "序列化后再解析：词组名一致",
    [g["display_name"] for g in g_web] == [g["display_name"] for g in g_file],
)
check("序列化后再解析：全局过滤一致", len(gf_web) == len(gf_file))
check(
    "匹配语义一致",
    matches_word_groups("大熊猫福宝回国", g_web, f_web, gf_web)
    == matches_word_groups("大熊猫福宝回国", g_file, f_file, gf_file),
)

# ── 2. 抓取合并语义（mock 网络） ──
print("\n── 2. 抓取合并语义 ──")
BATCH_1 = {
    "weibo": [
        {"title": "大熊猫福宝回国引围观", "url": "https://weibo.com/1", "mobileUrl": ""},
        {"title": "某明星恋情曝光", "url": "https://weibo.com/2", "mobileUrl": ""},
        {"title": "东北虎豹国家公园种群扩大", "url": "https://weibo.com/3", "mobileUrl": ""},
    ],
    "zhihu": [
        {"title": "如何评价大熊猫保护成效", "url": "https://zhihu.com/1", "mobileUrl": ""},
        {"title": "程序员脱发怎么办", "url": "https://zhihu.com/2", "mobileUrl": ""},
    ],
}
BATCH_2 = {
    "weibo": [
        {"title": "大熊猫福宝回国引围观", "url": "https://weibo.com/1", "mobileUrl": ""},  # 重复
        {"title": "长江江豚数量首次回升", "url": "https://weibo.com/4", "mobileUrl": ""},  # 新增
    ],
    "zhihu": [
        {"title": "如何评价大熊猫保护成效", "url": "https://zhihu.com/1", "mobileUrl": ""},  # 重复
    ],
}


def fake_fetch(self, pid, max_retries=2, min_retry_wait=3, max_retry_wait=5):
    batch = BATCH_1 if not hasattr(self, "_second") else BATCH_2
    if pid in batch:
        return json.dumps({"status": "success", "items": batch[pid]}), pid, pid
    return None, pid, pid


class FakeDatetime:
    """控制 run_crawl 内的 get_configured_time，让两次抓取落在同一天不同时刻"""


with mock.patch("trendradar.crawler.fetcher.DataFetcher.fetch_data", fake_fetch):
    r1 = run_crawl(config, config_store, data_store)
    check("第一次抓取：ok", r1["ok"] is True)
    check("第一次抓取：4 个平台成功", r1["platforms_success"] == 2, str(r1))
    check("第一次抓取：5 条新标题", r1["new_titles"] == 5, str(r1))

    # 第二次抓取（同日）
    fake_fetch_second = lambda self, pid, **kw: fake_fetch.__call__(self, pid, **kw)  # noqa: E731
    with mock.patch("trendradar.crawler.fetcher.DataFetcher.fetch_data", fake_fetch_second):
        # 让第二次抓到的数据切到 BATCH_2
        class ToggledFetcher:
            pass

        def fake_fetch2(self, pid, max_retries=2, min_retry_wait=3, max_retry_wait=5):
            if pid in BATCH_2:
                return json.dumps({"status": "success", "items": BATCH_2[pid]}), pid, pid
            return None, pid, pid

        with mock.patch("trendradar.crawler.fetcher.DataFetcher.fetch_data", fake_fetch2):
            r2 = run_crawl(config, config_store, data_store)
    check("第二次抓取：2 条新标题（江豚+无）", r2["new_titles"] == 1, str(r2))

# 验证合并后的当日数据
today = datetime.now().strftime("%Y-%m-%d")
day = data_store.get_day(today)
panda = day["weibo"]["大熊猫福宝回国引围观"]
check("重复标题 count 累加为 2", panda["count"] == 2, str(panda["count"]))
check("重复标题 ranks 跨次拼接", panda["ranks"] == [1, 1], str(panda["ranks"]))
check("重复标题 rank_timeline 有 2 条", len(panda["rank_timeline"]) == 2)
check("新标题 count 为 1", day["weibo"]["长江江豚数量首次回升"]["count"] == 1)
check("first_time <= last_time", panda["first_time"] <= panda["last_time"])
meta = data_store.get_meta()
check("元信息：抓取次数 2", meta.get("crawl_count") == 2)
check("元信息：上次抓取日期为今天", meta.get("last_crawl_date") == today)

# ── 3. 报告构建 ──
print("\n── 3. 报告构建 ──")
report = build_report(config, data_store)
group_names = [g["name"] for g in report["groups"]]
check("报告：命中 4 条动物生态新闻", report["total_matched"] == 4, str(report["total_matched"]))
check("报告：包含大熊猫组", "大熊猫" in group_names, str(group_names))
check("报告：包含老虎组", "老虎" in group_names)
check("报告：包含鲸豚组", "鲸豚" in group_names)
check("报告：不含科技类新闻", "程序员脱发怎么办" not in json.dumps(report, ensure_ascii=False))
check("报告：不含娱乐类新闻", "某明星恋情曝光" not in json.dumps(report, ensure_ascii=False))
panda_group = next(g for g in report["groups"] if g["name"] == "大熊猫")
check("报告：大熊猫组 2 条（微博+知乎）", panda_group["count"] == 2, str(panda_group["count"]))
check("报告：新闻带 count 字段", all("count" in n for n in panda_group["news"]))
check("报告：range 正确", report["range"]["days"] == 7)

# max_news_per_keyword 裁剪
config_max = json.loads(json.dumps(config))
config_max["report"]["max_news_per_keyword"] = 1
report_max = build_report(config_max, data_store)
panda_max = next(g for g in report_max["groups"] if g["name"] == "大熊猫")
check("报告：max_news_per_keyword=1 裁剪生效", len(panda_max["news"]) == 1)

# ── 4. 定时槽位判定 ──
print("\n── 4. 定时槽位判定 ──")
sched_config = json.loads(json.dumps(config))
sched_config["schedule"] = {
    "enabled": True,
    "weekdays": [1, 2, 3, 4, 5, 6, 7],
    "times": ["08:00", "20:00"],
    "timezone": "Asia/Shanghai",
}

# 4.1 关闭 → 不执行
off = json.loads(json.dumps(sched_config))
off["schedule"]["enabled"] = False
d = evaluate_schedule(off, data_store, now=datetime(2026, 11, 11, 9, 0))
check("自动监控关闭 → 不执行", d["should_run"] is False)

# 4.2 到点（09:00 处于 08:00 后 1 小时内）→ 执行
d = evaluate_schedule(sched_config, data_store, now=datetime(2026, 11, 11, 9, 0))
check("09:00 处于 08:00 槽位窗口 → 执行", d["should_run"] is True and d["slot"] == "08:00")

# 4.3 同槽位再入 → 去重跳过
d = evaluate_schedule(sched_config, data_store, now=datetime(2026, 11, 11, 9, 30))
check("同一槽位重复触发 → 跳过", d["should_run"] is False)

# 4.4 未到点 → 不执行
d = evaluate_schedule(sched_config, data_store, now=datetime(2026, 11, 11, 7, 0))
check("07:00 未到点 → 不执行", d["should_run"] is False)
check("07:00 给出下一时刻", d.get("next_slot") is not None)

# 4.5 晚于窗口且今日已抓过 → 不执行（无补抓）
d = evaluate_schedule(sched_config, data_store, now=datetime(2026, 11, 11, 15, 0))
check("15:00 超出窗口且今日已抓过 → 不执行", d["should_run"] is False)

# 4.6 星期过滤：2026-11-14 是周六，若只允许周一~周五 → 不执行
weekday_cfg = json.loads(json.dumps(sched_config))
weekday_cfg["schedule"]["weekdays"] = [1, 2, 3, 4, 5]
d = evaluate_schedule(weekday_cfg, data_store, now=datetime(2026, 11, 14, 9, 0))
check("周六不在监控星期 → 不执行", d["should_run"] is False and "星期" in d["reason"])

# 4.7 补抓：全新一天（数据里没有 11-12），时间已过 08:00，今日无抓取记录
d = evaluate_schedule(sched_config, data_store, now=datetime(2026, 11, 12, 9, 30))
check("新一天已过槽位但未抓过 → 补抓", d["should_run"] is True and d["slot"] == "catchup")

# 4.8 补抓去重
d = evaluate_schedule(sched_config, data_store, now=datetime(2026, 11, 12, 9, 40))
check("补抓槽位去重", d["should_run"] is False)

# ── 5. KV 后端键位设计（不实际联网，仅验证键名生成） ──
print("\n── 5. 存储键位 ──")
check("日键", data_store.day_key("2026-11-11") == "trendradar:day:2026-11-11")
check("槽位键", data_store.slot_key("2026-11-11", "08-00") == "trendradar:slot:2026-11-11:08-00")
_slot_path = __import__("trendradar.web.stores", fromlist=["FileBackend"]).FileBackend(str(TEST_DIR))._path(
    data_store.slot_key("2026-11-11", "catchup")
)
check("文件后端槽位路径不含冒号（Windows 兼容）", ":" not in _slot_path.name, str(_slot_path))

# ── 清理 ──
shutil.rmtree(TEST_DIR, ignore_errors=True)
print(f"\n══════════════════════════════════")
print(f"测试结果: {PASS} 通过, {FAIL} 失败")
sys.exit(1 if FAIL else 0)
