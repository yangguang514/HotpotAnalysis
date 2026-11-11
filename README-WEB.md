# TrendRadar Web 化改造与 Vercel 部署指南

本文件记录把 TrendRadar（原为本地 CLI 工具）改造为**前端可操作、支持远程部署**的系统所涉及的全部内容：核心功能模块、配置项交互逻辑、部署适配范围与最终效果。

---

## 1. 改造总览

### 1.1 架构变化

```
改造前（纯本地 CLI）                     改造后（CLI + Web 双模式）
┌──────────────────────┐              ┌──────────────────────┐
│ trendradar/__main__.py│              │ trendradar/__main__.py│  ← CLI 保留，行为不变
│   ├ config/*.yaml     │              │   ├ config/*.yaml    │
│   ├ output/news/*.db  │              │   └ output/news/*.db │
│   └ 调度/抓取/报告一体 │              ├──────────────────────┤
└──────────────────────┘              │ trendradar/web/      │  ← 新增 Web 层
                                      │   ├ stores.py        │  配置/数据存储抽象
                                      │   ├ pipeline.py      │  抓取/报告/定时管线
                                      │   ├ wsgi.py          │  WSGI 应用 + API 路由
                                      │   └ catalog.py       │  平台目录
                                      ├──────────────────────┤
                                      │ app.py               │  Vercel 入口
                                      │ public/              │  前端仪表盘
                                      │ vercel.json          │  部署配置
                                      └──────────────────────┘
```

**设计原则：零侵入复用。** Web 层不重写业务逻辑，而是复用现有模块：

| 复用模块 | 用途 |
|---|---|
| `crawler/fetcher.py` `DataFetcher` | 热榜抓取、域名安全校验（防链接劫持） |
| `core/frequency.py` `parse_frequency_words` / `matches_word_groups` | 词表解析与关键词匹配（同一套逻辑，CLI 与 Web 行为一致） |
| `utils/time.py` | 时区处理、日期格式化 |
| `web/catalog.py` | NewsNow 平台目录（68 个平台的 id/名称/域名规则） |

为此对 `core/frequency.py` 做了一个**行为等价的重构**：抽出 `parse_frequency_words(content)`（从字符串解析），`load_frequency_words(path)` 变为其薄封装。原 `tests/test_frequency.py` 验证通过，CLI 行为不变。

### 1.2 新增文件清单

| 文件 | 职责 |
|---|---|
| `trendradar/web/__init__.py` | 包初始化 |
| `trendradar/web/catalog.py` | 68 个平台目录 + 域名规则（供前端多选与安全校验） |
| `trendradar/web/stores.py` | 存储抽象：`KVBackend`（Vercel KV/Upstash REST）、`FileBackend`（本地文件，Vercel 上落 `/tmp`）与 `MemoryBackend`（只读文件系统兜底），上层 `ConfigStore` / `DataStore` 接口一致 |
| `trendradar/web/pipeline.py` | 业务管线：配置种子化、抓取合并、跨天报告聚合、定时槽位判定 |
| `trendradar/web/wsgi.py` | WSGI 应用：REST API 路由、鉴权、静态资源、安全防护 |
| `trendradar/web/__main__.py` | 本地开发服务器（`python -m trendradar.web`） |
| `app.py` | Vercel 部署入口（暴露 WSGI `app`） |
| `frontend/` | React + TypeScript + Vite 前端源码与构建配置 |
| `public/` | Vite 生成的静态仪表盘资源，由 Vercel CDN 服务 |
| `vercel.json` | 函数时长、Cron 配置 |
| `requirements.txt` | Vercel 依赖清单（仅 `requests` + `PyYAML` + `pytz`） |
| `package.json` `frontend/package.json` | 前端 workspace 与 React/Vite 依赖，供 Vercel 执行生产构建 |
| `.vercelignore` | 排除 `pyproject.toml`/`uv.lock`（避免 Vercel 装重依赖）与本地资产 |
| `.python-version` | 锁定 Python 3.12 |
| `.github/workflows/trendradar-cron.yml` | 外部定时触发器（补足 Hobby 计划 Cron 每天一次的限制） |
| `tests/test_web_pipeline.py` | 管线离线测试（40 项，不依赖外网） |
| `tests/test_web_kv.py` | KV 后端冒烟测试（mock Upstash REST API） |
| `tests/test_web_wsgi.py` | WSGI 层测试（20 项：路由、鉴权、穿越防护、CORS） |

