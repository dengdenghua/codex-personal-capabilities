# 换机安装与依赖检查 — 1.1.0

仓库包含 Blender、KiCad、SolidWorks 的外置 MCP 源码，以及 LightTools、Zemax 服务和 REA 版本锁定清单。不复制旧电脑的虚拟环境或账号配置。

## 一键安装

先安装 Git、Python 3.11+ 和 Codex。商业软件和许可证由你安装。在仓库目录运行 `./Install.ps1`，也可运行 `python scripts/install.py`。只安装技能用 `python scripts/install.py --skills-only`。

Linux/macOS 跳过 Windows 专用的 SolidWorks、LightTools、Zemax 服务，保留技能。本轮原生运行验证以 Windows 为准。

安装器会验证指纹，在 `~/.codex/personal-runtimes/1.1.0/` 按服务和源码指纹创建独立 Python 环境，从 PyPI 安装锁定依赖。REA 用 npm 锁文件。优先使用符合 REA 要求的 Node.js（22.23.4+ 的 22.x、24.22.1+ 的 24.x 或 >=26.12.1）；Windows x64 缺少合适 Node 时，从 nodejs.org 下载固定的 24.22.1 并核对官方 SHA256，不修改系统 PATH。

通过注册表、环境变量和标准目录发现软件，生成本机 `~/.codex/personal-runtime.json`。保留其他自定义服务配置，只自动更新本安装器管理的服务，更新前保留 `.previous.json`。使用官方 Codex CLI 安装插件，将实际 Python 路径写入本机已安装模板，避免 Windows Store 的 python 占位程序。

检查只执行 MCP initialize 和 tools/list，不打开、修改或运行 CAD/光学项目。下载或启动失败返回非零状态，保留本地 install.log；修复后重跑复用已完成环境。版本目录不覆盖正在运行的旧代码。

## 依赖检查

运行 `python scripts/runtime_manager.py doctor`。doctor.json 保存在本地运行目录，分别报告 MCP 状态和工具数、商业软件发现结果、许可证 not_checked。环境损坏时可运行 `python scripts/runtime_manager.py install --repair --servers 服务名` 重装依赖；正常重跑会复用已安装环境。

可执行文件存在不代表许可证有效；MCP tools/list 成功不代表原生软件操作已验收。未发现软件可指定路径后再检查。

## Blender 附加组件

从随包官方源码生成的 `blender-mcp-addon.zip` 放在 Blender runtime 版本目录。首次在 Blender 扩展设置中“从磁盘安装”此 ZIP 并启用。安装器不启动 Blender、不改写正在使用的偏好文件。默认仅连接 127.0.0.1:9876。附加组件连接不由 tools/list 测试覆盖。

## 本机路径

非标准安装位置，在安装前设置环境变量或编辑本机配置的 env：

| 服务 | 变量 |
|---|---|
| Blender | BLENDER_PATH、BLENDER_MCP_HOST、BLENDER_MCP_PORT |
| KiCad | KICAD_CLI（发现用）、KICAD_SYMBOL_DIR |
| SolidWorks | SOLIDWORKS_EXE、SOLIDWORKS_TLB、SOLIDWORKS_TEMPLATES；Flow 可选 SOLIDWORKS_FLOW_HOME |
| LightTools | LIGHTTOOLS_HOME |
| Zemax | ZEMAX_EXE（发现用）、ZEMAX_ROOT（Zemax 数据目录，供原生 ZOS-API 连接使用） |
| REA | 可选 GHIDRA_INSTALL_DIR、JAVA_HOME；这些分析引擎另装，未默认宣称可用 |

SolidWorks 模板若存在多个版本不猜选。模板不上传，调用时仍需验证模板与目标实例。

## 私人数据和回退

SolidWorks 的队列、锁和 Flow 状态，以及 LightTools 日志和恢复文件，写到本地 personal-runtimes/private-data，不写入仓库。镜头库、光学记忆、模型、密码、令牌和许可证均未复制。

切换版本标签后重跑安装，切换后续会话使用的版本；不会强制结束运行中的旧进程。恢复上次配置前先正常结束相关任务，再用 .previous.json 恢复配置并重开 Codex 对话。

MCP 源码已齐全，不依赖旧电脑的外置服务目录。商业软件/API、账号登录、私人数据库以及 Blender 首次启用仍属于各机条件。
