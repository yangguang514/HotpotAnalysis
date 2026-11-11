# coding=utf-8
"""WSGI 应用层测试：路由、鉴权、安全防护（直接调用 app，不起 HTTP 服务器）"""
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


def call_app(method, path, headers=None, query="", body=b""):
    """调用 WSGI app，返回 (status, headers_dict, body_bytes)"""
    from trendradar.web.wsgi import app

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": io.StringIO(),
    }
    for k, v in (headers or {}).items():
        environ["HTTP_" + k.upper().replace("-", "_")] = v

    captured = {}

    def start_response(status, response_headers, exc_info=None):
        captured["status"] = int(status.split()[0])
        captured["headers"] = {k.lower(): v for k, v in response_headers}

    chunks = app(environ, start_response)
    return captured["status"], captured["headers"], b"".join(chunks)


def main():
    # 保存并清空令牌环境，保证测试确定性
    saved = {k: os.environ.pop(k, None) for k in ("ADMIN_TOKEN", "CRON_SECRET")}

    try:
        print("── 无令牌模式（本地开发默认）──")
        status, _, body = call_app("GET", "/api/health")
        check("health 200", status == 200)
        status, _, _ = call_app("GET", "/api/config")
        check("config 免鉴权可读", status == 200)
        status, _, _ = call_app("GET", "/api/unknown")
        check("未知 API 404", status == 404)

        print("── 路径穿越防护 ──")
        status, _, body = call_app("GET", "/../app.py")
        check("/../app.py → 404", status == 404)
        check("不泄露源码", b"from trendradar" not in body)
        status, _, _ = call_app("GET", "/../../etc/passwd")
        check("深层穿越 → 404", status == 404)
        status, _, _ = call_app("GET", "/app.js")
        check("正常静态路径不受影响（无 public 时 404/无泄露）", status in (200, 404))

        print("── ADMIN_TOKEN 模式 ──")
        os.environ["ADMIN_TOKEN"] = "secret123"
        status, _, _ = call_app("GET", "/api/config")
        check("无令牌 → 401", status == 401)
        status, _, _ = call_app("GET", "/api/config", {"Authorization": "Bearer wrong"})
        check("错误令牌 → 401", status == 401)
        status, _, _ = call_app("GET", "/api/config", {"Authorization": "Bearer secret123"})
        check("Bearer 正确令牌 → 200", status == 200)
        status, _, _ = call_app("GET", "/api/status", {"X-Admin-Token": "secret123"})
        check("X-Admin-Token 头 → 200", status == 200)
        status, _, _ = call_app("GET", "/api/status", query="key=secret123")
        check("?key= 参数 → 200", status == 200)
        status, _, _ = call_app("GET", "/api/health")
        check("health 仍免鉴权 → 200", status == 200)
        status, _, _ = call_app("POST", "/api/crawl")
        check("无令牌 POST → 401", status == 401)

        print("── CRON_SECRET 模式 ──")
        os.environ["CRON_SECRET"] = "cron456"
        status, _, _ = call_app("GET", "/api/cron", {"Authorization": "Bearer cron456"})
        check("cron 密钥 → 200", status == 200)
        status, _, _ = call_app("GET", "/api/cron", {"Authorization": "Bearer secret123"})
        check("admin 令牌也可调 cron → 200", status == 200)
        status, _, _ = call_app("GET", "/api/cron", {"Authorization": "Bearer nope"})
        check("错误 cron 密钥 → 401", status == 401)
        status, _, _ = call_app("GET", "/api/config", {"Authorization": "Bearer cron456"})
        check("cron 密钥不能读配置 → 401", status == 401)
        del os.environ["CRON_SECRET"]

        print("── CORS 预检 ──")
        status, headers, _ = call_app("OPTIONS", "/api/config")
        check("OPTIONS → 200", status == 200)
        check("CORS 头存在", "access-control-allow-origin" in headers)

    finally:
        os.environ.pop("ADMIN_TOKEN", None)
        os.environ.pop("CRON_SECRET", None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v

    print()
    print("=" * 46)
    print(f"测试结果: {PASS} 通过, {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