---

## 2. 核心功能模块说明

### 2.1 存储抽象（`stores.py`）

同一套键名设计，两种后端自动切换：

```
ConfigStore / DataStore
   ├── KVBackend    ← 检测到 KV_REST_API_URL/TOKEN（或 UPSTASH_REDIS_REST_URL/TOKEN）时启用
   └── FileBackend  ← 否则回退到本地 web_data/ 目录（开发用）
```

**键位设计**（统一 `trendradar:` 命名空间，防止共享 KV 实例时与其他项目碰撞）：

| 键 | 内容 |
|---|---|
| `trendradar:config` | Web 配置 JSON（关键词/平台/调度/报告） |
| `trendradar:meta` | 运行元信息（上次抓取时间与统计） |
| `trendradar:day:2026-11-11` | 当日抓取数据（标题→次数/排名/时间线） |
| `trendradar:slot:2026-11-11:08-00` | 定时槽位认领记录（去重，防止重复抓取） |
| `trendradar:report` | 最新报告缓存（抓取后失效重建） |

`FileBackend` 的原子写（临时文件 + replace）保证中断不产生半文件；Windows 下键名中的 `:` 会转为 `_`（文件名不允许冒号）。

### 2.2 业务管线（`pipeline.py`）

**配置种子化**：首次访问时，如果 KV 中没有配置，自动从仓库的 `config/frequency_words.txt`、`config/config.yaml` 生成一份等价的 Web 配置——部署后打开页面即有你之前配好的 19 个动物生态词组和 11 个监控平台，无需从零配置。

**抓取管线** `run_crawl()`：
- 线程池并发抓取（6 并发），复用 CLI 的 `DataFetcher`（含域名安全校验）
- Serverless 友好的保守重试（1 次重试、短退避）
- **总体时限 200 秒**：超时后取消未开始的任务并记为失败，为 Vercel 300 秒函数上限留足余量
- 结果合并进当日数据：同标题 count+1、ranks 追加、`rank_timeline` 追加时间线、last_time 更新

**报告管线** `merge_days_data()` + `build_report()`：
- 跨天合并最近 N 天数据（复用 CLI weekly 模式的合并语义）
- 关键词分组统计、平台过滤、排序（默认排名优先）
- 报告缓存：抓取后失效，下次读取重建

**定时槽位** `evaluate_schedule()`：
- 判定逻辑：今天是否在「监控星期」内 → 各「监控时间」槽位是否已认领 → 未认领则触发抓取并认领
- 槽位认领是**原子**的（KV SETNX 语义由 FileBackend 的 replace 与 KV 的 set 保证），并发触发不会重复抓取
- 「补抓」机制：当天已过时点但从未抓过（如服务中断恢复），会补一次

### 2.3 REST API（`wsgi.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查（免鉴权） |
| GET | `/api/platforms` | 平台目录（68 个，供前端多选） |
| GET | `/api/config` | 读取 Web 配置 |
| POST | `/api/config` | 保存配置（校验后写入） |
| GET | `/api/status` | 运行状态（后端类型、自动监控、数据天数、上次抓取） |
| POST | `/api/crawl` | 手动触发一轮抓取 |
| GET | `/api/report` | 聚合报告（按 `range_days`） |
| GET | `/api/cron` | 定时入口（Vercel Cron / GitHub Actions 调用） |

**鉴权**：除 `/api/health` 外均需 `Authorization: Bearer <ADMIN_TOKEN>`。设置环境变量 `ADMIN_TOKEN` 即启用；未设置时本地开发免鉴权。`/api/cron` 同时接受 `CRON_SECRET`（Vercel Cron 会自动带上，见 4.3）。

**安全防护**：
- 目录穿越（`..` 路径段）直接 404，且静态服务有 `resolve()` + `relative_to()` 双重校验，`public/` 之外的文件不可读
- 未知 `/api/*` 返回 404 JSON，不落入 SPA 回退
- 抓取结果做域名安全校验（复用 CLI 的链接劫持防护）

### 2.4 前端仪表盘（`public/`）

三个标签页使用 React + TypeScript 实现，按功能组件拆分，并由 Vite 构建为静态资源：

