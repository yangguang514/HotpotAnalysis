# coding=utf-8
"""
Web 端 WSGI 应用

- Vercel：根目录 app.py 导出本模块的 app 变量，整个站点由单个
  Serverless Function 承载（public/ 静态资源由 Vercel CDN 直接服务）
- 本地开发：python -m trendradar.web 用 wsgiref 起服务，
  静态文件由本应用直接从 public/ 读取返回

API 一览：
    GET  /api/health   健康检查
    GET  /api/config   读取 Web 配置（关键词/平台/调度/报告参数）
    POST /api/config   保存 Web 配置（校验后写入存储）
    GET  /api/status   运行状态（上次抓取、监控计划、存储后端）
    POST /api/crawl    立即执行一轮抓取
    GET  /api/report   读取报告（?refresh=1 强制重建）
    GET  /api/cron     定时入口（Vercel Cron / 外部调度器）

鉴权：
    - 设置环境变量 ADMIN_TOKEN 后，所有 /api/* 要求
      Authorization: Bearer <token>（或 X-Admin-Token 头）
    - /api/cron 额外接受 CRON_SECRET（Vercel Cron 自动以 Bearer 发送）
    - 两者都未设置时完全开放（仅建议本地开发使用）
"""

import json
import os
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from trendradar.web.pipeline import (
    build_report,
    evaluate_schedule,
    get_report_cached,
    run_crawl,
    seed_config_from_files,
    validate_keywords,
)
from trendradar.web.stores import ConfigStore, DataStore

PUBLIC_DIR = Path(__file__).resolve().parent.parent.parent / "public"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


# ══════════════════════════════════════════════════════════════════════
# 基础工具
# ══════════════════════════════════════════════════════════════════════

