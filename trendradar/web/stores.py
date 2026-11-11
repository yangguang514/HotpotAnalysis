# coding=utf-8
"""
Web 端存储抽象层

为 Vercel Serverless 环境（只读文件系统）与本地开发环境提供统一存储：

- ConfigStore：Web 端配置（关键词词组、监控平台、调度、报告参数）
    - FileConfigStore：本地开发，存 web_data/config.json
    - KVConfigStore：Vercel KV（Upstash Redis REST API）
- DataStore：抓取数据（按天聚合）、元信息、报告缓存、定时任务槽位
    - FileDataStore / KVDataStore，键位设计与 KV 版一致

后端选择逻辑（自动）：
    存在环境变量 KV_REST_API_URL + KV_REST_API_TOKEN → Vercel KV
    否则 → 文件存储（目录取 WEB_DATA_DIR；Vercel 环境下默认
        /tmp/trendradar_web_data，因为 Serverless 仅 /tmp 可写）
    文件目录创建失败（只读文件系统等）→ 内存后端（仅保命，数据不持久化）

所有存储值统一为 JSON 字符串，读写即 json.dumps / json.loads。
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests

from trendradar.utils.time import DEFAULT_TIMEZONE

logger = logging.getLogger(__name__)

# ── 键位设计（KV 与文件后端共用同一套键名） ────────────────────────────
# 统一加 trendradar: 命名空间前缀：KV 实例可能被多个项目共用，避免键名碰撞
KEY_NS = "trendradar:"
KEY_CONFIG = KEY_NS + "config"            # Web 配置 JSON
KEY_META = KEY_NS + "meta"                # 运行元信息（上次抓取等）
KEY_REPORT = KEY_NS + "report"            # 最新报告缓存
DAY_KEY_PREFIX = KEY_NS + "day:"          # trendradar:day:2026-11-11 → 当日抓取数据
SLOT_KEY_PREFIX = KEY_NS + "slot:"        # trendradar:slot:2026-11-11:08-00 → 定时槽位去重


def _utcnow_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class KVError(Exception):
    """Vercel KV 访问失败"""


# ══════════════════════════════════════════════════════════════════════
# KV 后端（Vercel KV / Upstash Redis REST API）
# ══════════════════════════════════════════════════════════════════════

class KVBackend:
    """Vercel KV REST 客户端（无 SDK 依赖，仅用 requests）"""

    def __init__(self, url: str, token: str, timeout: int = 15):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {token}"})

    def get(self, key: str) -> Optional[str]:
        resp = self._session.get(f"{self.url}/get/{key}", timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result")
        return result if result is not None else None

    def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        url = f"{self.url}/set/{key}"
        if ex:
            url += f"?ex={int(ex)}"
        resp = self._session.post(url, data=value.encode("utf-8"), timeout=self.timeout)
        resp.raise_for_status()

    def delete(self, key: str) -> None:
        resp = self._session.get(f"{self.url}/del/{key}", timeout=self.timeout)
        resp.raise_for_status()


def _kv_backend_from_env() -> Optional[KVBackend]:
    """从环境变量构建 KV 后端，未配置返回 None

    兼容三套命名：
    - Vercel KV（旧版集成）：KV_REST_API_URL / KV_REST_API_TOKEN
    - Vercel 环境变量简写：  KV_URL / KV_TOKEN
    - Upstash 集成（新版）：  UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN
    """
    url = (
        os.environ.get("KV_REST_API_URL")
        or os.environ.get("KV_URL")
        or os.environ.get("UPSTASH_REDIS_REST_URL")
    )
    token = (
        os.environ.get("KV_REST_API_TOKEN")
        or os.environ.get("KV_TOKEN")
        or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    )
    if url and token:
        return KVBackend(url, token)
    return None


# ══════════════════════════════════════════════════════════════════════
# 内存后端（最后兜底）
# ══════════════════════════════════════════════════════════════════════

class MemoryBackend:
    """进程内内存后端：文件系统不可用时的兜底，数据不持久化

    仅用于保证服务可用（配置读取、报告生成等不因存储故障 500），
    进程重启 / 冷启动后数据丢失。Vercel 上需要持久化请绑定 KV。
    """

    def __init__(self):
        self._data: Dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        with self._lock:
            self._data[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)


def _default_data_dir() -> str:
    """文件后端数据目录解析：
    1. 显式设置 WEB_DATA_DIR 时优先
    2. Vercel 环境（VERCEL=1）→ /tmp/trendradar_web_data
       Serverless 函数仅 /tmp 可写；每个函数实例独立，冷启动后丢失，
       需要持久化请在 Vercel 控制台绑定 KV（自动注入 KV_REST_API_URL/TOKEN）
    3. 本地开发 → web_data/
    """
    explicit = os.environ.get("WEB_DATA_DIR")
    if explicit:
        return explicit
    if os.environ.get("VERCEL"):
        return "/tmp/trendradar_web_data"
    return "web_data"


# ══════════════════════════════════════════════════════════════════════
# 文件后端（本地开发）
# ══════════════════════════════════════════════════════════════════════

class FileBackend:
    """本地文件后端，目录结构：web_data/<key 中的 ':' 转为路径分隔>"""

    def __init__(self, data_dir: str = "web_data"):
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, key: str) -> Path:
        # key 形如 day:2026-11-11 → web_data/day/2026-11-11.json
        # key 形如 slot:2026-11-11:08-00 → web_data/slot/2026-11-11_08-00.json
        # 注意：Windows 文件名不允许包含 ":"，需替换为 "_"
        parts = key.split(":", 1)
        if len(parts) == 2:
            prefix, rest = parts
            safe_name = rest.replace(":", "_")
            return self.root / prefix / f"{safe_name}.json"
        return self.root / f"{key}.json"

    def get(self, key: str) -> Optional[str]:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写：先写临时文件再替换，避免中断导致半文件
        with self._lock:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(value, encoding="utf-8")
            tmp.replace(path)

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()


def _resolve_backend():
    """按优先级解析存储后端，返回 (backend, kind)

    kind ∈ {"kv", "file", "memory"}，供 /api/status 向前端展示存储状态。
    """
    kv = _kv_backend_from_env()
    if kv is not None:
        return kv, "kv"
    data_dir = _default_data_dir()
    try:
        return FileBackend(data_dir), "file"
    except OSError as exc:
        logger.warning(
            "文件后端初始化失败（%s 不可写: %s），降级为内存后端（数据不持久化）",
            data_dir, exc,
        )
        return MemoryBackend(), "memory"


# ══════════════════════════════════════════════════════════════════════
# 配置存储
# ══════════════════════════════════════════════════════════════════════

def default_web_config() -> Dict:
    """Web 端默认配置（结构见 README-WEB.md）"""
    return {
        "version": 1,
        "keywords": {
            "groups": [],
            "global_filters": [],
        },
        "platforms": [],
        "api_url": "",
        "schedule": {
            "enabled": False,
            "weekdays": [1, 2, 3, 4, 5, 6, 7],
            "times": ["08:00", "12:00", "20:00"],
            "timezone": DEFAULT_TIMEZONE,
        },
        "report": {
            "mode": "weekly",
            "range_days": 7,
            "sort_by_position_first": False,
            "max_news_per_keyword": 0,
            "rank_threshold": 5,
        },
    }


class ConfigStore:
    """Web 配置存储（KV 或文件后端）"""

    def __init__(self, backend=None):
        if backend is not None:
            self.backend = backend
            self.backend_kind = "kv" if isinstance(backend, KVBackend) else "custom"
        else:
            self.backend, self.backend_kind = _resolve_backend()
        self.is_kv = self.backend_kind == "kv"

    def get(self) -> Optional[Dict]:
        raw = self.backend.get(KEY_CONFIG)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def get_or_default(self) -> Dict:
        config = self.get()
        if config is None:
            return default_web_config()
        return _merge_defaults(config)

    def save(self, config: Dict) -> None:
        self.backend.set(KEY_CONFIG, json.dumps(config, ensure_ascii=False))


def _merge_defaults(config: Dict) -> Dict:
    """给已有配置补齐缺失字段（前向兼容，不触发额外存储读取）"""
    default = default_web_config()
    for section in ("keywords", "schedule", "report"):
        if section not in config:
            config[section] = default[section]
        elif isinstance(default[section], dict):
            for k, v in default[section].items():
                config[section].setdefault(k, v)
    config.setdefault("platforms", [])
    config.setdefault("api_url", "")
    config.setdefault("version", 1)
    return config


# ══════════════════════════════════════════════════════════════════════
# 数据存储
# ══════════════════════════════════════════════════════════════════════

class DataStore:
    """抓取数据 / 元信息 / 报告缓存 / 定时槽位存储"""

    def __init__(self, backend=None):
        if backend is not None:
            self.backend = backend
            self.backend_kind = "kv" if isinstance(backend, KVBackend) else "custom"
        else:
            self.backend, self.backend_kind = _resolve_backend()
        self.is_kv = self.backend_kind == "kv"

    # ── 按天数据 ────────────────────────────────────────────────────

    def day_key(self, date_str: str) -> str:
        return f"{DAY_KEY_PREFIX}{date_str}"

    def get_day(self, date_str: str) -> Dict:
        """读取某日数据：{platform_id: {title: {...}}}，不存在返回 {}"""
        raw = self.backend.get(self.day_key(date_str))
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    def save_day(self, date_str: str, data: Dict) -> None:
        self.backend.set(self.day_key(date_str), json.dumps(data, ensure_ascii=False))

    def list_days(self, days: int, end_date: Optional[str] = None) -> List[str]:
        """最近 N 天的日期字符串列表（含 end_date，倒序）"""
        if end_date:
            end = datetime.strptime(end_date, "%Y-%m-%d")
        else:
            end = datetime.now()
        return [(end - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

    # ── 元信息 ──────────────────────────────────────────────────────

    def get_meta(self) -> Dict:
        raw = self.backend.get(KEY_META)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    def save_meta(self, meta: Dict) -> None:
        self.backend.set(KEY_META, json.dumps(meta, ensure_ascii=False))

    # ── 报告缓存 ────────────────────────────────────────────────────

    def get_report(self) -> Optional[Dict]:
        raw = self.backend.get(KEY_REPORT)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def save_report(self, report: Dict) -> None:
        self.backend.set(KEY_REPORT, json.dumps(report, ensure_ascii=False))

    def clear_report(self) -> None:
        try:
            self.backend.delete(KEY_REPORT)
        except Exception:
            pass

    # ── 定时槽位（去重） ─────────────────────────────────────────────

    def slot_key(self, date_str: str, hhmm: str) -> str:
        return f"{SLOT_KEY_PREFIX}{date_str}:{hhmm}"

    def claim_slot(self, date_str: str, hhmm: str) -> bool:
        """尝试认领一个定时槽位，返回 True 表示本次应执行（首次认领成功）"""
        key = self.slot_key(date_str, hhmm)
        if self.backend.get(key):
            return False
        # 槽位记录 48 小时后自动过期
        self.backend.set(key, _utcnow_iso(), ex=172800)
        return True
