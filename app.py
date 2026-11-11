# coding=utf-8
"""
Vercel 部署入口

Vercel Python 运行时会自动寻找根目录的 app.py / index.py / server.py /
main.py / wsgi.py / asgi.py，并加载其中的 app（或 application）变量作为
WSGI/ASGI 应用。本文件将 trendradar.web.wsgi 的 WSGI 应用暴露出来：

- 所有 /api/* 请求由 trendradar/web/wsgi.py 内部路由处理
- public/ 目录的静态资源由 Vercel CDN 直接服务（不会到达本函数）
- 函数配置（maxDuration 等）见 vercel.json 的 functions 段
"""

from trendradar.web.wsgi import app  # noqa: F401
