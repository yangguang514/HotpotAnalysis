# coding=utf-8
"""KV 后端冒烟测试：本地 mock Upstash REST API"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote

STORE = {}


class MockUpstash(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(self.path)
        if path.startswith("/get/"):
            key = path[len("/get/"):]
            self._send({"result": STORE.get(key)})
        elif path.startswith("/del/"):
            key = path[len("/del/"):]
            STORE.pop(key, None)
            self._send({"result": 1})
        else:
            self._send({"error": "not found"})

    def do_POST(self):
        path = unquote(self.path)
        length = int(self.headers.get("Content-Length", 0))
        value = self.rfile.read(length).decode("utf-8")
        if path.startswith("/set/"):
            key = path[len("/set/"):]
            STORE[key] = value
            self._send({"result": "OK"})
        else:
            self._send({"error": "not found"})


def main():
    server = HTTPServer(("127.0.0.1", 0), MockUpstash)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    from trendradar.web.stores import KVBackend, ConfigStore, DataStore

    backend = KVBackend(f"http://127.0.0.1:{port}", "test-token")
    backend.set("trendradar:config", json.dumps({"version": 1, "hello": "世界"}))
    got = backend.get("trendradar:config")
    assert got is not None and json.loads(got)["hello"] == "世界", "KV set/get 失败"
    print("✅ KV set/get")

    # 通过 ConfigStore/DataStore 走一遍完整读写
    config_store = ConfigStore(backend=backend)
    cfg = config_store.get_or_default()
    assert "keywords" in cfg, "默认配置结构异常"
    config_store.save(cfg)
    assert json.loads(STORE["trendradar:config"])["keywords"]["groups"] == cfg["keywords"]["groups"]
    print("✅ ConfigStore over KV")

    data_store = DataStore(backend=backend)
    data_store.save_day("2026-11-11", {"weibo": {"测试标题": {"count": 1}}})
    day = data_store.get_day("2026-11-11")
    assert day["weibo"]["测试标题"]["count"] == 1, "DataStore KV 读写失败"
    print("✅ DataStore over KV")

    # 键名规范检查（Upstash REST 通过 URL 路径传键，斜杠会破坏路径）
    keys = list(STORE.keys())
    assert all(k.startswith("trendradar:") for k in keys), keys
    assert all("/" not in k for k in keys), f"键名含斜杠会破坏 REST 路径: {keys}"
    print("✅ 键名命名空间与 URL 安全:", keys)

    server.shutdown()
    print("\nKV 后端冒烟测试全部通过")


if __name__ == "__main__":
    main()
