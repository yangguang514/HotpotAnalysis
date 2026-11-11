# coding=utf-8
"""存储后端解析测试：Vercel 只读文件系统适配

覆盖：
1. MemoryBackend 基本读写
2. _default_data_dir：WEB_DATA_DIR > VERCEL=/tmp > 本地 web_data
3. _resolve_backend：文件目录创建失败时降级内存后端
4. ConfigStore/DataStore 的 backend_kind 上报（/api/status 依赖）
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.web import stores  # noqa: E402
from trendradar.web.stores import (  # noqa: E402
    ConfigStore,
    DataStore,
    MemoryBackend,
)


class _RecordingBackend(MemoryBackend):
    """记录传入目录的内存后端，用于验证目录解析逻辑"""

    def __init__(self, data_dir):
        super().__init__()
        self.data_dir = data_dir


def _with_env(**env):
    """上下文管理器：临时设置/清除环境变量，结束后还原"""
    class _Ctx:
        def __enter__(self):
            self.saved = {}
            keys = set(env) | {"WEB_DATA_DIR", "VERCEL", "KV_REST_API_URL",
                               "KV_REST_API_TOKEN", "KV_URL", "KV_TOKEN",
                               "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"}
            for k in keys:
                self.saved[k] = os.environ.pop(k, None)
            for k, v in env.items():
                if v is not None:
                    os.environ[k] = v

        def __exit__(self, *args):
            for k, v in self.saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return _Ctx()


def main():
    # ── 1. MemoryBackend 读写 ──────────────────────────────────────
    mem = MemoryBackend()
    assert mem.get("missing") is None
    mem.set("k", "v")
    assert mem.get("k") == "v"
    mem.delete("k")
    assert mem.get("k") is None
    print("✅ MemoryBackend get/set/delete")

    # ── 2. _default_data_dir 优先级 ────────────────────────────────
    with _with_env():
        assert stores._default_data_dir() == "web_data", "本地默认应为 web_data"
    with _with_env(VERCEL="1"):
        assert stores._default_data_dir() == "/tmp/trendradar_web_data", \
            "Vercel 环境应默认 /tmp（仅 /tmp 可写）"
    with _with_env(VERCEL="1", WEB_DATA_DIR="/custom/dir"):
        assert stores._default_data_dir() == "/custom/dir", "显式 WEB_DATA_DIR 应优先"
    print("✅ _default_data_dir 优先级: WEB_DATA_DIR > VERCEL > 本地默认")

    # ── 3. _resolve_backend：Vercel 环境走文件后端（/tmp） ──────────
    orig_file_backend = stores.FileBackend
    stores.FileBackend = _RecordingBackend
    try:
        with _with_env(VERCEL="1"):
            backend, kind = stores._resolve_backend()
            assert kind == "file", kind
            assert backend.data_dir == "/tmp/trendradar_web_data", backend.data_dir
        print("✅ Vercel 环境文件后端目录 = /tmp/trendradar_web_data")

        # ── 4. 文件后端创建失败 → 内存兜底 ─────────────────────────
        class _BrokenBackend:
            def __init__(self, data_dir):
                raise OSError(30, "Read-only file system")

        stores.FileBackend = _BrokenBackend
        with _with_env(WEB_DATA_DIR="/nonexistent/readonly"):
            backend, kind = stores._resolve_backend()
            assert kind == "memory", kind
            assert isinstance(backend, MemoryBackend)
        print("✅ 只读文件系统降级为内存后端")

        # 降级后 Store 仍可用（保命，不 500）
        with _with_env():
            cfg_store = ConfigStore(backend=MemoryBackend())
            assert cfg_store.backend_kind == "custom"
            assert cfg_store.is_kv is False
            cfg = cfg_store.get_or_default()
            assert "keywords" in cfg
            cfg_store.save(cfg)
            assert json.loads(cfg_store.backend.get(stores.KEY_CONFIG))["version"] == 1
            data_store = DataStore(backend=MemoryBackend())
            assert data_store.backend_kind == "custom"
            data_store.save_day("2026-11-11", {"weibo": {"标题": {"count": 1}}})
            assert data_store.get_day("2026-11-11")["weibo"]["标题"]["count"] == 1
        print("✅ 内存后端兜底时 ConfigStore/DataStore 读写正常")
    finally:
        stores.FileBackend = orig_file_backend

    # ── 5. backend_kind 端到端：kv / file ─────────────────────────
    with _with_env():
        kv_like = MemoryBackend()
        kv_store = ConfigStore(backend=kv_like)
        # 显式注入 KVBackend 实例时 kind=kv（用真实 KVBackend 类构造但不发请求）
        from trendradar.web.stores import KVBackend
        kv_backend = KVBackend("http://127.0.0.1:1", "token")
        assert ConfigStore(backend=kv_backend).backend_kind == "kv"
        assert ConfigStore(backend=kv_backend).is_kv is True
        assert kv_store.backend_kind == "custom"
    print("✅ backend_kind: 注入 KVBackend → kv")

    print("\n存储后端解析测试全部通过")


if __name__ == "__main__":
    main()
