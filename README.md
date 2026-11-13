# Codex Personal Capabilities

个人 Codex 技能与插件的私人 Git 仓库。版本：`v1.1.1`（2026-11-13）。

包含 8 个个人工具/光学插件，以及 `personal-skills`、`dingtalk-skills` 两个技能集合。保留技能来源声明与上游许可证，不代表这些第三方技能均由仓库所有者编写。OpenAI 内置、官方商店下载包不复制；新电脑从官方插件目录重新安装。

## 换电脑安装

先安装 Git、Python 3.11+ 和可用的 Codex CLI；使用自己的 GitHub 账号登录以访问私人仓库。

```powershell
gh auth login
gh repo clone dengdenghua/codex-personal-capabilities
cd codex-personal-capabilities
git checkout v1.1.1
./Install.ps1
```

安装后开一个新的 Codex 对话。也可只装部分包：

```powershell
python scripts/install.py --plugins personal-skills projection-optics lens-toolkit
```

脚本使用官方 `codex plugin marketplace add` 与 `codex plugin add`。不会覆盖现有账号、全局指令或私人资料配置。若旧插件市场已指向失效路径，Codex 可能拒绝安装；先用官方市场管理命令修复对应旧条目，不要删除整个 Codex 配置。

## 更新和回退

```powershell
git fetch origin --tags
git checkout v1.1.1
python scripts/install.py
```

将版本标签替换为期望版本即可更新/回退。保留 checkout 目录，因为本地市场引用它。更新技能或插件时提升该插件清单版本；运行测试、刷新指纹、验证，再提交并创建新标签。不要重写已发布标签。

## 本地软件依赖

安装器自动创建六种 MCP 隔离运行环境并检查服务。商业软件、许可证、私人资料库由你配置，Blender 附加组件首次需要启用，详见 [RUNTIMES.md](RUNTIMES.md)。安装成功不是原生 CAD 建模或仿真验收通过。

## 隐私和内容边界

- 排除密码、令牌、账号配置、私人数据库、历史搜索记录、工程模型、截图、验证日志和旧投影技能的项目档案。
- 未验证嵌入元数据的二进制图纸模板、示例工程也不上传；需在本机配置。
- 保留通用方法、技能源码、公开来源引用与必要服务代码。本机路径已移除或改为本地配置。
- `provenance.json` 保存原文件指纹；`files.sha256.json` 保存最终文件指纹。完整排除清单只留在原电脑，不把私人文件路径写进仓库。
- 不自动迁移记忆、对话、授权或购买的软件；第三方登录由新电脑重新完成。

## 维护

```powershell
python -m unittest discover -s tests
python scripts/refresh_lock.py
python scripts/validate.py
```

隐私扫描检查常见密钥格式和禁传文件，不能代替人工审查。新增文件先检查内容，再刷新指纹。通用参考资料里有公开案例，不得当作用户当前项目已经验证的结论。