**① 关注关键词**
- 词组可视化编辑：每个词组一张卡片，支持改名、编辑词行与删除
- 词行语法与 `frequency_words.txt` 完全一致：`普通词`、`/正则/ => 显示名`、`!排除词`、`+必须词`、`@显示条数`
- 全局过滤词单独管理
- 保存前在浏览器端做基础校验，服务端再用 `validate_keywords()`（调用项目自己的解析器）做权威校验——**服务端校验不通过会拒绝保存并返回具体错误**，保证页面配置与 CLI 词表永远等价

**② 监控时间与平台**
- 自动监控总开关
- 监控星期多选（周一~周日）
- 监控时间多选（`HH:MM`，可增删）
- 时区选择（默认 `Asia/Shanghai`）
- 监控平台多选（68 个平台目录，带启用/禁用）

**③ 热点报告**
- 展示聚合报告：按词组分组的新闻列表（标题、平台、上榜次数、排名变化、首次/末次上榜时间）
- 顶部统计：监控平台数、数据天数、总新闻数、上次抓取时间
- 「立即抓取」按钮：手动触发一轮抓取并刷新报告
- 报告范围跟随 `report.range_days` 配置

---

## 3. 配置项交互逻辑

页面配置与存储的对应关系（`POST /api/config` 的请求体结构）：

```jsonc
{
  "config": {
    "version": 1,
    "keywords": {
      "groups": [                          // 关注词组（有序）
        {
          "display_name": "大熊猫",         // 显示名（[] 行或 => 后的名字）
          "lines": ["/大熊猫|熊猫|旅韩大熊猫/ => 大熊猫"]  // 词行，语法同 frequency_words.txt
        }
      ],
      "global_filters": ["震惊"]           // 全局排除词
    },
    "platforms": [                         // 启用的监控平台
      { "id": "weibo", "name": "微博", "enabled": true, "domain": "weibo.com" }
    ],
    "api_url": "",                         // 自定义 NewsNow 实例（留空用默认）
    "schedule": {
      "enabled": false,                    // 自动监控开关
      "weekdays": [1,2,3,4,5,6,7],         // 监控星期（1=周一 … 7=周日）
      "times": ["08:00","12:00","20:00"],  // 监控时间（HH:MM，最多若干个）
      "timezone": "Asia/Shanghai"
    },
    "report": {
      "mode": "weekly",                    // weekly=整周汇总 / daily=当日汇总
      "range_days": 7,                     // 聚合天数（weekly 生效）
      "max_news_per_keyword": 0,           // 每组显示条数上限（0=不限）
      "rank_threshold": 5                  // 高排名阈值
    }
  }
}
```

**保存时的校验链**（任一步失败即拒绝并返回中文错误信息）：

1. 结构校验：`keywords.groups` 非空、`schedule.times` 为合法 `HH:MM`（且不重复）、`weekdays` 在 1~7、`range_days` 在 1~90
2. 词表序列化：结构化词组 → `frequency_words.txt` 格式文本（`keywords_to_text()`，保留 `[GLOBAL_FILTER]`/`[WORD_GROUPS]` 区域标记）
3. 权威解析：用项目自己的 `parse_frequency_words()` 解析序列化结果，解析失败或结果为空则拒绝
4. 写入存储（KV 或文件），前端即时刷新

**与 CLI 配置的关系**：两套配置独立。CLI 继续读 `config/` 目录；Web 端读 KV/文件存储。首次种子化会让两者初始内容一致，之后各改各的。`frequency_words.txt` 的手改内容想同步到 Web，删掉 KV 里的 `trendradar:config` 键（或清空本地 `web_data/`）后重新访问即可重新种子化。

---

## 4. 部署适配范围与步骤

### 4.1 适配要点（为什么需要这些文件）

