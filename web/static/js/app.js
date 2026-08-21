/* ============ 抖音视频自动发送 · 管理面板前端逻辑 ============ */
(function () {
    "use strict";

    // ---------- 基础工具 ----------
    function $(sel) { return document.querySelector(sel); }
    function $all(sel) { return document.querySelectorAll(sel); }

    function toast(msg, type) {
        type = type || "info";
        var c = $("#toast-container");
        var el = document.createElement("div");
        el.className = "toast " + type;
        el.textContent = msg;
        c.appendChild(el);
        setTimeout(function () {
            el.style.opacity = "0";
            el.style.transition = "opacity .3s";
            setTimeout(function () { el.remove(); }, 300);
        }, 3200);
    }

    async function api(path, opts) {
        opts = opts || {};
        var init = { method: opts.method || "GET", headers: {} };
        if (opts.body !== undefined) {
            init.method = "POST";
            init.headers["Content-Type"] = "application/json";
            init.body = JSON.stringify(opts.body);
        }
        var res = await fetch(path, init);
        var data = await res.json().catch(function () { return {}; });
        return data;
    }

    function esc(s) {
        if (s === null || s === undefined) return "";
        return String(s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    function fmtUptime(sec) {
        if (!sec || sec < 0) return "—";
        var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
        var parts = [];
        if (h) parts.push(h + " 小时");
        if (m) parts.push(m + " 分");
        parts.push(s + " 秒");
        return parts.join(" ");
    }

    // ---------- 页面导航 ----------
    var pageTitles = {
        dashboard: "Dashboard", config: "配置中心", tasks: "任务记录",
        logs: "运行日志", settings: "高级设置", about: "关于"
    };

    function switchPage(name) {
        $all(".page").forEach(function (p) { p.classList.remove("active"); });
        var target = $("#page-" + name);
        if (target) target.classList.add("active");
        $all("#nav a").forEach(function (a) {
            a.classList.toggle("active", a.getAttribute("data-page") === name);
        });
        $("#page-title").textContent = pageTitles[name] || name;
        if (name === "logs") refreshLogs(true);
        if (name === "tasks") refreshTasks();
        if (name === "dashboard") refreshDashboard();
        if (name === "config") loadConfig();
        if (name === "settings") loadConfig();
    }

    $all("#nav a").forEach(function (a) {
        a.addEventListener("click", function () { switchPage(a.getAttribute("data-page")); });
    });

    // ---------- 主题切换 ----------
    function applyTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("theme", theme);
        $("#theme-toggle").textContent = theme === "dark" ? "☀️ 主题" : "🌙 主题";
    }
    var savedTheme = localStorage.getItem("theme") || "light";
    applyTheme(savedTheme);
    $("#theme-toggle").addEventListener("click", function () {
        var cur = document.documentElement.getAttribute("data-theme");
        applyTheme(cur === "dark" ? "light" : "dark");
    });

    // ---------- 状态与统计 ----------
    var STATUS_TEXT = {
        ok: ["ok", "正常"], error: ["error", "异常"],
        warn: ["warn", "警告"], checking: ["checking", "检测中"],
        unknown: ["unknown", "未知"]
    };

    function statusDot(status) {
        var cls = STATUS_TEXT[status] ? STATUS_TEXT[status][0] : "unknown";
        return '<span class="status-dot ' + cls + '"></span>';
    }
    function statusText(status) {
        return STATUS_TEXT[status] ? STATUS_TEXT[status][1] : "未知";
    }

    async function refreshDashboard() {
        var st = await api("/api/status");
        if (!st.ok) return;
        var d = st.data;
        renderStatus(d);
        renderService(d.service);

        var stats = await api("/api/stats");
        if (stats.ok) renderStats(stats.data);
    }

    function renderStatus(d) {
        var modules = [
            { key: "wechat", name: "微信", icon: "💬" },
            { key: "weflow", name: "WeFlow", icon: "🔗" },
            { key: "douyin", name: "抖音解析", icon: "🎵" },
            { key: "bilibili", name: "B站解析", icon: "📺" },
            { key: "xhs", name: "小红书解析", icon: "📕" },
            { key: "service", name: "消息监听", icon: "📡",
              custom: d.service ? (d.service.running ? "ok" : "unknown") : "unknown",
              detail: d.service && d.service.running ? "运行中" : "未启动" },
        ];
        var html = "";
        modules.forEach(function (m) {
            var status = m.custom || (d[m.key] ? d[m.key].status : "unknown");
            var detail = m.detail || (d[m.key] ? d[m.key].detail : "");
            html += '<div class="status-card">' + statusDot(status) +
                '<div><div class="st-name">' + m.icon + ' ' + m.name +
                '：<span>' + statusText(status) + '</span></div>' +
                '<div class="st-detail">' + esc(detail || "") + '</div></div></div>';
        });
        $("#status-grid").innerHTML = html;
    }

    function renderStats(s) {
        var items = [
            { label: "今日处理", value: s.total || 0, cls: "primary" },
            { label: "今日成功", value: s.success || 0, cls: "success" },
            { label: "今日失败", value: s.failed || 0, cls: "failed" },
            { label: "今日下载", value: s.downloaded || 0, cls: "" },
        ];
        var html = "";
        items.forEach(function (it) {
            html += '<div class="stat-card"><div class="stat-label">' + it.label + '</div>' +
                '<div class="stat-value ' + it.cls + '">' + it.value + '</div></div>';
        });
        $("#stats-grid").innerHTML = html;
    }

    function renderService(svc) {
        var running = svc.running;
        $("#service-state").textContent = running ? "运行中" : "未运行";
        $("#service-state").className = "badge " + (running ? "success" : "pending");
        $("#service-pill").textContent = running ? "● 监听运行中" : "● 监听未运行";
        $("#service-pill").className = "badge " + (running ? "success" : "pending");
        $("#service-start").textContent = svc.started_at ? new Date(svc.started_at * 1000).toLocaleString("zh-CN") : "—";
        $("#service-uptime").textContent = fmtUptime(svc.uptime);
        $("#btn-start").disabled = running;
        $("#btn-stop").disabled = !running;
    }

    // ---------- 服务控制 ----------
    async function serviceAction(action) {
        var btnMap = { start: $("#btn-start"), stop: $("#btn-stop"), restart: $("#btn-restart") };
        var btn = btnMap[action];
        if (btn) { btn.disabled = true; btn.dataset.orig = btn.textContent; btn.innerHTML = '<span class="spinner"></span> 处理中...'; }
        try {
            var r = await api("/api/service/" + action, { body: {} });
            toast(r.detail || (r.ok ? "操作成功" : "操作失败"), r.ok ? "success" : "error");
        } catch (e) {
            toast("请求失败: " + e, "error");
        }
        if (btn) { btn.disabled = false; btn.textContent = btn.dataset.orig; }
        setTimeout(refreshDashboard, 500);
    }
    $("#btn-start").addEventListener("click", function () { serviceAction("start"); });
    $("#btn-stop").addEventListener("click", function () { serviceAction("stop"); });
    $("#btn-restart").addEventListener("click", function () { serviceAction("restart"); });

    // ---------- 连接测试 ----------
    async function runTest(kind, btn) {
        var label = { weflow: "WeFlow", douyin: "抖音解析", bilibili: "B站解析", xhs: "小红书解析", wechat: "微信" }[kind];
        var resultBox = $("#test-result");
        resultBox.style.display = "block";
        resultBox.className = "help-box";
        resultBox.innerHTML = "正在测试 " + label + " 连接...";
        if (btn) { btn.disabled = true; btn.dataset.orig = btn.textContent; btn.innerHTML = '<span class="spinner"></span> 测试中'; }
        try {
            var r = await api("/api/" + kind + "/test", { body: {} });
            var ok = r.ok;
            resultBox.className = "help-box" + (ok ? "" : " warn");
            resultBox.innerHTML = (ok ? "🟢 " : "🔴 ") + label + "：" + esc(r.detail || (ok ? "成功" : "失败"));
            toast(label + (ok ? " 连接成功" : " 连接失败"), ok ? "success" : "error");
        } catch (e) {
            resultBox.className = "help-box warn";
            resultBox.innerHTML = "🔴 请求失败：" + esc(e);
        }
        if (btn) { btn.disabled = false; btn.textContent = btn.dataset.orig; }
        setTimeout(refreshDashboard, 300);
    }
    $("#test-weflow").addEventListener("click", function () { runTest("weflow", this); });
    $("#test-douyin").addEventListener("click", function () { runTest("douyin", this); });
    $("#test-bilibili").addEventListener("click", function () { runTest("bilibili", this); });
    $("#test-xhs").addEventListener("click", function () { runTest("xhs", this); });
    $("#test-wechat").addEventListener("click", function () { runTest("wechat", this); });
    $("#test-weflow-2").addEventListener("click", function () { runTest("weflow", this); });
    $("#test-wechat-2").addEventListener("click", function () { runTest("wechat", this); });
    $("#test-douyin-2").addEventListener("click", function () { runTest("douyin", this); });
    $("#test-bili-2").addEventListener("click", function () { runTest("bilibili", this); });
    $("#test-xhs-2").addEventListener("click", function () { runTest("xhs", this); });

    // ---------- 环境检查 ----------
    $("#btn-env-check").addEventListener("click", async function () {
        var box = $("#env-result");
        box.style.display = "block";
        box.innerHTML = "正在检查...";
        var r = await api("/api/env/check");
        if (!r.ok) { box.innerHTML = "检查失败"; return; }
        var html = "";
        r.data.items.forEach(function (it) {
            var icon = it.status === "ok" ? "🟢" : "🔴";
            html += '<div class="flex gap-8 mb-8"><span style="width:120px;flex-shrink:0;font-weight:600;">' +
                icon + ' ' + esc(it.name) + '</span><span class="muted">' + esc(it.detail || "") + '</span></div>';
        });
        box.innerHTML = html;
    });

    // ---------- 配置中心 ----------
    // tab 切换
    $all("#config-tabs .tab").forEach(function (t) {
        t.addEventListener("click", function () {
            $all("#config-tabs .tab").forEach(function (x) { x.classList.remove("active"); });
            t.classList.add("active");
            var name = t.getAttribute("data-tab");
            $all(".config-panel").forEach(function (p) { p.style.display = "none"; });
            $("#panel-" + name).style.display = "block";
        });
    });

    // 密码显示/隐藏
    $all(".pw-toggle").forEach(function (btn) {
        btn.addEventListener("click", async function () {
            var target = $("#" + btn.getAttribute("data-target"));
            if (!target) return;
            if (target.type === "password") {
                target.type = "text";
                btn.textContent = "🙈";
                // 若当前是占位状态，拉取真实值填入
                if (!target.value || target.dataset.loaded !== "1") {
                    var r = await api("/api/config/secrets");
                    if (r.ok) {
                        if (target.id === "cfg-weflow-token") target.value = r.data.token || "";
                        target.dataset.loaded = "1";
                    }
                }
            } else {
                target.type = "password";
                btn.textContent = "👁";
            }
        });
    });

    var configData = null;

    async function loadConfig() {
        var r = await api("/api/config");
        if (!r.ok) return;
        configData = r.data;
        var c = r.data;
        // WeFlow
        $("#cfg-weflow-url").value = c.weflow.base_url || "";
        $("#cfg-weflow-token").value = "";
        $("#cfg-weflow-token").type = "password";
        $("#cfg-weflow-token").dataset.loaded = "0";
        $("#cfg-weflow-token").placeholder = c._meta.token_set ? "已配置（留空不修改）" : "请输入 Token";
        // 微信
        $("#cfg-wechat-whitelist").value = (c.wechat.group_whitelist || []).join("\n");
        $("#cfg-wechat-testmode").checked = !!c.wechat.test_mode;
        $("#cfg-wechat-quote").checked = !!c.wechat.quote_reply;
        $("#cfg-wechat-delete").value = c.wechat.delete_after_seconds;
        // 抖音
        $("#cfg-douyin-enabled").checked = !!c.douyin.enabled;
        $("#cfg-douyin-dir").value = c.douyin.download_dir || "";
        $("#cfg-douyin-mode").value = c.douyin.parse_mode || "real";
        // B站
        $("#cfg-bili-enabled").checked = !!c.bilibili.enabled;
        $("#cfg-bili-dir").value = c.bilibili.download_dir || "";
        $("#cfg-bili-quality").value = String(c.bilibili.quality || 64);
        $("#cfg-bili-auth").value = c.bilibili.auth || "";
        $("#cfg-bili-yutto").value = c.bilibili.yutto_path || "";
        $("#cfg-bili-ffmpeg").value = c.bilibili.ffmpeg_path || "";
        // 小红书
        $("#cfg-xhs-enabled").checked = !!c.xhs.enabled;
        $("#cfg-xhs-dir").value = c.xhs.download_dir || "";
        $("#cfg-xhs-cookie").value = c.xhs.cookie || "";
        // 高级
        $("#cfg-adv-port").value = c.advanced.port;
        $("#cfg-adv-push").checked = !!c.advanced.listen_push;
        $("#cfg-adv-poll").checked = !!c.advanced.listen_poll;
        $("#cfg-adv-pollint").value = c.advanced.poll_interval;
        $("#cfg-adv-lookback").value = c.advanced.lookback_limit;
        $("#cfg-adv-window").value = c.advanced.active_window;
        $("#cfg-adv-loglevel").value = c.advanced.log_level || "INFO";
        $("#cfg-adv-maxlog").value = c.advanced.max_log_lines;
        $("#cfg-adv-browser").checked = !!c.advanced.auto_open_browser;
    }

    function collectWeFlow() {
        return {
            weflow: {
                base_url: $("#cfg-weflow-url").value.trim(),
                token: $("#cfg-weflow-token").value.trim(),
            }
        };
    }
    function collectWechat() {
        var list = $("#cfg-wechat-whitelist").value.split("\n")
            .map(function (s) { return s.trim(); }).filter(Boolean);
        return {
            wechat: {
                group_whitelist: list,
                test_mode: $("#cfg-wechat-testmode").checked,
                quote_reply: $("#cfg-wechat-quote").checked,
                delete_after_seconds: parseInt($("#cfg-wechat-delete").value, 10) || 0,
            }
        };
    }
    function collectDouyin() {
        return {
            douyin: {
                enabled: $("#cfg-douyin-enabled").checked,
                parse_mode: $("#cfg-douyin-mode").value,
                download_dir: $("#cfg-douyin-dir").value.trim(),
            }
        };
    }
    function collectBilibili() {
        return {
            bilibili: {
                enabled: $("#cfg-bili-enabled").checked,
                download_dir: $("#cfg-bili-dir").value.trim(),
                quality: parseInt($("#cfg-bili-quality").value, 10) || 64,
                auth: $("#cfg-bili-auth").value.trim(),
                yutto_path: $("#cfg-bili-yutto").value.trim(),
                ffmpeg_path: $("#cfg-bili-ffmpeg").value.trim(),
            }
        };
    }
    function collectXhs() {
        return {
            xhs: {
                enabled: $("#cfg-xhs-enabled").checked,
                download_dir: $("#cfg-xhs-dir").value.trim(),
                cookie: $("#cfg-xhs-cookie").value.trim(),
            }
        };
    }
    function collectAdv() {
        return {
            advanced: {
                port: parseInt($("#cfg-adv-port").value, 10) || 8765,
                listen_push: $("#cfg-adv-push").checked,
                listen_poll: $("#cfg-adv-poll").checked,
                poll_interval: parseInt($("#cfg-adv-pollint").value, 10) || 3,
                lookback_limit: parseInt($("#cfg-adv-lookback").value, 10) || 10,
                active_window: parseInt($("#cfg-adv-window").value, 10) || 86400,
                log_level: $("#cfg-adv-loglevel").value,
                max_log_lines: parseInt($("#cfg-adv-maxlog").value, 10) || 500,
                auto_open_browser: $("#cfg-adv-browser").checked,
            }
        };
    }

    async function saveConfig(body, name) {
        var r = await api("/api/config", { body: body });
        if (r.ok) {
            toast((name || "配置") + "已保存", "success");
            await loadConfig();
        } else {
            toast("保存失败：" + (r.error || ""), "error");
        }
    }
    $("#save-weflow").addEventListener("click", function () { saveConfig(collectWeFlow(), "WeFlow 配置"); });
    $("#save-wechat").addEventListener("click", function () { saveConfig(collectWechat(), "微信配置"); });
    $("#save-douyin").addEventListener("click", function () { saveConfig(collectDouyin(), "抖音配置"); });
    $("#save-bili").addEventListener("click", function () { saveConfig(collectBilibili(), "B站配置"); });
    $("#save-xhs").addEventListener("click", function () { saveConfig(collectXhs(), "小红书配置"); });
    $("#save-adv").addEventListener("click", function () { saveConfig(collectAdv(), "高级设置"); });

    // 选择目录
    async function selectFolder(inputId) {
        var input = $("#" + inputId);
        var orig = input.value;
        toast("正在打开目录选择器...", "info");
        var r = await api("/api/select-folder", { body: {} });
        if (r.ok && r.data.folder) {
            input.value = r.data.folder;
        } else if (r.ok) {
            // 用户取消
        } else {
            toast("选择目录失败", "error");
        }
    }
    $("#btn-select-douyin").addEventListener("click", function () { selectFolder("cfg-douyin-dir"); });
    $("#btn-select-bili").addEventListener("click", function () { selectFolder("cfg-bili-dir"); });
    $("#btn-select-xhs").addEventListener("click", function () { selectFolder("cfg-xhs-dir"); });

    // ---------- 任务记录 ----------
    var TASK_STATUS = {
        success: ["success", "成功"], failed: ["failed", "失败"],
        processing: ["processing", "处理中"], pending: ["pending", "待处理"],
        deleted: ["deleted", "已删除"]
    };
    async function refreshTasks() {
        var r = await api("/api/tasks");
        if (!r.ok) return;
        var list = r.data.tasks || [];
        var body = $("#tasks-body");
        if (!list.length) {
            body.innerHTML = '<tr><td colspan="6" class="empty-state">暂无处理记录</td></tr>';
            return;
        }
        var html = "";
        list.forEach(function (t) {
            var st = TASK_STATUS[t.status] || ["pending", t.status || "待处理"];
            html += '<tr>' +
                '<td class="muted">' + esc(t.time) + '</td>' +
                '<td>' + esc(t.source) + '</td>' +
                '<td class="link-cell mono"><a href="' + esc(t.url) + '" target="_blank">' + esc(t.url) + '</a></td>' +
                '<td class="muted">' + esc(t.video || "—") + '</td>' +
                '<td><span class="badge ' + st[0] + '">' + st[1] + '</span></td>' +
                '<td class="muted">' + esc(t.error || "—") + '</td>' +
                '</tr>';
        });
        body.innerHTML = html;
    }
    $("#btn-clear-tasks").addEventListener("click", async function () {
        if (!confirm("确定清空所有处理记录吗？")) return;
        await api("/api/tasks/clear", { body: {} });
        toast("记录已清空", "success");
        refreshTasks();
    });

    // ---------- 运行日志 ----------
    var logSeq = 0;
    async function refreshLogs(reset) {
        if (reset) { logSeq = 0; $("#log-box").innerHTML = ""; }
        var r = await api("/api/logs?since=" + logSeq);
        if (!r.ok) return;
        var lines = r.data.lines || [];
        if (r.data.seq) logSeq = r.data.seq;
        var box = $("#log-box");
        var hadEmpty = box.querySelector(".log-empty");
        lines.forEach(function (l) {
            if (hadEmpty) { hadEmpty.remove(); hadEmpty = null; }
            var div = document.createElement("div");
            div.className = "log-line " + l.level;
            div.innerHTML = '<span class="t">[' + esc(l.time) + ']</span>' + esc(l.message);
            box.appendChild(div);
        });
        if (!box.children.length) {
            box.innerHTML = '<div class="log-empty">暂无日志</div>';
        }
        var autoScroll = $("#log-autoscroll").checked;
        if (autoScroll) box.scrollTop = box.scrollHeight;
    }
    $("#btn-clear-logs").addEventListener("click", async function () {
        await api("/api/logs/clear", { body: {} });
        $("#log-box").innerHTML = '<div class="log-empty">日志已清空</div>';
        toast("日志已清空", "success");
    });

    // ---------- 定时轮询 ----------
    setInterval(function () {
        if ($("#page-dashboard").classList.contains("active")) refreshDashboard();
        if ($("#page-logs").classList.contains("active")) refreshLogs(false);
        if ($("#page-tasks").classList.contains("active")) refreshTasks();
    }, 3000);

    // 日志更频繁轮询
    setInterval(function () {
        if ($("#page-logs").classList.contains("active")) refreshLogs(false);
    }, 1000);

    // ---------- 初始化 ----------
    loadConfig();
    refreshDashboard();
})();
