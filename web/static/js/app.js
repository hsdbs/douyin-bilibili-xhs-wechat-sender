/* ================================================================
   媒体助手 · 自动化管理面板 前端控制交互逻辑
   Modern, Precision, Commercial-Grade Desktop Web UI Controller
   ================================================================ */
(function () {
    "use strict";

    // ---------- DOM 查找与基础工具 ----------
    function $(sel) { return document.querySelector(sel); }
    function $all(sel) { return document.querySelectorAll(sel); }

    // Toast 通知管理
    function toast(msg, type) {
        type = type || "info";
        var c = $("#toast-container");
        if (!c) return;
        var el = document.createElement("div");
        el.className = "toast " + type;

        var iconSvg = {
            success: '<svg class="icon text-success" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg>',
            error: '<svg class="icon text-danger" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>',
            warning: '<svg class="icon text-warning" viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
            info: '<svg class="icon text-primary" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>'
        }[type] || '';

        el.innerHTML = iconSvg + '<span>' + esc(msg) + '</span>';
        c.appendChild(el);

        setTimeout(function () {
            el.style.opacity = "0";
            el.style.transform = "translateX(20px)";
            el.style.transition = "all .3s ease";
            setTimeout(function () { el.remove(); }, 300);
        }, 3200);
    }

    // 剪贴板复制工具
    async function copyText(text, label) {
        if (!text) return;
        try {
            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(text);
            } else {
                var ta = document.createElement("textarea");
                ta.value = text;
                ta.style.position = "fixed";
                ta.style.left = "-9999px";
                document.body.appendChild(ta);
                ta.focus();
                ta.select();
                document.execCommand('copy');
                ta.remove();
            }
            toast((label || "内容") + " 已复制到剪贴板", "success");
        } catch (e) {
            toast("复制失败: " + e, "error");
        }
    }

    // 通用 HTTP API 请求
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

    // 字符串安全转义
    function esc(s) {
        if (s === null || s === undefined) return "";
        return String(s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    // 格式化运行时长
    function fmtUptime(sec) {
        if (!sec || sec < 0) return "—";
        var d = Math.floor(sec / 86400);
        var h = Math.floor((sec % 86400) / 3600);
        var m = Math.floor((sec % 3600) / 60);
        var s = Math.floor(sec % 60);
        var parts = [];
        if (d > 0) parts.push(d + " 天");
        if (h > 0 || d > 0) parts.push(h + " 小时");
        if (m > 0 || h > 0 || d > 0) parts.push(m + " 分");
        parts.push(s + " 秒");
        return parts.join(" ");
    }

    // ---------- 页面导航路由 ----------
    var pageTitles = {
        dashboard: "Dashboard 概览看板",
        config: "平台与服务配置中心",
        tasks: "任务记录与发送历史",
        logs: "实时运行日志控制台",
        settings: "高级网络与同步参数",
        about: "系统关于与运行帮助"
    };

    function switchPage(name) {
        $all(".page").forEach(function (p) { p.classList.remove("active"); });
        var target = $("#page-" + name);
        if (target) target.classList.add("active");
        $all("#nav a").forEach(function (a) {
            a.classList.toggle("active", a.getAttribute("data-page") === name);
        });
        var titleEl = $("#page-title");
        if (titleEl) titleEl.textContent = pageTitles[name] || name;

        if (name === "logs") refreshLogs(true);
        if (name === "tasks") refreshTasks();
        if (name === "dashboard") refreshDashboard();
        if (name === "config") loadConfig();
        if (name === "settings") loadConfig();
    }

    $all("#nav a").forEach(function (a) {
        a.addEventListener("click", function () {
            switchPage(a.getAttribute("data-page"));
        });
    });

    // ---------- 主题切换与持久化 ----------
    function applyTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("theme", theme);
        var textEl = $("#theme-toggle-text");
        var iconEl = $("#theme-icon");
        if (theme === "dark") {
            if (textEl) textEl.textContent = "深色";
            if (iconEl) iconEl.innerHTML = '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>';
        } else {
            if (textEl) textEl.textContent = "浅色";
            if (iconEl) iconEl.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>';
        }
    }
    var savedTheme = localStorage.getItem("theme") || "light";
    applyTheme(savedTheme);
    var themeToggleBtn = $("#theme-toggle");
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener("click", function () {
            var cur = document.documentElement.getAttribute("data-theme");
            applyTheme(cur === "dark" ? "light" : "dark");
        });
    }

    // ---------- Dashboard 状态与统计 ----------
    var STATUS_TEXT = {
        ok: ["ok", "正常"],
        error: ["error", "异常"],
        warn: ["warn", "警告"],
        checking: ["checking", "检测中"],
        unknown: ["unknown", "未检测"]
    };

    function statusDot(status) {
        var cls = STATUS_TEXT[status] ? STATUS_TEXT[status][0] : "unknown";
        return '<span class="status-dot ' + cls + '"></span>';
    }
    function statusText(status) {
        return STATUS_TEXT[status] ? STATUS_TEXT[status][1] : "未检测";
    }

    var serviceStartedAt = null;
    var serviceIsRunning = false;

    async function refreshDashboard() {
        var st = await api("/api/status");
        if (st && st.ok) {
            var d = st.data;
            renderStatus(d);
            renderService(d.service);
        }
        var stats = await api("/api/stats");
        if (stats && stats.ok) {
            renderStats(stats.data);
        }
    }

    // 平台模块 SVG 图标映射表
    var PLATFORM_SVGS = {
        wechat: '<svg class="icon" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>',
        weflow: '<svg class="icon" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>',
        douyin: '<svg class="icon" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>',
        bilibili: '<svg class="icon" viewBox="0 0 24 24"><rect x="2" y="7" width="20" height="15" rx="2" ry="2"></rect><polyline points="17 2 12 7 7 2"></polyline></svg>',
        xhs: '<svg class="icon" viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>',
        netease: '<svg class="icon" viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg>',
        qqmusic: '<svg class="icon" viewBox="0 0 24 24"><circle cx="5.5" cy="17.5" r="2.5"></circle><circle cx="17.5" cy="15.5" r="2.5"></circle><path d="M8 17V5l12-2v12"></path></svg>',
        ebook: '<svg class="icon" viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path><line x1="9" y1="7" x2="16" y2="7"></line><line x1="9" y1="11" x2="14" y2="11"></line></svg>',
        service: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="2"></circle><path d="M16.24 7.76a6 6 0 0 1 0 8.49m-8.48-.01a6 6 0 0 1 0-8.49m11.31-2.82a10 10 0 0 1 0 14.14m-14.14 0a10 10 0 0 1 0-14.14"></path></svg>'
    };

    // 当前正在执行测试的模块集合
    var activeTesting = {};

    function renderStatus(d) {
        var modules = [
            { key: "wechat", name: "微信客户端", testKey: "wechat" },
            { key: "weflow", name: "WeFlow 接口", testKey: "weflow" },
            { key: "douyin", name: "抖音无水印解析", testKey: "douyin" },
            { key: "bilibili", name: "B站混流解析", testKey: "bilibili" },
            { key: "xhs", name: "小红书图文/视频", testKey: "xhs" },
            { key: "netease", name: "网易云高保真", testKey: "netease" },
            { key: "qqmusic", name: "QQ 音乐解析", testKey: "qqmusic" },
            { key: "ebook", name: "电子书检索下载", testKey: "ebook" }
        ];

        var grid = $("#status-grid");
        if (!grid) return;

        // 如果网格内尚未初始化卡片结构，则整体渲染并绑定事件
        var existingCards = grid.querySelectorAll(".status-card");
        if (!existingCards || existingCards.length !== modules.length) {
            var html = "";
            modules.forEach(function (m) {
                var status = (d[m.key] ? d[m.key].status : "unknown") || "unknown";
                var detail = (d[m.key] ? d[m.key].detail : "") || "";
                var iconSvg = PLATFORM_SVGS[m.key] || '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle></svg>';

                html += '<div class="status-card" data-key="' + m.key + '" data-test="' + m.testKey + '">' +
                    '<div class="status-card-main">' +
                        '<div class="status-card-icon">' + iconSvg + '</div>' +
                        '<div class="status-card-info">' +
                            '<div class="st-name">' +
                                statusDot(status) +
                                '<span>' + esc(m.name) + '</span>' +
                            '</div>' +
                            '<div class="st-detail" title="' + esc(detail) + '">' +
                                (detail ? esc(detail) : ('状态：' + statusText(status))) +
                            '</div>' +
                        '</div>' +
                    '</div>' +
                    '<button class="btn-card-test" data-test="' + m.testKey + '">测试</button>' +
                '</div>';
            });
            grid.innerHTML = html;

            grid.querySelectorAll(".btn-card-test").forEach(function (btn) {
                btn.addEventListener("click", function (e) {
                    e.stopPropagation();
                    var testKey = btn.getAttribute("data-test");
                    runTest(testKey, btn);
                });
            });
            return;
        }

        // 若卡片已存在，则进行原位平滑 DOM 局部更新，不销毁 DOM 节点
        modules.forEach(function (m) {
            if (activeTesting[m.testKey]) return; // 测试中保持卡片自身测试状态

            var card = grid.querySelector('.status-card[data-key="' + m.key + '"]');
            if (!card) return;

            var status = (d[m.key] ? d[m.key].status : "unknown") || "unknown";
            var detail = (d[m.key] ? d[m.key].detail : "") || "";

            var dot = card.querySelector(".status-dot");
            if (dot) {
                var cls = STATUS_TEXT[status] ? STATUS_TEXT[status][0] : "unknown";
                dot.className = "status-dot " + cls;
            }

            var detailEl = card.querySelector(".st-detail");
            if (detailEl) {
                var displayText = detail ? detail : ("状态：" + statusText(status));
                detailEl.textContent = displayText;
                detailEl.title = displayText;
            }
        });
    }

    function renderStats(s) {
        var total = s.total || 0;
        var success = s.success || 0;
        var failed = s.failed || 0;
        var downloaded = s.downloaded || 0;
        var rate = total > 0 ? Math.round((success / total) * 100) : 100;

        var items = [
            {
                label: "今日消息处理",
                value: total,
                cls: "primary",
                iconClass: "primary",
                iconSvg: '<svg class="icon" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>'
            },
            {
                label: "成功解析发送 (" + rate + "%)",
                value: success,
                cls: "success",
                iconClass: "success",
                iconSvg: '<svg class="icon" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>'
            },
            {
                label: "异常拦截重试",
                value: failed,
                cls: "failed",
                iconClass: "failed",
                iconSvg: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>'
            },
            {
                label: "文件缓存下载",
                value: downloaded,
                cls: "",
                iconClass: "neutral",
                iconSvg: '<svg class="icon" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>'
            }
        ];

        var html = "";
        items.forEach(function (it) {
            html += '<div class="stat-card">' +
                '<div class="stat-info">' +
                    '<div class="stat-label">' + it.label + '</div>' +
                    '<div class="stat-value ' + it.cls + '">' + it.value + '</div>' +
                '</div>' +
                '<div class="stat-icon-wrap ' + it.iconClass + '">' +
                    it.iconSvg +
                '</div>' +
            '</div>';
        });

        var statsGrid = $("#stats-grid");
        if (statsGrid) statsGrid.innerHTML = html;
    }

    function renderService(svc) {
        if (!svc) return;
        var running = !!svc.running;
        serviceIsRunning = running;
        serviceStartedAt = svc.started_at || null;

        var badgeEl = $("#hero-badge");
        if (badgeEl) {
            badgeEl.className = "hero-status-badge " + (running ? "running" : "stopped");
        }

        var stateEl = $("#service-state");
        if (stateEl) {
            stateEl.textContent = running ? "运行中" : "未运行";
            stateEl.className = "badge " + (running ? "success" : "pending");
        }

        var pillEl = $("#service-pill");
        var pillText = $("#service-pill-text");
        if (pillEl) {
            pillEl.className = "service-pill " + (running ? "running" : "stopped");
        }
        if (pillText) {
            pillText.textContent = running ? "监听运行中" : "监听未运行";
        }

        var startEl = $("#service-start");
        if (startEl) {
            startEl.textContent = svc.started_at ? new Date(svc.started_at * 1000).toLocaleString("zh-CN") : "—";
        }

        var uptimeEl = $("#service-uptime");
        if (uptimeEl) {
            uptimeEl.textContent = fmtUptime(svc.uptime);
        }

        var btnStart = $("#btn-start");
        var btnStop = $("#btn-stop");
        if (btnStart) btnStart.disabled = running;
        if (btnStop) btnStop.disabled = !running;
    }

    // 前端秒级平滑心跳计时器
    setInterval(function () {
        if (serviceIsRunning && serviceStartedAt) {
            var now = Date.now() / 1000;
            var diff = Math.max(0, Math.floor(now - serviceStartedAt));
            var uptimeEl = $("#service-uptime");
            if (uptimeEl) uptimeEl.textContent = fmtUptime(diff);
        }
    }, 1000);

    // ---------- 服务主控 (Start / Stop / Restart) ----------
    async function serviceAction(action) {
        var btnMap = { start: $("#btn-start"), stop: $("#btn-stop"), restart: $("#btn-restart") };
        var btn = btnMap[action];
        var origHtml = btn ? btn.innerHTML : "";
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> 处理中...';
        }
        try {
            var r = await api("/api/service/" + action, { body: {} });
            toast(r.detail || (r.ok ? "操作成功" : "操作失败"), r.ok ? "success" : "error");
        } catch (e) {
            toast("请求异常: " + e, "error");
        }
        if (btn) {
            btn.innerHTML = origHtml;
        }
        setTimeout(refreshDashboard, 500);
    }

    var btnStart = $("#btn-start");
    var btnStop = $("#btn-stop");
    var btnRestart = $("#btn-restart");
    if (btnStart) btnStart.addEventListener("click", function () { serviceAction("start"); });
    if (btnStop) btnStop.addEventListener("click", function () { serviceAction("stop"); });
    if (btnRestart) btnRestart.addEventListener("click", function () { serviceAction("restart"); });

    // ---------- 连接诊断测试 (原位无跳动更新) ----------
    async function runTest(kind, btn) {
        var labelMap = {
            weflow: "WeFlow 接口",
            douyin: "抖音无水印解析",
            bilibili: "B站混流解析",
            xhs: "小红书解析",
            netease: "网易云音乐",
            qqmusic: "QQ 音乐",
            ebook: "电子书检索下载",
            wechat: "微信客户端"
        };
        var label = labelMap[kind] || kind;
        activeTesting[kind] = true;

        // 获取看板中对应的卡片并即时置于检测中状态
        var card = document.querySelector('.status-card[data-test="' + kind + '"]');
        var dot = card ? card.querySelector(".status-dot") : null;
        var detailEl = card ? card.querySelector(".st-detail") : null;
        var cardBtn = card ? card.querySelector(".btn-card-test") : null;

        if (dot) dot.className = "status-dot checking";
        if (detailEl) {
            detailEl.textContent = "正在测试连通性...";
            detailEl.title = "正在测试连通性...";
        }

        var isMatrixBtn = btn && btn.classList.contains("btn-card-test");
        var origHtml = btn ? btn.innerHTML : "";
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = isMatrixBtn ? '<span class="spinner dark"></span>' : '<span class="spinner dark"></span> 测试中...';
        }
        if (cardBtn && cardBtn !== btn) {
            cardBtn.disabled = true;
            cardBtn.innerHTML = '<span class="spinner dark"></span>';
        }

        try {
            var r = await api("/api/" + kind + "/test", { body: {} });
            var ok = !!(r && r.ok);
            var resultDetail = (r && r.detail) ? r.detail : (ok ? "连接正常" : "测试未通过");

            if (dot) dot.className = "status-dot " + (ok ? "ok" : "error");
            if (detailEl) {
                detailEl.textContent = resultDetail;
                detailEl.title = resultDetail;
            }

            toast(label + (ok ? " 测试成功" : " 测试失败") + (r && r.detail ? ("：" + r.detail) : ""), ok ? "success" : "error");
        } catch (e) {
            if (dot) dot.className = "status-dot error";
            if (detailEl) {
                detailEl.textContent = "请求异常 (" + e + ")";
                detailEl.title = "请求异常 (" + e + ")";
            }
            toast(label + " 连接测试失败: " + e, "error");
        } finally {
            delete activeTesting[kind];
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = origHtml || "测试";
            }
            if (cardBtn && cardBtn !== btn) {
                cardBtn.disabled = false;
                cardBtn.innerHTML = "测试";
            }
        }
    }

    // 绑定配置中心面板内的测试按钮
    var configTestBtns = {
        "test-weflow-2": "weflow",
        "test-wechat-2": "wechat",
        "test-douyin-2": "douyin",
        "test-bili-2": "bilibili",
        "test-xhs-2": "xhs",
        "test-netease-2": "netease",
        "test-qqmusic-2": "qqmusic",
        "test-ebook-2": "ebook"
    };
    for (var id in configTestBtns) {
        (function (btnId, kind) {
            var el = $("#" + btnId);
            if (el) {
                el.addEventListener("click", function () { runTest(kind, this); });
            }
        })(id, configTestBtns[id]);
    }

    // ---------- 环境自检诊断 ----------
    var btnEnvCheck = $("#btn-env-check");
    if (btnEnvCheck) {
        btnEnvCheck.addEventListener("click", async function () {
            var box = $("#env-result");
            if (!box) return;
            box.style.display = "block";
            box.innerHTML = '<div class="help-box"><span class="spinner dark"></span> 正在诊断运行环境与依赖项...</div>';
            var r = await api("/api/env/check");
            if (!r || !r.ok) {
                box.innerHTML = '<div class="help-box warn">环境诊断请求失败</div>';
                return;
            }
            var html = '<div class="card" style="margin-bottom:0;"><div class="card-title mb-12"><span class="title-accent"></span>系统环境与关键依赖自检清单</div><div class="grid grid-2">';
            (r.data.items || []).forEach(function (it) {
                var ok = it.status === "ok";
                var statusPill = ok
                    ? '<span class="badge success">● 正常</span>'
                    : '<span class="badge failed">● 异常</span>';
                html += '<div class="status-card" style="padding:10px 14px;">' +
                    '<div class="status-card-info">' +
                        '<div class="st-name">' + esc(it.name) + ' ' + statusPill + '</div>' +
                        '<div class="st-detail">' + esc(it.detail || "—") + '</div>' +
                    '</div>' +
                '</div>';
            });
            html += '</div></div>';
            box.innerHTML = html;
        });
    }

    // ---------- 配置中心交互 ----------
    // Tab 切换
    $all("#config-tabs .tab-item").forEach(function (tab) {
        tab.addEventListener("click", function () {
            $all("#config-tabs .tab-item").forEach(function (t) { t.classList.remove("active"); });
            tab.classList.add("active");
            var name = tab.getAttribute("data-tab");
            $all(".config-panel").forEach(function (p) { p.classList.remove("active"); });
            var targetPanel = $("#panel-" + name);
            if (targetPanel) targetPanel.classList.add("active");
        });
    });

    // 密码框明文切换与 Lazy 解密拉取
    $all(".pw-toggle").forEach(function (btn) {
        btn.addEventListener("click", async function () {
            var targetId = btn.getAttribute("data-target");
            var target = $("#" + targetId);
            if (!target) return;
            if (target.type === "password") {
                target.type = "text";
                btn.innerHTML = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>';
                if (!target.value || target.dataset.loaded !== "1") {
                    var r = await api("/api/config/secrets");
                    if (r && r.ok) {
                        if (target.id === "cfg-weflow-token") target.value = r.data.token || "";
                        target.dataset.loaded = "1";
                    }
                }
            } else {
                target.type = "password";
                btn.innerHTML = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
            }
        });
    });

    async function loadConfig() {
        var r = await api("/api/config");
        if (!r || !r.ok) return;
        var c = r.data;

        // WeFlow
        if ($("#cfg-weflow-url")) $("#cfg-weflow-url").value = (c.weflow && c.weflow.base_url) || "";
        if ($("#cfg-weflow-token")) {
            $("#cfg-weflow-token").value = "";
            $("#cfg-weflow-token").type = "password";
            $("#cfg-weflow-token").dataset.loaded = "0";
            $("#cfg-weflow-token").placeholder = (c._meta && c._meta.token_set) ? "已配置（留空不修改）" : "请输入 Token";
        }

        // 微信
        if ($("#cfg-wechat-whitelist")) $("#cfg-wechat-whitelist").value = ((c.wechat && c.wechat.group_whitelist) || []).join("\n");
        if ($("#cfg-wechat-testmode")) $("#cfg-wechat-testmode").checked = !!(c.wechat && c.wechat.test_mode);
        if ($("#cfg-wechat-quote")) $("#cfg-wechat-quote").checked = !!(c.wechat && c.wechat.quote_reply);
        if ($("#cfg-wechat-delete")) $("#cfg-wechat-delete").value = (c.wechat && c.wechat.delete_after_seconds !== undefined) ? c.wechat.delete_after_seconds : 180;

        // 抖音
        if ($("#cfg-douyin-enabled")) $("#cfg-douyin-enabled").checked = !!(c.douyin && c.douyin.enabled);
        if ($("#cfg-douyin-dir")) $("#cfg-douyin-dir").value = (c.douyin && c.douyin.download_dir) || "";
        if ($("#cfg-douyin-mode")) $("#cfg-douyin-mode").value = (c.douyin && c.douyin.parse_mode) || "real";

        // B站
        if ($("#cfg-bili-enabled")) $("#cfg-bili-enabled").checked = !!(c.bilibili && c.bilibili.enabled);
        if ($("#cfg-bili-dir")) $("#cfg-bili-dir").value = (c.bilibili && c.bilibili.download_dir) || "";
        if ($("#cfg-bili-quality")) $("#cfg-bili-quality").value = String((c.bilibili && c.bilibili.quality) || 64);
        if ($("#cfg-bili-auth")) $("#cfg-bili-auth").value = (c.bilibili && c.bilibili.auth) || "";
        if ($("#cfg-bili-yutto")) $("#cfg-bili-yutto").value = (c.bilibili && c.bilibili.yutto_path) || "";
        if ($("#cfg-bili-ffmpeg")) $("#cfg-bili-ffmpeg").value = (c.bilibili && c.bilibili.ffmpeg_path) || "";

        // 小红书
        if ($("#cfg-xhs-enabled")) $("#cfg-xhs-enabled").checked = !!(c.xhs && c.xhs.enabled);
        if ($("#cfg-xhs-dir")) $("#cfg-xhs-dir").value = (c.xhs && c.xhs.download_dir) || "";
        if ($("#cfg-xhs-cookie")) $("#cfg-xhs-cookie").value = (c.xhs && c.xhs.cookie) || "";

        // 网易云
        if ($("#cfg-netease-enabled")) $("#cfg-netease-enabled").checked = !!(c.netease && c.netease.enabled);
        if ($("#cfg-netease-dir")) $("#cfg-netease-dir").value = (c.netease && c.netease.download_dir) || "";
        if ($("#cfg-netease-cookie")) $("#cfg-netease-cookie").value = (c.netease && c.netease.cookie) || "";
        if ($("#cfg-netease-source")) $("#cfg-netease-source").value = (c.netease && c.netease.source) || "auto";
        if ($("#cfg-netease-quality")) $("#cfg-netease-quality").value = (c.netease && c.netease.quality) || "lossless";

        // QQ音乐
        if ($("#cfg-qqmusic-enabled")) $("#cfg-qqmusic-enabled").checked = !!(c.qqmusic && c.qqmusic.enabled);
        if ($("#cfg-qqmusic-dir")) $("#cfg-qqmusic-dir").value = (c.qqmusic && c.qqmusic.download_dir) || "";
        if ($("#cfg-qqmusic-cookie")) $("#cfg-qqmusic-cookie").value = (c.qqmusic && c.qqmusic.cookie) || "";

        // 电子书
        if ($("#cfg-ebook-enabled")) $("#cfg-ebook-enabled").checked = !!(c.ebook && c.ebook.enabled !== false);
        if ($("#cfg-ebook-dir")) $("#cfg-ebook-dir").value = (c.ebook && c.ebook.download_dir) || "";
        if ($("#cfg-ebook-prefix")) $("#cfg-ebook-prefix").value = (c.ebook && c.ebook.command_prefix) || "./下载";
        if ($("#cfg-ebook-source")) $("#cfg-ebook-source").value = (c.ebook && c.ebook.search_source) || "auto";

        // 高级设置
        if (c.advanced) {
            if ($("#cfg-adv-port")) $("#cfg-adv-port").value = c.advanced.port || 8765;
            if ($("#cfg-adv-push")) $("#cfg-adv-push").checked = !!c.advanced.listen_push;
            if ($("#cfg-adv-poll")) $("#cfg-adv-poll").checked = !!c.advanced.listen_poll;
            if ($("#cfg-adv-pollint")) $("#cfg-adv-pollint").value = c.advanced.poll_interval || 3;
            if ($("#cfg-adv-lookback")) $("#cfg-adv-lookback").value = c.advanced.lookback_limit || 10;
            if ($("#cfg-adv-window")) $("#cfg-adv-window").value = c.advanced.active_window || 86400;
            if ($("#cfg-adv-loglevel")) $("#cfg-adv-loglevel").value = c.advanced.log_level || "INFO";
            if ($("#cfg-adv-maxlog")) $("#cfg-adv-maxlog").value = c.advanced.max_log_lines || 500;
            if ($("#cfg-adv-browser")) $("#cfg-adv-browser").checked = !!c.advanced.auto_open_browser;
        }
    }

    // 收集各面板配置数据
    function collectWeFlow() {
        return {
            weflow: {
                base_url: $("#cfg-weflow-url").value.trim(),
                token: $("#cfg-weflow-token").value.trim()
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
                delete_after_seconds: parseInt($("#cfg-wechat-delete").value, 10) || 0
            }
        };
    }
    function collectDouyin() {
        return {
            douyin: {
                enabled: $("#cfg-douyin-enabled").checked,
                parse_mode: $("#cfg-douyin-mode").value,
                download_dir: $("#cfg-douyin-dir").value.trim()
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
                ffmpeg_path: $("#cfg-bili-ffmpeg").value.trim()
            }
        };
    }
    function collectXhs() {
        return {
            xhs: {
                enabled: $("#cfg-xhs-enabled").checked,
                download_dir: $("#cfg-xhs-dir").value.trim(),
                cookie: $("#cfg-xhs-cookie").value.trim()
            }
        };
    }
    function collectNetease() {
        return {
            netease: {
                enabled: $("#cfg-netease-enabled").checked,
                download_dir: $("#cfg-netease-dir").value.trim(),
                cookie: $("#cfg-netease-cookie").value.trim(),
                source: $("#cfg-netease-source").value,
                quality: $("#cfg-netease-quality").value
            }
        };
    }
    function collectQQMusic() {
        return {
            qqmusic: {
                enabled: $("#cfg-qqmusic-enabled").checked,
                download_dir: $("#cfg-qqmusic-dir").value.trim(),
                cookie: $("#cfg-qqmusic-cookie").value.trim()
            }
        };
    }
    function collectEbook() {
        return {
            ebook: {
                enabled: $("#cfg-ebook-enabled").checked,
                download_dir: $("#cfg-ebook-dir").value.trim(),
                command_prefix: ($("#cfg-ebook-prefix") ? $("#cfg-ebook-prefix").value.trim() : "") || "./下载",
                search_source: $("#cfg-ebook-source").value,
                auto_convert_txt: true
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
                auto_open_browser: $("#cfg-adv-browser").checked
            }
        };
    }

    async function saveConfig(body, name, btn) {
        var origHtml = btn ? btn.innerHTML : "";
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> 保存中...';
        }
        var r = await api("/api/config", { body: body });
        if (r && r.ok) {
            toast((name || "配置") + " 已成功保存", "success");
            await loadConfig();
        } else {
            toast("保存失败：" + ((r && r.error) || "未知错误"), "error");
        }
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = origHtml;
        }
    }

    var saveMap = [
        { id: "save-weflow", fn: collectWeFlow, name: "WeFlow 配置" },
        { id: "save-wechat", fn: collectWechat, name: "微信发送配置" },
        { id: "save-douyin", fn: collectDouyin, name: "抖音配置" },
        { id: "save-bili", fn: collectBilibili, name: "B站配置" },
        { id: "save-xhs", fn: collectXhs, name: "小红书配置" },
        { id: "save-netease", fn: collectNetease, name: "网易云配置" },
        { id: "save-qqmusic", fn: collectQQMusic, name: "QQ 音乐配置" },
        { id: "save-ebook", fn: collectEbook, name: "电子书配置" },
        { id: "save-adv", fn: collectAdv, name: "高级网络参数" }
    ];

    saveMap.forEach(function (it) {
        var el = $("#" + it.id);
        if (el) {
            el.addEventListener("click", function () {
                saveConfig(it.fn(), it.name, this);
            });
        }
    });

    // ================= 可视化目录选择模态窗逻辑 =================
    var currentPickerTargetInput = null;
    var currentFolderBrowsingPath = "";
    var selectedFolderPath = "";

    var folderModal = $("#modal-folder-picker");
    var folderPathInput = $("#folder-current-path");
    var folderItemsList = $("#folder-items-list");
    var folderDrivesList = $("#folder-drives-list");
    var btnFolderUp = $("#btn-folder-up");
    var btnFolderGo = $("#btn-folder-go");
    var btnFolderMkdir = $("#btn-folder-mkdir");
    var btnTryNativePicker = $("#btn-try-native-picker");
    var btnConfirmFolder = $("#btn-confirm-folder");
    var btnCancelFolder = $("#btn-cancel-folder");
    var btnCloseFolderModal = $("#btn-close-folder-modal");

    async function openFolderPicker(targetInputId) {
        currentPickerTargetInput = $("#" + targetInputId);
        var initialPath = currentPickerTargetInput ? currentPickerTargetInput.value.trim() : "";
        if (folderModal) folderModal.style.display = "flex";
        await loadFolderList(initialPath);
    }

    function closeFolderPicker() {
        if (folderModal) folderModal.style.display = "none";
    }

    async function loadFolderList(path) {
        if (folderItemsList) {
            folderItemsList.innerHTML = '<div class="folder-empty"><span class="spinner dark"></span> 加载目录中...</div>';
        }
        var url = "/api/fs/list" + (path ? "?path=" + encodeURIComponent(path) : "");
        var res = await api(url);
        if (!res || !res.ok || !res.data) {
            if (folderItemsList) folderItemsList.innerHTML = '<div class="folder-empty text-danger">读取目录失败: ' + ((res && res.error) || "未知错误") + '</div>';
            return;
        }
        var data = res.data;
        currentFolderBrowsingPath = data.current_path || path || "";
        selectedFolderPath = currentFolderBrowsingPath;
        if (folderPathInput) folderPathInput.value = currentFolderBrowsingPath;

        // 渲染驱动器切换按钮
        if (folderDrivesList && data.drives) {
            var drivesHtml = "";
            data.drives.forEach(function (drv) {
                drivesHtml += '<button class="drive-btn" type="button" data-path="' + drv.path + '">' + drv.name + '</button>';
            });
            folderDrivesList.innerHTML = drivesHtml;
            folderDrivesList.querySelectorAll(".drive-btn").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    loadFolderList(this.getAttribute("data-path"));
                });
            });
        }

        // 渲染子文件夹
        if (folderItemsList) {
            if (!data.folders || data.folders.length === 0) {
                folderItemsList.innerHTML = '<div class="folder-empty">此目录下无可见子文件夹（可直接点击下方「确定选择该目录」）</div>';
            } else {
                var html = "";
                data.folders.forEach(function (f) {
                    html += '<div class="folder-item" data-path="' + f.path + '">' +
                        '<div class="folder-item-left">' +
                            '<span class="folder-item-icon"><svg class="icon icon-md" viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg></span>' +
                            '<span class="folder-item-name">' + f.name + '</span>' +
                        '</div>' +
                        '<span class="folder-item-hint">双击进入</span>' +
                    '</div>';
                });
                folderItemsList.innerHTML = html;

                var items = folderItemsList.querySelectorAll(".folder-item");
                items.forEach(function (item) {
                    item.addEventListener("click", function () {
                        items.forEach(function (it) { it.classList.remove("active"); });
                        this.classList.add("active");
                        selectedFolderPath = this.getAttribute("data-path");
                        if (folderPathInput) folderPathInput.value = selectedFolderPath;
                    });
                    item.addEventListener("dblclick", function () {
                        loadFolderList(this.getAttribute("data-path"));
                    });
                });
            }
        }

        // 上级按钮状态
        if (btnFolderUp) {
            btnFolderUp.disabled = !data.parent_path;
            btnFolderUp.onclick = function () {
                if (data.parent_path) loadFolderList(data.parent_path);
            };
        }
    }

    if (btnFolderGo && folderPathInput) {
        btnFolderGo.addEventListener("click", function () {
            loadFolderList(folderPathInput.value.trim());
        });
        folderPathInput.addEventListener("keydown", function (e) {
            if (e.key === "Enter") loadFolderList(this.value.trim());
        });
    }

    if (btnFolderMkdir) {
        btnFolderMkdir.addEventListener("click", async function () {
            var name = prompt("请输入要新建的文件夹名称：");
            if (!name || !name.trim()) return;
            var res = await api("/api/fs/mkdir", {
                body: { parent_path: currentFolderBrowsingPath, name: name.trim() }
            });
            if (res && res.ok && res.data.folder) {
                toast("已成功创建文件夹: " + name, "success");
                await loadFolderList(res.data.folder);
            } else {
                toast("创建文件夹失败: " + ((res && res.error) || "未知错误"), "error");
            }
        });
    }

    if (btnConfirmFolder) {
        btnConfirmFolder.addEventListener("click", function () {
            var chosen = folderPathInput ? folderPathInput.value.trim() : selectedFolderPath;
            if (chosen && currentPickerTargetInput) {
                currentPickerTargetInput.value = chosen;
                toast("已选择目录: " + chosen, "success");
            }
            closeFolderPicker();
        });
    }

    if (btnCancelFolder) btnCancelFolder.addEventListener("click", closeFolderPicker);
    if (btnCloseFolderModal) btnCloseFolderModal.addEventListener("click", closeFolderPicker);

    if (btnTryNativePicker) {
        btnTryNativePicker.addEventListener("click", async function () {
            toast("正在请求系统原生选择窗口...", "info");
            var r = await api("/api/select-folder", { body: {} });
            if (r && r.ok && r.data && r.data.folder) {
                if (currentPickerTargetInput) currentPickerTargetInput.value = r.data.folder;
                if (folderPathInput) folderPathInput.value = r.data.folder;
                toast("原生窗口已选取: " + r.data.folder, "success");
                closeFolderPicker();
            } else {
                toast("已取消或未选择目录", "info");
            }
        });
    }

    // 绑定所有「浏览目录」按钮
    var dirPickers = [
        { btn: "btn-select-douyin", target: "cfg-douyin-dir" },
        { btn: "btn-select-bili", target: "cfg-bili-dir" },
        { btn: "btn-select-xhs", target: "cfg-xhs-dir" },
        { btn: "btn-select-netease", target: "cfg-netease-dir" },
        { btn: "btn-select-qqmusic", target: "cfg-qqmusic-dir" },
        { btn: "btn-select-ebook", target: "cfg-ebook-dir" }
    ];
    dirPickers.forEach(function (dp) {
        var el = $("#" + dp.btn);
        if (el) {
            el.addEventListener("click", function () {
                openFolderPicker(dp.target);
            });
        }
    });

    // ---------- 任务记录 ----------
    var TASK_STATUS = {
        success: ["success", "成功"],
        failed: ["failed", "失败"],
        processing: ["processing", "处理中"],
        pending: ["pending", "待处理"],
        deleted: ["deleted", "已删除"]
    };

    var cachedTasks = [];
    var currentTaskFilter = "all";
    var taskSearchTerm = "";

    async function refreshTasks() {
        var r = await api("/api/tasks");
        if (!r || !r.ok) return;
        cachedTasks = r.data.tasks || [];
        renderFilteredTasks();
    }

    function renderFilteredTasks() {
        var list = cachedTasks.filter(function (t) {
            var stMatch = currentTaskFilter === "all" || t.status === currentTaskFilter;
            if (!stMatch) return false;
            if (!taskSearchTerm) return true;
            var text = (t.source + " " + t.url + " " + (t.video || "") + " " + (t.error || "")).toLowerCase();
            return text.indexOf(taskSearchTerm.toLowerCase()) !== -1;
        });

        var body = $("#tasks-body");
        if (!body) return;
        if (!list.length) {
            body.innerHTML = '<tr><td colspan="6" class="empty-state">' +
                '<svg class="icon icon-lg text-muted mb-8" style="display:block;margin:0 auto;" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>' +
                '暂无匹配的任务处理记录' +
            '</td></tr>';
            return;
        }

        var html = "";
        list.forEach(function (t) {
            var st = TASK_STATUS[t.status] || ["pending", t.status || "待处理"];
            var isGroup = (t.source || "").indexOf("@chatroom") !== -1;
            var sourceBadge = isGroup
                ? '<span class="badge" style="background:var(--primary-soft); color:var(--primary-text);">' + esc(t.source) + '</span>'
                : '<span class="badge" style="background:var(--bg-surface-hover); color:var(--text-secondary);">' + esc(t.source) + '</span>';

            html += '<tr>' +
                '<td class="mono text-muted">' + esc(t.time) + '</td>' +
                '<td>' + sourceBadge + '</td>' +
                '<td class="link-cell mono">' +
                    '<a href="' + esc(t.url) + '" target="_blank" rel="noreferrer" title="' + esc(t.url) + '">' +
                        esc(t.url) +
                    '</a>' +
                '</td>' +
                '<td class="text-secondary" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + esc(t.video || "") + '">' +
                    (t.video ? esc(t.video) : '<span class="text-muted">—</span>') +
                '</td>' +
                '<td><span class="badge ' + st[0] + '">' + st[1] + '</span></td>' +
                '<td class="text-muted" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + esc(t.error || "") + '">' +
                    (t.error ? esc(t.error) : '<span class="text-muted">—</span>') +
                '</td>' +
            '</tr>';
        });
        body.innerHTML = html;
    }

    // 绑定任务状态过滤与搜索
    $all("#task-filter-chips .log-chip").forEach(function (chip) {
        chip.addEventListener("click", function () {
            $all("#task-filter-chips .log-chip").forEach(function (c) { c.classList.remove("active"); });
            chip.classList.add("active");
            currentTaskFilter = chip.getAttribute("data-filter") || "all";
            renderFilteredTasks();
        });
    });

    var taskSearchInput = $("#task-search-input");
    if (taskSearchInput) {
        taskSearchInput.addEventListener("input", function () {
            taskSearchTerm = this.value.trim();
            renderFilteredTasks();
        });
    }

    var btnClearTasks = $("#btn-clear-tasks");
    if (btnClearTasks) {
        btnClearTasks.addEventListener("click", async function () {
            if (!confirm("确定清空所有本地历史任务记录吗？")) return;
            await api("/api/tasks/clear", { body: {} });
            toast("处理记录已成功清空", "success");
            refreshTasks();
        });
    }

    // ---------- 运行日志控制台 ----------
    var logSeq = 0;
    var rawLogs = [];
    var currentLogLevel = "ALL";
    var logSearchTerm = "";

    function renderFilteredLogs() {
        var box = $("#log-box");
        if (!box) return;

        var filtered = rawLogs.filter(function (l) {
            var lvlMatch = currentLogLevel === "ALL" || l.level === currentLogLevel;
            if (!lvlMatch) return false;
            if (!logSearchTerm) return true;
            var text = (l.time + " " + l.level + " " + l.message).toLowerCase();
            return text.indexOf(logSearchTerm.toLowerCase()) !== -1;
        });

        var countEl = $("#log-count");
        if (countEl) countEl.textContent = filtered.length + " 行";

        if (!filtered.length) {
            box.innerHTML = '<div class="log-empty">暂无匹配的日志输出</div>';
            return;
        }

        var html = "";
        filtered.forEach(function (l) {
            html += '<div class="log-line ' + esc(l.level) + '">' +
                '<span class="log-time">[' + esc(l.time) + ']</span>' +
                '<span class="log-lvl ' + esc(l.level) + '">' + esc(l.level) + '</span>' +
                '<span class="log-msg">' + esc(l.message) + '</span>' +
            '</div>';
        });
        box.innerHTML = html;

        var autoScroll = $("#log-autoscroll") && $("#log-autoscroll").checked;
        if (autoScroll) {
            box.scrollTop = box.scrollHeight;
        }
    }

    async function refreshLogs(reset) {
        if (reset) {
            logSeq = 0;
            rawLogs = [];
            var box = $("#log-box");
            if (box) box.innerHTML = "";
        }
        var r = await api("/api/logs?since=" + logSeq);
        if (!r || !r.ok) return;

        var lines = r.data.lines || [];
        if (r.data.seq) logSeq = r.data.seq;

        if (lines.length > 0) {
            rawLogs = rawLogs.concat(lines);
            // 限制前端内存日志缓存行数
            if (rawLogs.length > 1000) rawLogs = rawLogs.slice(rawLogs.length - 1000);
            renderFilteredLogs();
        }
    }

    // 绑定日志过滤器与搜索
    $all("#log-filter-chips .log-chip").forEach(function (chip) {
        chip.addEventListener("click", function () {
            $all("#log-filter-chips .log-chip").forEach(function (c) { c.classList.remove("active"); });
            chip.classList.add("active");
            currentLogLevel = chip.getAttribute("data-lvl") || "ALL";
            renderFilteredLogs();
        });
    });

    var logSearchInput = $("#log-search");
    if (logSearchInput) {
        logSearchInput.addEventListener("input", function () {
            logSearchTerm = this.value.trim();
            renderFilteredLogs();
        });
    }

    var btnCopyLogs = $("#btn-copy-logs");
    if (btnCopyLogs) {
        btnCopyLogs.addEventListener("click", function () {
            if (!rawLogs.length) {
                toast("当前无日志可复制", "warning");
                return;
            }
            var text = rawLogs.map(function (l) {
                return "[" + l.time + "] [" + l.level + "] " + l.message;
            }).join("\n");
            copyText(text, "运行日志");
        });
    }

    var btnClearLogs = $("#btn-clear-logs");
    if (btnClearLogs) {
        btnClearLogs.addEventListener("click", async function () {
            await api("/api/logs/clear", { body: {} });
            rawLogs = [];
            logSeq = 0;
            var box = $("#log-box");
            if (box) box.innerHTML = '<div class="log-empty">日志已清空</div>';
            toast("系统日志已清空", "success");
        });
    }

    // ---------- 定时轮询与启动初始化 ----------
    setInterval(function () {
        if ($("#page-dashboard") && $("#page-dashboard").classList.contains("active")) {
            refreshDashboard();
        }
        if ($("#page-tasks") && $("#page-tasks").classList.contains("active")) {
            refreshTasks();
        }
    }, 3000);

    // 实时日志以 1s 频率轮询
    setInterval(function () {
        if ($("#page-logs") && $("#page-logs").classList.contains("active")) {
            refreshLogs(false);
        }
    }, 1000);

    // 启动初始加载
    loadConfig();
    refreshDashboard();
})();