def _json_response(
    payload: Dict,
    status: int = 200,
    headers: Optional[List[Tuple[str, str]]] = None,
) -> Tuple[bytes, int, List[Tuple[str, str]]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    base_headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Cache-Control", "no-store"),
        ("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
        ("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Admin-Token"),
    ]
    if headers:
        base_headers.extend(headers)
    return body, status, base_headers


def _error(message: str, status: int = 400) -> Tuple[bytes, int, List[Tuple[str, str]]]:
    return _json_response({"ok": False, "error": message}, status)


def _read_body(environ: Dict) -> bytes:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except (ValueError, TypeError):
        length = 0
    if length <= 0:
        return b""
    return environ["wsgi.input"].read(length)


def _parse_json_body(environ: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    raw = _read_body(environ)
    if not raw:
        return {}, None
    try:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return None, "请求体必须是 JSON 对象"
        return data, None
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return None, f"请求体不是合法 JSON: {e}"


def _check_auth(environ: Dict, extra_secret: Optional[str] = None) -> Optional[str]:
    """
    鉴权检查，返回 None 表示通过，否则返回错误描述。

    extra_secret：/api/cron 场景下 CRON_SECRET 也可通过。
    """
    admin_token = os.environ.get("ADMIN_TOKEN", "").strip()
    secrets = [s for s in (admin_token, extra_secret or "") if s]
    if not secrets:
        return None  # 未配置任何令牌 → 开放访问

    headers = _headers(environ)
    # 注意：_headers 返回小写键
    provided = (
        headers.get("authorization", "")
        .replace("Bearer ", "")
        .strip()
        or headers.get("x-admin-token", "").strip()
        or headers.get("x-cron-secret", "").strip()
    )
    # 也允许 query 参数 ?key=（方便浏览器/调度器调试，安全性略低）
    if not provided:
        query = parse_qs(environ.get("QUERY_STRING", ""))
        provided = (query.get("key") or query.get("token") or [""])[0].strip()

    if not provided:
        return "缺少访问令牌"
    for secret in secrets:
        if provided == secret:
            return None
    return "访问令牌不正确"


def _headers(environ: Dict) -> Dict[str, str]:
    """从 WSGI environ 提取 HTTP 头（小写键）"""
    headers = {}
    for key, value in environ.items():
        if key.startswith("HTTP_"):
            headers[key[5:].lower().replace("_", "-")] = value
    if environ.get("CONTENT_TYPE"):
        headers["content-type"] = environ["CONTENT_TYPE"]
    return headers


# ══════════════════════════════════════════════════════════════════════
# API 处理函数
# ══════════════════════════════════════════════════════════════════════

def _get_stores() -> Tuple[ConfigStore, DataStore]:
    return ConfigStore(), DataStore()


def handle_health(environ: Dict, query: Dict) -> Tuple[bytes, int, List[Tuple[str, str]]]:
    return _json_response({"ok": True, "service": "trendradar-web", "version": 1})


def handle_platforms(environ: Dict, query: Dict) -> Tuple[bytes, int, List[Tuple[str, str]]]:
    """平台目录（供前端「监控平台」多选）"""
    from trendradar.web.catalog import PLATFORM_CATALOG, PLATFORM_DOMAINS

    return _json_response({
        "ok": True,
        "catalog": [{"id": pid, "name": name} for pid, name in PLATFORM_CATALOG],
        "domains": PLATFORM_DOMAINS,
    })


def handle_get_config(environ: Dict, query: Dict) -> Tuple[bytes, int, List[Tuple[str, str]]]:
    config_store, _ = _get_stores()
    config = seed_config_from_files(config_store)
    return _json_response({"ok": True, "config": config})


def handle_post_config(environ: Dict, query: Dict) -> Tuple[bytes, int, List[Tuple[str, str]]]:
    body, err = _parse_json_body(environ)
    if err:
        return _error(err)
    config = body.get("config")
    if not isinstance(config, dict):
        return _error("缺少 config 字段")

    # 词表校验
    keywords = config.get("keywords", {})
    if not isinstance(keywords, dict):
        return _error("keywords 必须是对象")
    errors = validate_keywords(keywords)
    if errors:
        return _json_response({"ok": False, "errors": errors}, 422)

    # 平台校验
    platforms = config.get("platforms", [])
    if not isinstance(platforms, list) or not platforms:
        return _error("platforms 至少需要一个平台")
    seen = set()
    for p in platforms:
        if not isinstance(p, dict) or not p.get("id"):
            return _error("platforms 中含有无效平台（缺少 id）")
        if p["id"] in seen:
            return _error(f"平台重复: {p['id']}")
        seen.add(p["id"])

    # 调度校验
    schedule = config.get("schedule", {})
    times = schedule.get("times", [])
    if not isinstance(times, list):
        return _error("schedule.times 必须是数组")
    for t in times:
        if not isinstance(t, str) or not _valid_hhmm(t):
            return _error(f"时间格式不正确: {t}（应为 HH:MM，如 08:30）")
    weekdays = schedule.get("weekdays", [])
    if not isinstance(weekdays, list) or not all(
        isinstance(w, int) and 1 <= w <= 7 for w in weekdays
    ):
        return _error("schedule.weekdays 必须是 1-7 的整数数组")

    report = config.get("report", {})
    try:
        days = int(report.get("range_days", 7))
        if not 1 <= days <= 90:
            raise ValueError
    except (ValueError, TypeError):
        return _error("report.range_days 必须是 1-90 的整数")

    config_store, _ = _get_stores()
    config["version"] = 1
    config_store.save(config)
    return _json_response({"ok": True, "message": "配置已保存"})


def _valid_hhmm(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 2:
        return False
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 0 <= h <= 23 and 0 <= m <= 59


def handle_status(environ: Dict, query: Dict) -> Tuple[bytes, int, List[Tuple[str, str]]]:
    config_store, data_store = _get_stores()
    config = seed_config_from_files(config_store)
    meta = data_store.get_meta()
    schedule = config.get("schedule", {})

    from trendradar.utils.time import get_configured_time

    now = get_configured_time(schedule.get("timezone", "Asia/Shanghai"))
    dates = data_store.list_days(
        int(config.get("report", {}).get("range_days", 7) or 7),
        now.strftime("%Y-%m-%d"),
    )
    available_days = [d for d in dates if data_store.get_day(d)]

    # 持久性判断：仅 KV 跨冷启动持久；Vercel 上文件后端落在 /tmp，同样不持久
    on_vercel = bool(os.environ.get("VERCEL"))
    persistent = data_store.backend_kind == "kv" or (
        data_store.backend_kind == "file" and not on_vercel
    )

    return _json_response({
        "ok": True,
        "backend": data_store.backend_kind,
        "persistent": persistent,
        "server_time": now.isoformat(timespec="seconds"),
        "last_crawl": {
            "time": meta.get("last_crawl_time"),
            "date": meta.get("last_crawl_date"),
            "status": meta.get("last_crawl_status"),
            "stats": meta.get("last_crawl_stats"),
        },
        "crawl_count": meta.get("crawl_count", 0),
        "schedule": {
            "enabled": schedule.get("enabled", False),
            "times": schedule.get("times", []),
            "weekdays": schedule.get("weekdays", []),
            "timezone": schedule.get("timezone"),
        },
        "next_slot": None,
        "data_days": available_days,
        "platforms_enabled": len([p for p in config.get("platforms", []) if p.get("enabled", True)]),
        "keywords_groups": len(config.get("keywords", {}).get("groups", [])),
    })


def handle_crawl(environ: Dict, query: Dict) -> Tuple[bytes, int, List[Tuple[str, str]]]:
    config_store, data_store = _get_stores()
    config = seed_config_from_files(config_store)
    result = run_crawl(config, config_store, data_store)
    status = 200 if result.get("ok") else 400
    return _json_response(result, status)


def handle_report(environ: Dict, query: Dict) -> Tuple[bytes, int, List[Tuple[str, str]]]:
    config_store, data_store = _get_stores()
    config = seed_config_from_files(config_store)
    refresh = query.get("refresh", ["0"])[0] in ("1", "true")
    report = get_report_cached(config, data_store, refresh=refresh)
    return _json_response({"ok": True, "report": report})


def handle_cron(environ: Dict, query: Dict) -> Tuple[bytes, int, List[Tuple[str, str]]]:
    """
    定时入口。

    - Vercel Cron 自动携带 Authorization: Bearer <CRON_SECRET>
    - 外部调度器（GitHub Actions 等）自行携带同样头部
    - 未配置 CRON_SECRET 时依赖 ADMIN_TOKEN（均未设置则开放）
    """
    auth_err = _check_auth(environ, extra_secret=os.environ.get("CRON_SECRET", "").strip())
    if auth_err:
        return _error(auth_err, 401)

    config_store, data_store = _get_stores()
    config = seed_config_from_files(config_store)
    decision = evaluate_schedule(config, data_store)

    if not decision["should_run"]:
        return _json_response({
            "ok": True,
            "ran": False,
            "reason": decision.get("reason", ""),
            "next_slot": decision.get("next_slot"),
        })

    result = run_crawl(config, config_store, data_store)
    return _json_response({
        "ok": result.get("ok", False),
        "ran": True,
        "slot": decision.get("slot"),
        "reason": decision.get("reason"),
        "crawl": result,
    })


# ══════════════════════════════════════════════════════════════════════
# 静态文件（仅本地开发需要；Vercel 上由 CDN 服务 public/）
# ══════════════════════════════════════════════════════════════════════

def _serve_static(path: str) -> Optional[Tuple[bytes, int, List[Tuple[str, str]]]]:
    if PUBLIC_DIR is None or not PUBLIC_DIR.exists():
        return None
    rel = path.lstrip("/") or "index.html"
    target = (PUBLIC_DIR / rel).resolve()
    # 防目录穿越
    try:
        target.relative_to(PUBLIC_DIR.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    suffix = target.suffix.lower()
    body = target.read_bytes()
    return body, 200, [("Content-Type", CONTENT_TYPES.get(suffix, "application/octet-stream"))]


# ══════════════════════════════════════════════════════════════════════
# 路由与 WSGI 入口
# ══════════════════════════════════════════════════════════════════════

ROUTES: List[Tuple[str, str, Callable]] = [
    ("GET", "/api/health", handle_health),
    ("GET", "/api/platforms", handle_platforms),
    ("GET", "/api/config", handle_get_config),
    ("POST", "/api/config", handle_post_config),
    ("GET", "/api/status", handle_status),
    ("POST", "/api/crawl", handle_crawl),
    ("GET", "/api/report", handle_report),
    ("GET", "/api/cron", handle_cron),
]


def app(environ, start_response):
    """WSGI 应用入口（Vercel 与本地共用）"""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = urlparse(environ.get("PATH_INFO", "/")).path.rstrip("/") or "/"
    query = parse_qs(environ.get("QUERY_STRING", ""))

    # 拒绝目录穿越尝试（.. 路径段）。Vercel CDN 会先行归一化，
    # 这里主要保护本地开发服务器：既不回退到 SPA，也不读取 public/ 之外的文件。
    if ".." in environ.get("PATH_INFO", "").split("/"):
        body, status, headers = _error("Not Found", 404)
        start_response(f"{status} Not Found", headers)
        return [body]

    # CORS 预检
    if method == "OPTIONS":
        body, status, headers = _json_response({})
        start_response(f"{status} OK", headers)
        return [body]

    # API 路由
    for route_method, route_path, handler in ROUTES:
        if method == route_method and path == route_path:
            # /api/health 免鉴权（探活用）；其余端点需管理员密钥。
            # CRON_SECRET 仅对 /api/cron 有效（Vercel Cron 自动携带），
            # 不把它当作其他端点的通用凭证，缩小定时密钥的权限面。
            if route_path != "/api/health":
                extra = os.environ.get("CRON_SECRET", "").strip() if route_path == "/api/cron" else ""
                auth_err = _check_auth(environ, extra_secret=extra)
                if auth_err:
                    body, status, headers = _error(auth_err, 401)
                    start_response(f"{status} Unauthorized", headers)
                    return [body]
            try:
                body, status, headers = handler(environ, query)
            except Exception as e:
                print(f"[Web API] {path} 处理异常: {e}")
                body, status, headers = _error(f"服务器内部错误: {e}", 500)
            start_response(f"{status} {'OK' if status < 400 else 'ERROR'}", headers)
            return [body]

    # 静态文件（本地开发）
    static = _serve_static(environ.get("PATH_INFO", "/"))
    if static is not None:
        body, status, headers = static
        start_response(f"{status} OK", headers)
        return [body]

    # 未知 /api/* 路径 → 404 JSON（不落入 SPA 回退）
    if path.startswith("/api"):
        body, status, headers = _error("Not Found", 404)
        start_response(f"{status} Not Found", headers)
        return [body]

    # SPA 回退（本地开发时 / 直接给 index.html）
    if method == "GET":
        index = _serve_static("/index.html")
        if index is not None:
            body, status, headers = index
            start_response(f"{status} OK", headers)
            return [body]

    body, status, headers = _error("Not Found", 404)
    start_response(f"{status} Not Found", headers)
    return [body]
