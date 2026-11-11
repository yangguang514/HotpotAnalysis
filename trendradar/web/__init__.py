# coding=utf-8
"""
TrendRadar Web 端

把热点监控系统改造为前端可操作、可远程部署（Vercel）的形态：

- 配置（关键词/平台/监控时间/自动开关）在网页上直接维护，存 Vercel KV 或本地文件
- 抓取由 Serverless Function 执行，Vercel Cron 或外部调度器按「监控时间」触发
- 报告以 JSON API 提供，前端仪表盘渲染

本地开发：
    python -m trendradar.web            # 默认 http://127.0.0.1:8765
    PORT=9000 python -m trendradar.web  # 指定端口
"""

from trendradar.web.pipeline import (  # noqa: F401
    build_report,
    evaluate_schedule,
    get_report_cached,
    run_crawl,
    seed_config_from_files,
    validate_keywords,
)
from trendradar.web.stores import ConfigStore, DataStore  # noqa: F401
from trendradar.web.wsgi import app  # noqa: F401

__all__ = [
    "app",
    "build_report",
    "evaluate_schedule",
    "get_report_cached",
    "run_crawl",
    "seed_config_from_files",
    "validate_keywords",
    "ConfigStore",
    "DataStore",
]
