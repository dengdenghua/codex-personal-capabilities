# REA 软件逆向 — Codex 个人插件

插件 ID：`rea-control@personal`，封装版本：`0.2.0`。

上游：[morluto/rea](https://github.com/morluto/rea)，固定 npm 包 `rea-agents@6.8.0`。
包含官方 MCP、对应版本的工作流及按需参考资料。中文 skill 负责本机连接方式。

## 本机目录

- 插件源码：`<LOCAL_PATH: configure on this computer>`
- REA：`<LOCAL_PATH: configure on this computer>`
- 独立 Node：`<LOCAL_PATH: configure on this computer>`
- Ghidra：`<LOCAL_PATH: configure on this computer>`
- JDK 21：`<LOCAL_PATH: configure on this computer>`
- 插件入口：`.codex-plugin/plugin.json`
- MCP 启动配置：`.mcp.json`
- Skill：`skills/rea-reverse-engineering/SKILL.md`

运行环境与插件缓存分开保存。Node 来自 nodejs.org，其 SHA256 与官方
`SHASUMS256.txt` 核对；安装凭据记录在运行环境的 `provenance.json`。
npm 锁文件记录 REA 与依赖版本及完整性摘要。

## 使用

安装后新建 Codex 聊天；若尚未出现工具，重启 Codex。可以直接说：

> 使用 REA 分析这个软件，说明关键功能如何实现并给出证据。

或调用 `$rea-reverse-engineering`。先查询 `binary_session`，按实际工具与引擎
可用性选择路径。JavaScript/Electron 静态分析不要求原生反编译器。
Ghidra 已作为默认原生引擎配置，并已完成真实 PE64 函数反编译验证。
IDA 的原生桥接组件已下载并校验；官方 IDA 9.x 安装与许可证仍待账户登录，
尚未启用。接入详情见 [引擎状态](runtime/engines.json)。

## 检查与维护

```powershell
codex plugin list --marketplace personal --json
& '<LOCAL_PATH> `
  '<LOCAL_PATH> `
  '<LOCAL_PATH>
```

重新安装插件使用 `codex plugin add rea-control@personal`。
运行环境恢复可在 `6.8.0` 目录使用其保留的 `package-lock.json` 执行 `npm ci`，
确保使用此插件的 Node 版本。当前 `.mcp.json` 为本机绝对路径配置；迁移电脑时
需要重建运行环境并修改对应路径。

更新时应一起更新固定运行版本、官方 workflow/references、来源清单及插件版本，
执行 MCP 检查后再安装新版。不要通过上游 `setup` 重复注册全局 MCP。

官方代码与工作流的 MIT 许可随插件保留在 `UPSTREAM-LICENSE`。
实际验证结果见 `verification/`。

原生引擎验证记录见 [Ghidra 验证](verification/GHIDRA.md)。
IDA 官方登录入口：<https://my.hex-rays.com/>。
