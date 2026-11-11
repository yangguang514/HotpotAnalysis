# coding=utf-8
"""
Web 端业务管线

职责：
1. 配置种子化：首次运行时从本地 config/config.yaml + config/frequency_words.txt
   生成 Web 端配置（本地开发的配置无缝迁移到线上）
2. 词表序列化：结构化词组 <-> frequency_words.txt 文本（与 CLI 版完全同构）
3. 抓取管线：并行抓取平台 → 合并进当日数据（跨次累加）
4. 报告管线：按天数范围合并多日数据 → 词表过滤 → 分组统计
5. 定时判断：根据「监控时间」配置计算当前是否有到期的抓取槽位

本模块不依赖任何 Web 框架，可被 Serverless 函数、本地 CLI 直接调用。
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from trendradar.core.frequency import matches_word_groups, parse_frequency_words
from trendradar.crawler.fetcher import DataFetcher
from trendradar.utils.time import get_configured_time
from trendradar.web.catalog import (
    DEFAULT_PLATFORM_IDS,
    get_platform_domain,
    get_platform_name,
)
from trendradar.web.stores import ConfigStore, DataStore

# 抓取并发数（Vercel 函数内 I/O 密集型，6 并发兼顾速度与对方服务压力）
CRAWL_CONCURRENCY = 6
# 单轮抓取总体时限（秒）。Vercel 函数上限 300s（Fluid compute Hobby 默认值），
# 留出余量用于写库与响应；超时后未完成的平台会被取消并记为失败。
CRAWL_DEADLINE_SECONDS = 200


# ══════════════════════════════════════════════════════════════════════
# 1. 配置种子化
# ══════════════════════════════════════════════════════════════════════

def _split_word_blocks(content: str) -> Tuple[List[List[str]], List[str]]:
    """
    把 frequency_words.txt 内容拆成 (词组块列表, 全局过滤词列表)

    每个词组块保留原始文本行（含注释），块与块之间以空行分隔。
    """
    blocks = [b.strip() for b in content.split("\n\n") if b.strip()]
    groups: List[List[str]] = []
    global_filters: List[str] = []
    section = "WORD_GROUPS"

    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        # 去掉纯注释行（保留块内注释则跳过整块注释的场景）
        meaningful = [ln for ln in lines if not ln.startswith("#")]
        if not meaningful:
            continue
        if meaningful[0].startswith("[") and meaningful[0].endswith("]"):
            name = meaningful[0][1:-1].upper()
            if name in ("GLOBAL_FILTER", "WORD_GROUPS"):
                section = name
                lines = meaningful[1:]
                if not lines:
                    continue
        if section == "GLOBAL_FILTER":
            for ln in lines:
                if not ln.startswith("#"):
                    global_filters.append(ln)
        else:
            groups.append(lines)
    return groups, global_filters


def _derive_group_name(lines: List[str]) -> str:
    """从词组块推导显示名（优先组别名 > 行别名 > 首个有效行）"""
    for ln in lines:
        if ln.startswith("#"):
            continue
        if ln.startswith("[") and ln.endswith("]"):
            return ln[1:-1].strip()
        if "=>" in ln:
            right = re.split(r"\s*=>\s*", ln, 1)[1].strip()
            if right:
                return right
        return ln.strip("+/!@ ")
    return "未命名词组"


def seed_config_from_files(
    config_store: ConfigStore,
    config_dir: str = "config",
) -> Dict:
    """
    首次运行时用本地配置文件生成 Web 配置；已有配置则原样返回。

    返回种子化后的完整配置。
    """
    existing = config_store.get()
    if existing is not None:
        # 已种子化：补齐缺失字段后直接返回（不再触发第二次读取）
        from trendradar.web.stores import _merge_defaults
        return _merge_defaults(existing)

    config_path = Path(config_dir) / "config.yaml"
    words_path = Path(config_dir) / "frequency_words.txt"

    seed = {
        "version": 1,
        "keywords": {"groups": [], "global_filters": []},
        "platforms": [],
        "api_url": "",
        "schedule": {
            "enabled": False,
            "weekdays": [1, 2, 3, 4, 5, 6, 7],
            "times": ["08:00", "12:00", "20:00"],
            "timezone": "Asia/Shanghai",
        },
        "report": {
            "mode": "weekly",
            "range_days": 7,
            "sort_by_position_first": False,
            "max_news_per_keyword": 0,
            "rank_threshold": 5,
        },
    }

    # ── config.yaml ──
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            seed["schedule"]["timezone"] = data.get("app", {}).get("timezone", "Asia/Shanghai")
            seed["api_url"] = data.get("platforms", {}).get("api_url", "") or ""
            sources = data.get("platforms", {}).get("sources", []) or []
            enabled_ids = {p.get("id") for p in sources if p.get("enabled", True)}
            if enabled_ids:
                for pid in DEFAULT_PLATFORM_IDS:
                    if pid in enabled_ids:
                        seed["platforms"].append({
                            "id": pid,
                            "name": get_platform_name(pid),
                            "domain": get_platform_domain(pid),
                        })
            report = data.get("report", {}) or {}
            seed["report"].update({
                "mode": report.get("mode", "weekly"),
                "range_days": int(report.get("range_days", 7) or 7),
                "sort_by_position_first": bool(report.get("sort_by_position_first", False)),
                "max_news_per_keyword": int(report.get("max_news_per_keyword", 0) or 0),
                "rank_threshold": int(report.get("rank_threshold", 5) or 5),
            })
        except Exception as e:
            print(f"[Web种子化] 解析 config.yaml 失败，使用默认值: {e}")

    if not seed["platforms"]:
        seed["platforms"] = [
            {"id": pid, "name": get_platform_name(pid), "domain": get_platform_domain(pid)}
            for pid in DEFAULT_PLATFORM_IDS
        ]

    # ── frequency_words.txt ──
    if words_path.exists():
        try:
            content = words_path.read_text(encoding="utf-8")
            blocks, global_filters = _split_word_blocks(content)
            seed["keywords"] = {
                "groups": [
                    {"display_name": _derive_group_name(lines), "lines": lines}
                    for lines in blocks
                ],
                "global_filters": global_filters,
            }
        except Exception as e:
            print(f"[Web种子化] 解析 frequency_words.txt 失败: {e}")

    config_store.save(seed)
    print(f"[Web种子化] 已从 {config_dir} 生成初始配置并写入存储")
    return seed


# ══════════════════════════════════════════════════════════════════════
# 2. 词表序列化（结构化 <-> 文本）
# ══════════════════════════════════════════════════════════════════════

def keywords_to_text(keywords: Dict) -> str:
    """结构化词表 → frequency_words.txt 文本"""
    parts: List[str] = []
    global_filters = [g for g in keywords.get("global_filters", []) if g and g.strip()]
    groups = keywords.get("groups", [])
    if global_filters:
        parts.append("[GLOBAL_FILTER]\n" + "\n".join(g.strip() for g in global_filters))
    if groups:
        # 必须显式输出 [WORD_GROUPS] 标记，否则解析器会把后续词组
        # 继续当作 GLOBAL_FILTER 区的内容（section 状态会延续）
        parts.append("[WORD_GROUPS]")
    for group in groups:
        lines = [ln for ln in group.get("lines", []) if ln and ln.strip()]
        if not lines:
            continue
        parts.append("\n".join(ln.rstrip() for ln in lines))
    return "\n\n".join(parts) + "\n"


def validate_keywords(keywords: Dict) -> List[str]:
    """校验词表可否被解析，返回错误列表（空列表 = 通过）"""
    try:
        text = keywords_to_text(keywords)
    except Exception as e:
        return [f"词表序列化失败: {e}"]
    try:
        groups, _filters, _global = parse_frequency_words(text)
    except Exception as e:
        return [f"词表解析失败: {e}"]
    if not keywords.get("groups") and not keywords.get("global_filters"):
        return ["词表为空：至少需要一个词组或全局过滤词"]
    errors = []
    for i, group in enumerate(keywords.get("groups", [])):
        lines = [ln for ln in group.get("lines", []) if ln and ln.strip()]
        if not lines:
            errors.append(f"第 {i + 1} 个词组没有任何内容")
        elif not any(not ln.startswith(("#", "!", "+", "@")) for ln in lines):
            errors.append(f"第 {i + 1} 个词组「{group.get('display_name', '')}」只有排除/必须词，没有普通词")
    if not groups and not errors:
        errors.append("词表解析结果为空，请检查语法")
    return errors


# ══════════════════════════════════════════════════════════════════════
# 3. 抓取管线
# ══════════════════════════════════════════════════════════════════════

def _fetch_one(fetcher: DataFetcher, platform: Dict) -> Tuple[str, Optional[str], str]:
    """抓取单个平台，返回 (platform_id, 响应文本|None, 平台名)

    Serverless 环境对单次调用总时长敏感，重试参数比 CLI 更保守：
    最坏情况每平台约 10s(超时) + 1s + 10s ≈ 21s。
    """
    pid = platform["id"]
    try:
        response, _, _ = fetcher.fetch_data(
            pid, max_retries=1, min_retry_wait=1, max_retry_wait=2
        )
        return pid, response, platform.get("name", pid)
    except Exception as e:
        print(f"[Web抓取] {pid} 异常: {e}")
        return pid, None, platform.get("name", pid)


def merge_crawl_results(
    day_data: Dict,
    platform_id: str,
    items: List[Dict],
    now_iso: str,
) -> int:
    """
    把一次抓取结果合并进当日数据。

    同一标题再次出现：count+1、ranks 追加、rank_timeline 追加、last_time 更新；
    新标题：创建记录。返回新增标题数。
    """
    platform_data = day_data.setdefault(platform_id, {})
    new_titles = 0
    for index, item in enumerate(items, 1):
        title = item.get("title")
        if title is None or isinstance(title, float) or not str(title).strip():
            continue
        title = str(title).strip()
        url = item.get("url", "") or ""
        mobile_url = item.get("mobileUrl", "") or ""

        if title in platform_data:
            record = platform_data[title]
            record["count"] = record.get("count", 1) + 1
            record["ranks"].append(index)
            record["last_time"] = now_iso
            timeline = record.setdefault("rank_timeline", [])
            timeline.append([now_iso, index])
            if url and not record.get("url"):
                record["url"] = url
        else:
            platform_data[title] = {
                "ranks": [index],
                "url": url,
                "mobileUrl": mobile_url,
                "first_time": now_iso,
                "last_time": now_iso,
                "count": 1,
                "rank_timeline": [[now_iso, index]],
            }
            new_titles += 1
    return new_titles


def run_crawl(
    config: Dict,
    config_store: ConfigStore,
    data_store: DataStore,
    timezone: Optional[str] = None,
) -> Dict:
    """
    执行一轮抓取：并行拉取所有启用平台 → 合并进当日数据 → 更新元信息。

    返回统计信息字典。
    """
    started = time.time()
    tz = timezone or config.get("schedule", {}).get("timezone") or "Asia/Shanghai"
    now = get_configured_time(tz)
    now_iso = now.isoformat(timespec="seconds")
    date_str = now.strftime("%Y-%m-%d")

    platforms = [p for p in config.get("platforms", []) if p.get("enabled", True)]
    if not platforms:
        return {
            "ok": False,
            "error": "没有启用的监控平台，请先在「监控平台」中启用至少一个平台",
            "date": date_str,
        }

    fetcher = DataFetcher(api_url=config.get("api_url") or None)
    day_data = data_store.get_day(date_str)
    domain_by_id = {p["id"]: p.get("domain", "") for p in platforms}

    success_ids: List[str] = []
    failed_ids: List[str] = []
    total_new = 0
    total_items = 0
    deadline = started + CRAWL_DEADLINE_SECONDS
    timed_out_ids: List[str] = []

    with ThreadPoolExecutor(max_workers=CRAWL_CONCURRENCY) as pool:
        futures = {pool.submit(_fetch_one, fetcher, p): p for p in platforms}
        try:
            for future in as_completed(futures):
                if time.time() > deadline:
                    print(f"[Web抓取] 超过总体时限 {CRAWL_DEADLINE_SECONDS}s，放弃剩余平台")
                    break
                pid, response, name = future.result()
                if not response:
                    failed_ids.append(pid)
                    continue
                try:
                    data = json.loads(response)
                    items = data.get("items", [])
                except Exception as e:
                    print(f"[Web抓取] {pid} 解析失败: {e}")
                    failed_ids.append(pid)
                    continue

                # 域名安全校验（链接劫持/篡改防护）
                domain = domain_by_id.get(pid, "")
                if domain:
                    bad = fetcher._check_domain_safety(items, domain)
                    if bad:
                        print(f"[Web抓取] ⚠️ {name}({pid}) 未通过域名安全校验: {bad}，已丢弃")
                        failed_ids.append(pid)
                        continue

                new_titles = merge_crawl_results(day_data, pid, items, now_iso)
                total_new += new_titles
                total_items += len(items)
                success_ids.append(pid)
        finally:
            # 取消尚未开始的抓取；已在线程中运行的无法强杀，但其单次请求有界
            for future, p in futures.items():
                if not future.done() and future.cancel():
                    timed_out_ids.append(p["id"])
    failed_ids.extend(timed_out_ids)

    data_store.save_day(date_str, day_data)
    data_store.clear_report()  # 报告缓存失效，下次读取时重建

    duration = round(time.time() - started, 1)
    meta = data_store.get_meta()
    meta.update({
        "last_crawl_time": now_iso,
        "last_crawl_date": date_str,
        "last_crawl_status": "success" if success_ids else "failed",
        "last_crawl_stats": {
            "platforms_total": len(platforms),
            "platforms_success": len(success_ids),
            "platforms_failed": failed_ids,
            "items_fetched": total_items,
            "new_titles": total_new,
            "duration_seconds": duration,
        },
        "crawl_count": meta.get("crawl_count", 0) + 1,
    })
    data_store.save_meta(meta)

    print(f"[Web抓取] 完成: {len(success_ids)}/{len(platforms)} 平台成功, "
          f"新增标题 {total_new}, 耗时 {duration}s")
    return {
        "ok": bool(success_ids),
        "date": date_str,
        "time": now_iso,
        "platforms_success": len(success_ids),
        "platforms_failed": failed_ids,
        "items_fetched": total_items,
        "new_titles": total_new,
        "duration_seconds": duration,
    }


# ══════════════════════════════════════════════════════════════════════
# 4. 报告管线
# ══════════════════════════════════════════════════════════════════════

def merge_days_data(
    data_store: DataStore,
    days: int,
    end_date: Optional[str] = None,
) -> Dict:
    """
    合并最近 N 天的数据（含 end_date）。

    合并语义与 CLI 版 weekly 模式一致：
    - count 跨天累加
    - first_time 取最早、last_time 取最晚
    - ranks / rank_timeline 跨天拼接
    - url / mobileUrl 以最新一天为准
    """
    merged: Dict = {}
    for date_str in data_store.list_days(days, end_date):
        day_data = data_store.get_day(date_str)
        if not day_data:
            continue
        for pid, titles in day_data.items():
            platform_merged = merged.setdefault(pid, {})
            for title, rec in titles.items():
                existing = platform_merged.get(title)
                if existing is None:
                    platform_merged[title] = {
                        "ranks": list(rec.get("ranks", [])),
                        "url": rec.get("url", ""),
                        "mobileUrl": rec.get("mobileUrl", ""),
                        "first_time": rec.get("first_time", ""),
                        "last_time": rec.get("last_time", ""),
                        "count": rec.get("count", 1),
                        "rank_timeline": [list(t) for t in rec.get("rank_timeline", [])],
                    }
                else:
                    existing["count"] = existing.get("count", 1) + rec.get("count", 1)
                    existing["ranks"].extend(rec.get("ranks", []))
                    existing["rank_timeline"].extend(
                        [list(t) for t in rec.get("rank_timeline", [])]
                    )
                    # first_time 取更早者，last_time 取更晚者
                    if rec.get("first_time") and (
                        not existing["first_time"] or rec["first_time"] < existing["first_time"]
                    ):
                        existing["first_time"] = rec["first_time"]
                    if rec.get("last_time") and rec["last_time"] > existing.get("last_time", ""):
                        existing["last_time"] = rec["last_time"]
                    # 链接以最新记录为准（非空才覆盖）
                    if rec.get("url"):
                        existing["url"] = rec["url"]
                    if rec.get("mobileUrl"):
                        existing["mobileUrl"] = rec.get("mobileUrl", "")
    return merged


def build_report(
    config: Dict,
    data_store: DataStore,
    timezone: Optional[str] = None,
) -> Dict:
    """
    构建 Web 端报告（JSON 结构，供前端渲染）。

    流程：合并多日数据 → 词表过滤 → 按词组分组 → 排序裁剪。
    """
    tz = timezone or config.get("schedule", {}).get("timezone") or "Asia/Shanghai"
    now = get_configured_time(tz)
    report_cfg = config.get("report", {})
    days = int(report_cfg.get("range_days", 7) or 7)
    max_per_group = int(report_cfg.get("max_news_per_keyword", 0) or 0)

    # 1. 解析词表（与 CLI 版同一解析器）
    text = keywords_to_text(config.get("keywords", {}))
    groups, filter_words, global_filters = parse_frequency_words(text)
    group_order = {
        (g.get("display_name") or g.get("group_key")): i
        for i, g in enumerate(groups)
    }

    # 2. 合并多日数据
    merged = merge_days_data(data_store, days, now.strftime("%Y-%m-%d"))

    total_news = sum(len(titles) for titles in merged.values())
    matched_count = 0

    # 3. 过滤 + 分组
    group_stats: Dict[str, Dict] = {}
    platform_stats: Dict[str, Dict] = {}

    for pid, titles in merged.items():
        platform_stats.setdefault(pid, {"id": pid, "name": get_platform_name(pid), "matched": 0, "total": 0})
        platform_stats[pid]["total"] += len(titles)
        for title, rec in titles.items():
            if not matches_word_groups(title, groups, filter_words, global_filters):
                continue
            matched_count += 1
            platform_stats[pid]["matched"] += 1

            news_item = {
                "title": title,
                "url": rec.get("url", ""),
                "mobileUrl": rec.get("mobileUrl", ""),
                "platform_id": pid,
                "platform": get_platform_name(pid),
                "count": rec.get("count", 1),
                "ranks": rec.get("ranks", []),
                "first_time": rec.get("first_time", ""),
                "last_time": rec.get("last_time", ""),
                "rank_timeline": rec.get("rank_timeline", []),
            }

            # 一条新闻可命中多个词组，加入每个命中的词组
            for g in groups:
                if _title_matches_group(title, g, filter_words, global_filters):
                    key = g.get("display_name") or g.get("group_key")
                    stat = group_stats.setdefault(key, {"name": key, "count": 0, "news": []})
                    if not any(n["title"] == title and n["platform_id"] == pid for n in stat["news"]):
                        stat["news"].append(news_item)
                        stat["count"] = len(stat["news"])

    # 4. 排序与裁剪
    group_list = list(group_stats.values())
    if report_cfg.get("sort_by_position_first"):
        group_list.sort(key=lambda s: group_order.get(s["name"], 999))
    else:
        group_list.sort(key=lambda s: (-s["count"], group_order.get(s["name"], 999)))
    for stat in group_list:
        stat["news"].sort(key=lambda n: (-n["count"], n.get("last_time", "")))
        if max_per_group and len(stat["news"]) > max_per_group:
            stat["news"] = stat["news"][:max_per_group]

    dates = data_store.list_days(days, now.strftime("%Y-%m-%d"))
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "timezone": tz,
        "mode": report_cfg.get("mode", "weekly"),
        "range": {
            "days": days,
            "start": dates[-1] if dates else now.strftime("%Y-%m-%d"),
            "end": dates[0] if dates else now.strftime("%Y-%m-%d"),
        },
        "total_news": total_news,
        "total_matched": matched_count,
        "groups": group_list,
        "platforms": sorted(
            platform_stats.values(), key=lambda p: -p["matched"]
        ),
    }


def _title_matches_group(title: str, group: Dict, filter_words: List, global_filters: List) -> bool:
    """判断标题是否命中单个词组（复用全局/组内过滤规则）"""
    from trendradar.core.frequency import _word_matches

    title_lower = title.lower()
    if global_filters:
        if any(_word_matches(g, title_lower) for g in global_filters):
            return False
    for f in filter_words:
        if _word_matches(f, title_lower):
            return False
    required = group.get("required", [])
    if required and not all(_word_matches(r, title_lower) for r in required):
        return False
    normal = group.get("normal", [])
    if normal and not any(_word_matches(n, title_lower) for n in normal):
        return False
    return bool(required or normal)


def get_report_cached(
    config: Dict,
    data_store: DataStore,
    refresh: bool = False,
) -> Dict:
    """读取报告缓存；抓取后缓存会被清除，此时重建并缓存"""
    if not refresh:
        cached = data_store.get_report()
        if cached:
            return cached
    report = build_report(config, data_store)
    data_store.save_report(report)
    return report


# ══════════════════════════════════════════════════════════════════════
# 5. 定时判断（监控时间 → 是否到点）
# ══════════════════════════════════════════════════════════════════════

def evaluate_schedule(
    config: Dict,
    data_store: DataStore,
    now: Optional[datetime] = None,
) -> Dict:
    """
    根据「监控时间」配置判断当前是否应该抓取。

    规则：
    - 自动监控关闭 → 不执行
    - 今天不在勾选星期内 → 不执行
    - 存在到点且未执行的槽位（现在时刻 >= 设定时刻 且 < 1 小时）→ 执行
    - 今天一个槽位都没到，且今天还没抓过 → 补抓一次（保证每天有数据）

    返回 {should_run, slot, reason, slots_today, next_slot}
    """
    schedule = config.get("schedule", {})
    tz = schedule.get("timezone", "Asia/Shanghai")
    now = now or get_configured_time(tz)

    if not schedule.get("enabled"):
        return {"should_run": False, "reason": "自动监控未开启"}

    weekdays = schedule.get("weekdays", [1, 2, 3, 4, 5, 6, 7])
    # Python weekday(): 周一=0 … 周日=6；配置用 1=周一 … 7=周日
    iso_weekday = now.isoweekday()
    if weekdays and iso_weekday not in weekdays:
        return {"should_run": False, "reason": f"今天不在监控星期内（周{iso_weekday}）"}

    times = sorted(schedule.get("times", []))
    date_str = now.strftime("%Y-%m-%d")

    # 到点槽位：now >= slot 且 slot 距现在不超过 60 分钟（含整点边界，
    # 容忍外部调度器的分钟级延迟；槽位去重由 claim_slot 保证不会重复执行）
    due_slots = []
    for hhmm in times:
        try:
            h, m = map(int, hhmm.split(":"))
        except (ValueError, AttributeError):
            continue
        slot_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        delta = (now - slot_dt).total_seconds()
        if 0 <= delta <= 3600:
            due_slots.append(hhmm)

    for hhmm in due_slots:
        if data_store.claim_slot(date_str, hhmm):
            return {
                "should_run": True,
                "slot": hhmm,
                "reason": f"到点执行：{hhmm}",
                "slots_today": times,
            }

    # 补抓：今天有槽位已过（任一 slot <= now），但整天还没抓过
    meta = data_store.get_meta()
    if meta.get("last_crawl_date") != date_str:
        any_passed = False
        for hhmm in times:
            try:
                h, m = map(int, hhmm.split(":"))
            except (ValueError, AttributeError):
                continue
            slot_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if now >= slot_dt:
                any_passed = True
                break
        if any_passed and data_store.claim_slot(date_str, "catchup"):
            return {
                "should_run": True,
                "slot": "catchup",
                "reason": "补抓：今天尚未抓取过数据",
                "slots_today": times,
            }

    return {
        "should_run": False,
        "reason": "当前无到期槽位",
        "slots_today": times,
        "next_slot": _next_slot(now, times, weekdays),
    }


def _next_slot(now: datetime, times: List[str], weekdays: List[int]) -> Optional[str]:
    """计算下一个监控时刻（展示用）"""
    for i in range(8):
        day = now + timedelta(days=i)
        if weekdays and day.isoweekday() not in weekdays:
            continue
        for hhmm in sorted(times):
            try:
                h, m = map(int, hhmm.split(":"))
            except (ValueError, AttributeError):
                continue
            slot_dt = day.replace(hour=h, minute=m, second=0, microsecond=0)
            if slot_dt > now:
                return f"{day.strftime('%m-%d')} {hhmm}"
    return None
