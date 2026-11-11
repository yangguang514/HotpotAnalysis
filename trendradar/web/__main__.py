# coding=utf-8
"""
本地开发服务器

用法：
    python -m trendradar.web                # http://127.0.0.1:8765
    PORT=9000 python -m trendradar.web      # 自定义端口

与 Vercel 部署使用同一个 WSGI 应用（trendradar.web.wsgi:app），
本地用文件存储（web_data/），线上用 Vercel KV，行为一致。
"""

import os
import sys
from socketserver import ThreadingMixIn
from wsgiref.simple_server import make_server, WSGIServer


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    """线程化开发服务器：抓取等长请求不阻塞页面轮询"""

    daemon_threads = True


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("PORT", "8765"))
    except ValueError:
        port = 8765

    # 延迟导入，避免 --help 之类场景加载整个应用
    from trendradar.web.wsgi import app

    print("=" * 56)
    print(" TrendRadar Web 本地开发服务器")
    print(f" 地址:     http://{host}:{port}")
    print(f" 数据目录: {os.environ.get('WEB_DATA_DIR', 'web_data')}")
    print(" 停止:     Ctrl+C")
    print("=" * 56)

    with make_server(host, port, app, server_class=_ThreadingWSGIServer) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n服务器已停止")
            sys.exit(0)


if __name__ == "__main__":
    main()