| 适配项 | 原因 |
|---|---|
| `requirements.txt` | Vercel Python 运行时的依赖清单。**关键**：Vercel 的 uv 安装器优先读 `pyproject.toml`，而本项目 pyproject 含 litellm/boto3 等 CLI 专用重依赖，会拖垮函数体积与冷启动。因此 `.vercelignore` 排除 `pyproject.toml` + `uv.lock`，让 Vercel 只认这份精简清单（requests/PyYAML/pytz，约 3 个包） |
| `app.py` | Vercel Python 运行时约定入口文件名（`app.py`/`index.py`/`server.py` 等），加载其中的 `app` 变量作为 WSGI 应用 |
| `vercel.json` → `functions.app.py.maxDuration: 300` | Fluid compute 下 Hobby 计划默认即 300s；抓取管线时限设为 200s 留余量 |
| `vercel.json` → `crons` | 注册每日一次的 Cron（Hobby 限制） |
| `.python-version` | 锁定 Python 3.12（项目要求 ≥3.12） |
| `public/` | Vite 生成的静态资源目录，由 Vercel CDN 直接服务（不提交构建产物） |
| 延迟导入改造（`trendradar/__init__.py`） | 原包初始化急切导入 `AppContext` → 连带拉入 `trendradar.ai` → litellm。改用 PEP 562 模块 `__getattr__` 延迟加载后，Web 端导入链不再拖累任何重依赖（已验证 litellm/boto3/feedparser/fastmcp 均不加载），CLI 的 `from trendradar import AppContext` 用法保持兼容 |

### 4.2 部署步骤

1. **推送代码**到 GitHub 仓库（`git push`）。Vercel 执行 `npm run build` 生成 `public/` 静态资源，再由 CDN 服务页面；Python API 入口和运行时依赖保持不变。
2. **创建 Vercel 项目**：vercel.com → Add New → Project → 导入该仓库。Framework Preset 选 **Other**（无框架，纯 Python + 静态文件）。
3. **创建 KV 存储**（必须，否则 Serverless 环境数据不持久）：
   - Vercel 控制台 → Storage → Create → **Upstash Redis**（或 KV）→ 关联到刚创建的项目
   - 关联后环境变量会自动注入（`KV_REST_API_URL`/`KV_REST_API_TOKEN` 或 `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN`，两种命名都兼容）
   - 免费额度（Upstash 免费档约 500K 命令/月）对个人监控足够：一次抓取约十几次 KV 写，一天 3 次约 50 次命令
4. **设置环境变量**（Settings → Environment Variables）：

   | 变量 | 值 | 说明 |
   |---|---|---|
   | `ADMIN_TOKEN` | 自拟一串随机字符 | API 管理员令牌。**建议设置**：页面首次打开会要求输入，之后保存在浏览器 localStorage |
   | `CRON_SECRET` | 自拟另一串随机字符 | 定时入口密钥。Vercel Cron 会自动以 `Authorization: Bearer <CRON_SECRET>` 调用 `/api/cron` |

5. **部署**：首次导入会自动构建部署。之后每次 `git push` 到默认分支自动重新部署。
6. **访问**：打开分配的 `https://<项目名>.vercel.app`，输入 `ADMIN_TOKEN` 进入仪表盘。

> 未配置 KV 时的行为：自动回退到文件后端，数据目录为 `/tmp/trendradar_web_data`（Serverless 仅 `/tmp` 可写）。`/tmp` 在同一个函数实例内可读写，但**按实例独立、冷启动后重置**，仅适合临时体验；若目录创建失败会再降级为内存后端（`/api/status` 的存储徽标显示「⚠️ 临时存储」）。生产必须配 KV。

### 4.3 定时监控的两种触发方式

Hobby 计划的 Vercel 内置 Cron **每天只能运行一次**。本项目的「监控时间」支持一天内多个时刻，因此提供两条路径：

**方式 A：Vercel 内置 Cron（零维护，每天一次）**
`vercel.json` 已注册 `0 13 * * *`（UTC 13:00 = 北京时间 21:00）。服务端槽位逻辑会判断该时刻是否在「监控时间」里——在则抓，不在则跳过。想改时刻就改 `vercel.json` 里的 cron 表达式。

**方式 B：GitHub Actions 外部调度（免费，支持一天多次）**
`.github/workflows/trendradar-cron.yml` 每 15 分钟调用一次 `/api/cron`，由服务端按「监控星期 + 监控时间」决定是否真正抓取。配置方法：
1. 仓库 Settings → Secrets and variables → Actions → New repository secret
2. 添加 `TRENDRADAR_URL` = `https://你的项目.vercel.app`（不带末尾斜杠）
3. 添加 `CRON_SECRET` = 与 Vercel 环境变量相同的值
4. 在 Actions 页面手动运行一次验证（应返回 `{"action": "crawled"}` 或 `{"action": "skip"}`）

