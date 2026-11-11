/* TrendRadar Web 仪表盘逻辑 */
(function () {
  "use strict";

  // ── 状态 ──
  var state = {
    config: null,
    report: null,
    status: null,
    token: localStorage.getItem("tr_token") || "",
    rawMode: false,
    crawling: false,
  };

  var WEEKDAY_LABELS = ["一", "二", "三", "四", "五", "六", "日"]; // 索引 0 = 周一
  var PLATFORM_ORDER = null; // 由 /api/config 返回的平台目录顺序（内置在页面脚本下方注入）

  // ── 工具 ──
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function fmtTime(iso) {
    if (!iso) return "";
    var s = String(iso).replace("T", " ");
    return s.length >= 16 ? s.slice(5, 16) : s;
  }
  function toast(msg, type) {
    var el = $("toast");
    el.textContent = msg;
    el.className = "toast" + (type ? " " + type : "");
    el.hidden = false;
    clearTimeout(el._timer);
    el._timer = setTimeout(function () { el.hidden = true; }, type === "err" ? 6000 : 3000);
  }

  // ── API ──
  function api(path, options) {
    options = options || {};
    var headers = { "Content-Type": "application/json" };
    if (state.token) headers["Authorization"] = "Bearer " + state.token;
    return fetch(path, {
      method: options.method || "GET",
      headers: headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
    }).then(function (resp) {
      if (resp.status === 401) {
        showTokenModal();
        throw new Error("未授权：需要访问令牌");
      }
      return resp.json().then(function (data) {
        if (!resp.ok) throw new Error(data.error || data.message || ("HTTP " + resp.status));
        return data;
      });
    });
  }

  // ── 页签 ──
  document.querySelectorAll(".tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (b) { b.classList.remove("active"); });
      document.querySelectorAll(".tab-panel").forEach(function (p) { p.classList.remove("active"); });
      btn.classList.add("active");
      $("tab-" + btn.dataset.tab).classList.add("active");
      if (btn.dataset.tab === "report") loadReport();
      if (btn.dataset.tab === "schedule") loadStatus();
    });
  });

  // ── 令牌弹窗 ──
  function showTokenModal() { $("token-modal").hidden = false; $("token-input").focus(); }
  $("btn-token").addEventListener("click", showTokenModal);
  $("btn-token-cancel").addEventListener("click", function () { $("token-modal").hidden = true; });
  $("btn-token-save").addEventListener("click", function () {
    state.token = $("token-input").value.trim();
    localStorage.setItem("tr_token", state.token);
    $("token-modal").hidden = true;
    toast("令牌已保存", "ok");
    init();
  });

  // ═══════════════ 关键词编辑 ═══════════════

  function renderGroups() {
    var box = $("groups-editor");
    box.innerHTML = "";
    var groups = state.config.keywords.groups || [];
    groups.forEach(function (g, i) {
      var card = document.createElement("div");
      card.className = "group-card";
      card.innerHTML =
        '<div class="group-card-head">' +
          '<span class="group-index">' + (i + 1) + "</span>" +
          '<input class="group-name" type="text" value="' + esc(g.display_name) + '" placeholder="词组显示名">' +
          '<button class="group-del" type="button" title="删除该词组">🗑</button>' +
        "</div>" +
        '<textarea class="textarea mono" rows="3" placeholder="每行一个关键词，例如：&#10;/大熊猫|熊猫|旅韩大熊猫/ => 大熊猫">' + esc((g.lines || []).join("\n")) + "</textarea>";
      card.querySelector(".group-del").addEventListener("click", function () {
        state.config.keywords.groups.splice(i, 1);
        renderGroups();
      });
      card.querySelector(".group-name").addEventListener("input", function (e) {
        state.config.keywords.groups[i].display_name = e.target.value;
      });
      card.querySelector("textarea").addEventListener("input", function (e) {
        state.config.keywords.groups[i].lines = e.target.value.split("\n");
      });
      box.appendChild(card);
    });
    $("global-filters").value = (state.config.keywords.global_filters || []).join("\n");
  }

  $("global-filters").addEventListener("input", function (e) {
    state.config.keywords.global_filters = e.target.value.split("\n").filter(function (s) { return s.trim(); });
  });

  $("btn-add-group").addEventListener("click", function () {
    state.config.keywords.groups.push({ display_name: "", lines: [""] });
    renderGroups();
    var cards = document.querySelectorAll(".group-card .group-name");
    if (cards.length) cards[cards.length - 1].focus();
  });

  // 原始文本模式
  $("btn-toggle-raw").addEventListener("click", function () {
    var raw = $("raw-editor");
    if (state.rawMode) {
      // 从原始文本切回结构化（尽力解析）
      applyRawToStructured(raw.value);
      state.rawMode = false;
      $("btn-toggle-raw").textContent = "切换到原始文本编辑";
      raw.hidden = true;
      renderGroups();
    } else {
      raw.value = structuredToRaw();
      state.rawMode = true;
      $("btn-toggle-raw").textContent = "切换回可视化编辑";
      raw.hidden = false;
    }
  });

  function structuredToRaw() {
    var parts = [];
    var gf = (state.config.keywords.global_filters || []).filter(function (s) { return s.trim(); });
    if (gf.length) parts.push("[GLOBAL_FILTER]\n" + gf.join("\n"));
    (state.config.keywords.groups || []).forEach(function (g) {
      var lines = (g.lines || []).filter(function (l) { return l.trim(); });
      if (!lines.length) return;
      var name = (g.display_name || "").trim();
      var block = lines.slice();
      // 有显示名且首行没有 => 别名时，用组别名语法
      if (name && !block[0].match(/\s=>\s/) && !/^\[.+\]$/.test(block[0])) {
        block.unshift("[" + name + "]");
      }
      parts.push(block.join("\n"));
    });
    return parts.join("\n\n") + "\n";
  }

  function applyRawToStructured(text) {
    var blocks = text.split(/\n\s*\n/).map(function (b) { return b.trim(); }).filter(Boolean);
    var groups = [], globalFilters = [], section = "WORD_GROUPS";
    blocks.forEach(function (block) {
      var lines = block.split("\n").map(function (l) { return l.trim(); }).filter(function (l) { return l && !l.startsWith("#"); });
      if (!lines.length) return;
      if (/^\[GLOBAL_FILTER\]$/i.test(lines[0])) { section = "GLOBAL_FILTER"; lines = lines.slice(1); if (!lines.length) return; }
      else if (/^\[WORD_GROUPS\]$/i.test(lines[0])) { section = "WORD_GROUPS"; lines = lines.slice(1); if (!lines.length) return; }
      if (section === "GLOBAL_FILTER") { globalFilters = globalFilters.concat(lines); return; }
      var displayName = "", body = lines;
      if (/^\[.+\]$/.test(lines[0])) { displayName = lines[0].slice(1, -1); body = lines.slice(1); }
      else if (lines[0].indexOf("=>") !== -1) { displayName = lines[0].split("=>")[1].trim(); }
      if (!body.length) return;
      groups.push({ display_name: displayName || body[0], lines: body });
    });
    state.config.keywords = { groups: groups, global_filters: globalFilters };
  }

  $("btn-save-keywords").addEventListener("click", function () {
    if (state.rawMode) {
      applyRawToStructured($("raw-editor").value);
      state.rawMode = false;
      $("raw-editor").hidden = true;
      $("btn-toggle-raw").textContent = "切换到原始文本编辑";
      renderGroups();
    }
    saveConfig("词表已保存");
  });

  // ═══════════════ 监控设置 ═══════════════

  function renderSchedule() {
    var s = state.config.schedule;
    $("schedule-enabled").checked = !!s.enabled;
    $("timezone").value = s.timezone || "Asia/Shanghai";
    $("range-days").value = (state.config.report && state.config.report.range_days) || 7;

    // 星期 chips
    var wbox = $("weekday-chips");
    wbox.innerHTML = "";
    WEEKDAY_LABELS.forEach(function (label, idx) {
      var day = idx + 1; // 1=周一 … 7=周日
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip" + ((s.weekdays || []).indexOf(day) !== -1 ? " on" : "");
      chip.textContent = "周" + label;
      chip.addEventListener("click", function () {
        var arr = (state.config.schedule.weekdays = state.config.schedule.weekdays || []);
        var at = arr.indexOf(day);
        if (at === -1) arr.push(day); else arr.splice(at, 1);
        chip.classList.toggle("on");
      });
      wbox.appendChild(chip);
    });

    // 时间 chips
    renderTimeChips();
    // 平台
    renderPlatforms();
  }

  function renderTimeChips() {
    var box = $("time-chips");
    box.innerHTML = "";
    var times = (state.config.schedule.times || []).slice().sort();
    if (!times.length) {
      box.innerHTML = '<span class="hint-inline">尚未添加监控时间</span>';
      return;
    }
    times.forEach(function (t) {
      var chip = document.createElement("span");
      chip.className = "chip on";
      chip.innerHTML = "🕐 " + esc(t) + ' <button class="chip-del" type="button" title="删除">×</button>';
      chip.querySelector(".chip-del").addEventListener("click", function () {
        var arr = state.config.schedule.times;
        var at = arr.indexOf(t);
        if (at !== -1) arr.splice(at, 1);
        renderTimeChips();
      });
      box.appendChild(chip);
    });
  }

  function addTime(t) {
    if (!/^\d{2}:\d{2}$/.test(t)) { toast("时间格式应为 HH:MM", "err"); return; }
    var arr = state.config.schedule.times = state.config.schedule.times || [];
    if (arr.indexOf(t) !== -1) { toast("该时间已存在", "err"); return; }
    arr.push(t);
    renderTimeChips();
  }
  $("btn-add-time").addEventListener("click", function () {
    addTime($("new-time").value);
  });
  document.querySelectorAll(".btn-quick-time").forEach(function (btn) {
    btn.addEventListener("click", function () { addTime(btn.dataset.time); });
  });

  $("schedule-enabled").addEventListener("change", function (e) {
    state.config.schedule.enabled = e.target.checked;
  });
  $("timezone").addEventListener("change", function (e) {
    state.config.schedule.timezone = e.target.value;
  });
  $("range-days").addEventListener("change", function (e) {
    var v = parseInt(e.target.value, 10);
    if (!v || v < 1 || v > 90) { toast("统计范围需在 1-90 天之间", "err"); return; }
    state.config.report.range_days = v;
  });

  function renderPlatforms() {
    var grid = $("platform-grid");
    var filter = $("platform-search").value.trim().toLowerCase();
    var selected = {};
    (state.config.platforms || []).forEach(function (p) { if (p.enabled !== false) selected[p.id] = true; });
    var catalog = window.PLATFORM_CATALOG || [];
    var enabledCount = Object.keys(selected).length;
    $("platform-count").textContent = "已启用 " + enabledCount + " / " + catalog.length;

    grid.innerHTML = "";
    catalog.forEach(function (pair) {
      var id = pair[0], name = pair[1];
      if (filter && id.toLowerCase().indexOf(filter) === -1 && name.indexOf(filter) === -1) return;
      var item = document.createElement("label");
      item.className = "platform-item" + (selected[id] ? " on" : "");
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = !!selected[id];
      cb.addEventListener("change", function () {
        var platforms = state.config.platforms;
        var found = null;
        for (var i = 0; i < platforms.length; i++) if (platforms[i].id === id) { found = platforms[i]; break; }
        if (!found) {
          found = { id: id, name: name, domain: "", enabled: cb.checked };
          platforms.push(found);
        } else {
          found.enabled = cb.checked;
        }
        item.classList.toggle("on", cb.checked);
        $("platform-count").textContent = "已启用 " +
          platforms.filter(function (p) { return p.enabled !== false; }).length + " / " + catalog.length;
      });
      item.appendChild(cb);
      item.appendChild(document.createTextNode(name));
      grid.appendChild(item);
    });
  }

  $("platform-search").addEventListener("input", renderPlatforms);
  $("btn-select-all").addEventListener("click", function () {
    var catalog = window.PLATFORM_CATALOG || [];
    state.config.platforms = catalog.map(function (p) {
      return { id: p[0], name: p[1], domain: window.PLATFORM_DOMAINS[p[0]] || "", enabled: true };
    });
    renderPlatforms();
  });
  $("btn-select-none").addEventListener("click", function () {
    state.config.platforms.forEach(function (p) { p.enabled = false; });
    renderPlatforms();
  });

  $("btn-save-schedule").addEventListener("click", function () {
    var s = state.config.schedule;
    s.enabled = $("schedule-enabled").checked;
    s.timezone = $("timezone").value;
    s.weekdays = s.weekdays || [];
    var days = parseInt($("range-days").value, 10);
    if (!days || days < 1 || days > 90) { toast("统计范围需在 1-90 天之间", "err"); return; }
    state.config.report.range_days = days;
    saveConfig("监控设置已保存");
  });

  // ═══════════════ 保存 / 状态 / 报告 ═══════════════

  function saveConfig(msg) {
    api("/api/config", { method: "POST", body: { config: state.config } })
      .then(function (data) {
        if (data.ok) { toast(msg || "已保存", "ok"); loadStatus(); }
        else toast((data.errors || [data.error]).join("；") || "保存失败", "err");
      })
      .catch(function (e) { toast(e.message, "err"); });
  }

  function loadStatus() {
    api("/api/status").then(function (data) {
      state.status = data;
      var backend = $("badge-backend");
      if (data.backend === "kv") {
        backend.textContent = "☁️ Vercel KV";
        backend.className = "badge ok";
        backend.title = "配置与数据持久化存储（Vercel KV）";
      } else if (data.backend === "memory") {
        backend.textContent = "⚠️ 临时存储";
        backend.className = "badge warn";
        backend.title = "存储不可用，数据仅存内存，冷启动后丢失；请在 Vercel 控制台绑定 KV";
      } else {
        backend.textContent = "💾 本地存储";
        backend.className = "badge";
        backend.title = data.persistent === false
          ? "临时存储：冷启动/重启后数据丢失，建议在 Vercel 控制台绑定 KV 持久化"
          : "配置与数据存于本地 web_data/ 目录";
      }

      var auto = $("badge-auto");
      if (data.schedule.enabled) {
        auto.textContent = "⏰ 自动监控 开";
        auto.className = "badge ok";
        auto.title = "监控时刻：" + (data.schedule.times || []).join(" / ");
      } else {
        auto.textContent = "⏸ 自动监控 关";
        auto.className = "badge off";
      }

      var last = $("badge-lastcrawl");
      if (data.last_crawl && data.last_crawl.time) {
        last.textContent = "最近抓取 " + fmtTime(data.last_crawl.time);
        last.className = "badge" + (data.last_crawl.status === "success" ? " ok" : " warn");
        var st = data.last_crawl.stats || {};
        last.title = st.platforms_success + "/" + st.platforms_total + " 平台成功，新增 " +
          st.new_titles + " 条，耗时 " + st.duration_seconds + "s";
      } else {
        last.textContent = "尚未抓取";
        last.className = "badge";
      }
    }).catch(function () { /* 静默：401 时已弹窗 */ });
  }

  function loadReport() {
    api("/api/report").then(function (data) {
      state.report = data.report;
      renderReport();
    }).catch(function (e) {
      $("report-body").innerHTML = '<div class="empty"><span class="big">⚠️</span>报告加载失败：' + esc(e.message) + "</div>";
    });
  }

  function renderReport() {
    var r = state.report;
    if (!r) return;
    $("report-summary").innerHTML =
      card(r.range.days + " 天", "统计范围") +
      card(r.total_news, "榜上新闻总数") +
      card(r.total_matched, "命中关注词") +
      card(r.groups.length, "关注词组");

    function card(num, label) {
      return '<div class="summary-card"><div class="num">' + esc(num) + '</div><div class="label">' + label + "</div></div>";
    }

    var body = $("report-body");
    if (!r.groups.length) {
      body.innerHTML = '<div class="empty"><span class="big">🌱</span>统计范围内还没有命中关注词的新闻。<br>点击「立即抓取」跑一轮，或等自动监控到点执行。</div>';
      return;
    }

    var html = "";
    r.groups.forEach(function (g) {
      html += '<div class="report-group"><div class="report-group-head"><h3>' + esc(g.name) +
        '</h3><span class="report-group-count">' + g.count + " 条</span></div><ul class=\"news-list\">";
      g.news.forEach(function (n) {
        var rank = n.ranks && n.ranks.length ? Math.min.apply(null, n.ranks) : "-";
        var titleHtml = n.url
          ? '<a href="' + esc(n.url) + '" target="_blank" rel="noopener">' + esc(n.title) + "</a>"
          : esc(n.title);
        html += '<li class="news-item">' +
          '<span class="news-rank' + (typeof rank === "number" && rank <= 3 ? " top" : "") + '">' + esc(rank) + "</span>" +
          '<div class="news-main"><div class="news-title">' + titleHtml + "</div>" +
          '<div class="news-meta"><span class="tag">' + esc(n.platform) + "</span>" +
          fmtTime(n.first_time) + " 上榜" + (n.count > 1 ? " · 累计 " + n.count + " 次" : "") +
          (n.first_time !== n.last_time ? " · 至 " + fmtTime(n.last_time) : "") +
          "</div></div>" +
          (n.count > 1 ? '<span class="news-count">×' + n.count + "</span>" : "") +
          "</li>";
      });
      html += "</ul></div>";
    });
    body.innerHTML = html;
  }

  $("btn-refresh-report").addEventListener("click", function () {
    var btn = this;
    btn.disabled = true;
    api("/api/report?refresh=1").then(function (data) {
      state.report = data.report;
      renderReport();
      toast("报告已刷新", "ok");
    }).catch(function (e) { toast(e.message, "err"); })
      .finally(function () { btn.disabled = false; });
  });

  $("btn-crawl").addEventListener("click", function () {
    if (state.crawling) return;
    state.crawling = true;
    var btn = this;
    btn.disabled = true;
    btn.textContent = "⏳ 抓取中…";
    api("/api/crawl", { method: "POST", body: {} }).then(function (data) {
      if (data.ok) {
        toast("抓取完成：" + data.platforms_success + " 个平台成功，新增 " + data.new_titles + " 条", "ok");
        return api("/api/report?refresh=1").then(function (rd) {
          state.report = rd.report;
          renderReport();
        });
      }
      toast(data.error || "抓取失败", "err");
    }).catch(function (e) { toast(e.message, "err"); })
      .finally(function () {
        state.crawling = false;
        btn.disabled = false;
        btn.textContent = "⚡ 立即抓取";
        loadStatus();
      });
  });

  // ═══════════════ 初始化 ═══════════════

  function init() {
    // 先加载平台目录，再加载配置（平台多选依赖目录数据）
    api("/api/platforms").then(function (data) {
      window.PLATFORM_CATALOG = (data.catalog || []).map(function (p) { return [p.id, p.name]; });
      window.PLATFORM_DOMAINS = data.domains || {};
    }).catch(function () {
      window.PLATFORM_CATALOG = [];
      window.PLATFORM_DOMAINS = {};
    }).finally(function () {
      api("/api/config").then(function (data) {
        state.config = data.config;
        renderGroups();
        renderSchedule();
        loadStatus();
      }).catch(function (e) {
        document.querySelector("main").insertAdjacentHTML(
          "afterbegin",
          '<div class="empty"><span class="big">⚠️</span>配置加载失败：' + esc(e.message) + "</div>"
        );
      });
    });
  }

  init();
})();
