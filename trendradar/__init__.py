# coding=utf-8
"""
TrendRadar - 热点新闻聚合与分析工具

使用方式:
  python -m trendradar        # 模块执行
  trendradar                  # 安装后执行

注意：AppContext 采用延迟加载（PEP 562）。Web 端（Vercel Serverless）
只导入 trendradar.core.frequency / crawler.fetcher 等轻量模块，
若不延迟加载，导入 trendradar 包会顺带拉入 litellm 等仅 AI 功能需要的
重依赖，导致线上部署被迫安装这些包、拖慢冷启动。
"""

__version__ = "6.11.0"
__all__ = ["AppContext", "__version__"]


def __getattr__(name):
    if name == "AppContext":
        from trendradar.context import AppContext

        return AppContext
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return list(__all__)
