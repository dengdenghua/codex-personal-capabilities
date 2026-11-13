# Native runtime setup

本机运行配置放在 `~/.codex/personal-runtime.json`，绝不能提交到仓库。入口脚本默认使用 PATH 上的 `python`，再按本地配置启动各服务的专用 Python/Node。需要确保 Codex 能找到 Python 3.11+。

配置结构示例（路径需替换成这台电脑的实际安装位置）：

```json
{
  "servers": {
    "lighttools": {
      "command": "your-runtime-python",
      "args": ["your-checkout/plugins/lighttools-control/run_server.py"],
      "env": {"PYTHONUTF8": "1"}
    }
  }
}
```

| Server ID | 新电脑依赖 |
|---|---|
| lighttools | Windows、LightTools 许可证；包内 requirements.lock / pyproject.toml 和 run_server.py |
| zemax | Windows、OpticStudio 与 ZOS-API 许可证；包内 requirements-lock.txt 和 scripts/run_server.py |
| rea | Node.js、runtime/package-lock.json 固定的 rea-agents 6.8.0；可选 Ghidra/JDK/IDA 单独安装 |
| blender_official | Blender、原 Blender MCP 服务 `blmcp` 与连接配置；原服务环境未复制 |
| kicad | KiCad 与原 kicad_mcp_local.py 服务；原机外置适配器未复制 |
| solidworks_local | Windows、SOLIDWORKS 许可证与原 SolidWorksMCP 服务；原机外置适配器未复制 |

后三个原插件只包含技能及指向外部服务的配置。此仓库完整保存其可迁移技能，但不把外部工程目录混作插件上传。配置缺失时启动器会明确报缺失，不会伪装为可用服务或静默启动 CAD。仓库不是这些商业软件和外置服务的完整备份。

工具服务配置可设置 `command`、`args`、`cwd`、`env`；命令按参数数组执行，不使用 shell。凭据若确需配置，只存本机配置或操作系统凭据库。`PERSONAL_RUNTIME_CONFIG` 环境变量可指向另一个本地配置文件。

镜头知识库通过 `LENS_LIBRARY_ROOT` 或原技能支持的本机配置指定。光学记忆通过其标准库脚本和本机数据库保存；私人图谱与历史库未迁移。钉钉、支付宝、夸克等技能需按各自官方流程重新登录。