两种方式可同时启用：槽位认领机制保证同一槽位只抓一次，不会重复。GitHub 仓库 60 天无活动会暂停定时 workflow，属正常现象。

### 4.4 本地开发

```bash
# 安装 Python 依赖（复用已有 .venv 或新建）
uv sync                          # 或 pip install requests PyYAML pytz

# 启动 Python API（默认端口 8765，文件后端，数据落 web_data/）
python -m trendradar.web

# 在另一个终端启动 React 开发服务器（默认端口 5173）
npm install
npm run dev
```

开发时访问 Vite 地址 `http://localhost:5173`。Vite 会将 `/api/*` 请求代理到 `http://127.0.0.1:8765`；Python API 和生产环境 API 契约保持一致。若希望用 Python 静态服务预览生产页面，先执行 `npm run build`，再访问 `http://127.0.0.1:8765`。

---

## 5. 各项功能最终效果

| 功能 | 效果 |
|---|---|
| **页面端配置入口** | 打开网页即可管理一切：关键词词组的可视化增删改、监控星期与时刻的多选、自动监控开关、监控平台勾选。无需登录服务器、无需改文件、无需重新部署 |
| **配置即时生效** | 保存后下一次抓取/报告立即使用新配置；保存前的服务端权威校验保证页面配置与 CLI 词表逻辑永远一致（不会出现"页面显示配好了但实际没生效"） |
| **自动监控** | 按「星期 + 多个时刻」触发抓取，槽位去重防止重复；服务中断恢复后自动补抓当天漏掉的时点 |
| **手动抓取** | 报告页「立即抓取」按钮，随时获取最新热榜 |
| **整周/整日报告** | `weekly` 模式跨天合并（默认 7 天）：同一新闻在周内多次上榜会显示累计次数与上榜时间线，安静日不出现空报告；`daily` 模式只看当天 |
| **远程持久化** | 数据存 Vercel KV（Upstash Redis），函数冷启动/重新部署不丢失；历史数据按天一个键，报告按需聚合 |
| **独立前端构建** | React + TypeScript + Vite；构建产物由 Vercel CDN 直接服务，运行时继续调用同域 Python API |
| **CLI 不受影响** | `python -m trendradar` 原有用法、配置、输出完全不变，本地/服务器两条路径可并行使用 |
| **安全** | API 令牌鉴权、目录穿越防护、抓取域名安全校验、槽位原子认领 |

---

## 6. 测试与验证

```bash
python tests/test_web_pipeline.py    # 40 项管线离线测试（mock 抓取，不依赖外网）
python tests/test_web_kv.py          # KV 后端冒烟测试（mock Upstash REST）
python tests/test_web_wsgi.py        # 20 项 WSGI 层测试（路由/鉴权/穿越防护/CORS）
python -m unittest tests.test_frequency -v   # 原词表测试（验证重构无回归）
python -m trendradar --doctor        # CLI 环境体检
npm run build                        # 前端类型检查与 Vite 生产构建
npm test                             # 前端词表原始文本往返测试
```

已验证项：词表解析/匹配一致性、配置保存往返与校验拒绝、跨天合并语义（count 累加/时间线拼接/首末时间取舍）、定时槽位判定与补抓、KV 读写与键名 URL 安全、API 鉴权（ADMIN_TOKEN 三传入方式 + CRON_SECRET 仅限 /api/cron + health 免鉴权）、路径穿越 404、静态资源服务、API 404 语义、CORS 预检。

---

## 7. 已知限制

- **Hobby 计划 Cron 每天一次**：一天内多时刻监控需配 GitHub Actions 外部调度（见 4.3）
- **抓取时限 200 秒**：极端网络下个别平台可能超时被放弃，其余平台结果照常保存；平台数远大于 68 时建议分批或提高 `CRAWL_DEADLINE_SECONDS`
- **AI 功能未接入 Web 端**：页面配置使用关键词模式（免费、确定性强）。AI 智能分类需在 `config.yaml` 配 `ai.api_key`，属 CLI 能力
- **通知推送未接入 Web 端**：当前报告只在页面查看；需要推送（企业微信/飞书/Telegram 等）时用 CLI 模式或后续扩展
