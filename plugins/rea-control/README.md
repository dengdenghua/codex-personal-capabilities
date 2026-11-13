# REA 软件逆向 — 可迁移个人插件

上游：[morluto/rea](https://github.com/morluto/rea)，固定 npm 包 `rea-agents@6.8.0`，插件版本 1.1.0。官方代码与工作流的 MIT 许可随插件保留在 `UPSTREAM-LICENSE`。

在仓库根目录运行 `./Install.ps1`。安装器创建独立 Node/npm 环境、执行锁文件安装、生成仅保存在本机的启动配置，再用官方 Codex CLI 注册插件。不会复制旧电脑的账号或分析项目。详细依赖和回退步骤见根目录 `RUNTIMES.md`。

安装后新建 Codex 对话，使用 `$rea-reverse-engineering`。先查询实际引擎可用性。JavaScript/Electron 静态分析不要求原生反编译器；Ghidra、JDK、IDA 和对应许可证由用户另装，本包不默认声明其可用。

`python scripts/runtime_manager.py doctor --servers rea` 检查 MCP 握手与工具清单，不执行文件分析。仓库保留版本锁和源码完整性清单，实际环境、日志及配置在仓库外。
