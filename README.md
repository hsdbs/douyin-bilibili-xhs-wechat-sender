# 抖音视频自动发送 · 可视化管理面板

把「抖音链接自动解析并发送微信」的后台脚本，升级为普通用户可直接使用的本地 Web 管理软件。

## 一、快速开始

### 方式 A：直接使用打包好的 EXE（推荐给普通用户）

1. 双击 `dist\抖音视频自动发送\抖音视频自动发送.exe`
2. 程序自动启动本地服务并打开浏览器，进入管理面板
3. 依次配置：WeFlow → 抖音 Cookie → 微信 → 测试连接 → 启动监听

> 注意：整个 `dist\抖音视频自动发送\` 文件夹都要保留（EXE 依赖同级 `_internal` 目录）。

### 方式 B：开发环境运行

```bash
# 启动管理面板（自动打开浏览器）
启动自动发送.cmd
# 或
.venv\Scripts\python.exe app.py
```

## 二、使用步骤

| 步骤 | 操作 |
|------|------|
| ① | 配置中心 → WeFlow：填地址与 Token，点「测试连接」 |
| ② | 配置中心 → 抖音：填 Cookie，点「测试解析」 |
| ③ | 配置中心 → 微信：确认群白名单、测试模式；确认微信已登录运行 |
| ④ | Dashboard → 点「启动监听」 |

之后程序会持续监听微信消息，发现抖音链接后自动解析、下载、发送给对应联系人。

## 三、页面功能

- **Dashboard**：系统状态（微信/WeFlow/抖音/监听）、今日统计、服务控制、连接测试、环境检查
- **配置中心**：WeFlow / 抖音 / 微信 / 视频 四类配置，全部可视化
- **任务记录**：每次处理的时间、来源、链接、状态、错误原因
- **运行日志**：实时刷新、自动滚动、错误高亮、可清空
- **高级设置**：端口、日志等级等
- **关于**：使用步骤、外部依赖说明

## 四、目录结构

```
抖音视频解析自动发送/
├── app.py                 # 程序入口（启动 Web 服务 + 自动开浏览器）
├── main.py                # 业务逻辑（抖音解析/微信发送，改造为可停止 worker）
├── mapping.py             # WeFlow wxid↔显示名 映射（配置化）
├── douyin_parser.py       # 抖音解析下载（配置化）
├── core/                  # 核心模块
│   ├── config.py          # 统一配置管理（config/config.json）
│   ├── logger.py          # 日志（环形缓冲 + 脱敏）
│   ├── state.py           # 运行时状态
│   └── tasks.py           # 任务记录 + 统计
├── web/
│   ├── server.py          # Web 后端（标准库 http.server，零依赖）
│   └── static/            # 前端（HTML/CSS/JS 单页应用）
├── config/config.example.json # 配置模板（不含真实 Token/群白名单，提交到仓库）
├── config/config.json     # 用户配置（首次运行自动生成，已被 .gitignore 忽略）
├── data/                  # 运行数据（去重/映射/删除队列/任务记录）
├── logs/                  # 运行日志
├── videos/                # 下载的视频（发送后按策略自动删除）
├── douyin_sender.spec     # PyInstaller 打包配置
├── 启动自动发送.cmd        # 开发环境启动器
└── 打包EXE.cmd             # 一键打包脚本
```

## 五、打包 EXE

```bash
# 安装打包工具
uv pip install --python .venv\Scripts\python.exe pyinstaller

# 打包（onedir，无控制台）
.venv\Scripts\pyinstaller.exe douyin_sender.spec --noconfirm --clean
# 或直接双击「打包EXE.cmd」
```

产物：`dist\抖音视频自动发送\抖音视频自动发送.exe`

## 六、外部依赖（无法打包进 EXE）

- **微信**：需已安装并登录（Weixin.exe），发送靠 wxauto4 自动化
- **WeFlow**：需已启动（默认 http://127.0.0.1:5031），并在「设置 → API 服务」中开启「主动推送」，用于实时推送微信消息
- **抖音 Cookie**：需有效（网页版登录 Cookie，过期需重新获取）

## 七、安全说明

- Web 服务仅监听 `127.0.0.1`，不对外网开放
- WeFlow Token、抖音 Cookie 默认隐藏、API 脱敏返回、不写入普通日志
- 视频删除仅作用于「视频保存目录」内文件，不会误删其它文件
- `config/config.json`（含真实 WeFlow Token 与微信群白名单）及 `douyin_cookie.txt` 已被 `.gitignore` 忽略，不会提交到仓库；请复制 `config/config.example.json` 为 `config.json` 后填写自己的 Token 与群白名单
