# 光学知识库：安装、私人备份和换机恢复

公开仓库包含 Optics Workbench MCP 源码、技能、安装器、迁移工具和合成测试。私人图谱、记忆、数据库、资料原文和工程模型均不随仓库发布。原始服务版本为 0.4.0，MIT 许可；本插件扩展版本为 1.2.0。

## 安装服务

先安装 Python 3.11+、Git 和 Codex。在本仓库运行 `./Install.ps1`，默认安装光学服务和其他插件。只装光学服务可运行：

```powershell
python scripts/install.py --plugins optics-workbench lens-toolkit projection-optics
```

光学服务只依赖 Python 标准库，无需商业软件或许可证。商业仿真仍使用各自的软件和授权。未恢复私人库时是独立演示环境，不能把演示数据当成原知识库。

## 私人备份

命令中的位置由本机配置提供，不能把这些配置提交公开仓库。先核对所有来源的身份，旧路径可在明确指定的检索根目录中按文件名、大小和 SHA256 找回。

```powershell
python scripts/optics_private.py plan --workbench-config <本机工作台配置> --lens-root <镜头库目录> --memory <个人续接记忆数据库> --search-root <原始资料根目录> --output <私人目录>/private-plan.json
python scripts/optics_private.py backup --plan <私人目录>/private-plan.json --archive <私人目录>/optics.private.zip
```

可以重复指定 `--search-root`。备份包括工作台、图谱、镜头库与续接记忆的 SQLite 一致性快照、技能中的私有证据、配置的 catalog/audit 和能找回的已索引原始文件。按内容去重存储；原始路径和证据语义保持不变。SQLite 逐库一致，不宣称多个并发写入系统之间的事务快照。

工具不联网、不调用 Git、不读取账号登录文件。私人 ZIP 是本地明文备份，需由你保管或存入自己的加密磁盘；归档及 SHA256 校验文件要一起带到新电脑。缺失的原始文件会写入私人清单，不能把不完整备份当作完整迁移。

## 新电脑一键恢复

克隆公开仓库后，在新电脑执行：

```powershell
./Install.ps1 -PrivateBackup <私人备份路径>/optics.private.zip -RestoreTo <新的私人资料目录>
```

安装器核对归档 SHA256，逐文件验证内容、SQLite 完整性与表记录数，然后生成新机器的路径映射、启动配置和技能库配置。恢复目标必须是仓库外的新目录，不覆盖现有资料。安装中断后可重试；只有前次恢复与同一归档完全一致时才复用。

恢复后的服务关闭启动时自动重建索引，保留现有原型版本、图谱和记忆。原文依靠单独路径映射定位，catalog/audit 字节和历史来源记录不被改写；显式同步仍受原有 SHA 和证据等级约束。

也可以分步运行 `optics_private.py restore`，安装服务后再运行 `optics_private.py activate --destination <恢复目录> --runtime-config <本机 personal-runtime.json>`。激活仅改变后续会话；正常结束旧任务后新建 Codex 对话，不强制结束运行中的服务。

## 验收

```powershell
python scripts/runtime_manager.py doctor --servers optics_workbench
python scripts/verify_optics.py --config <本机 personal-runtime.json> --report <私人目录>/acceptance.json
```

真实验收覆盖中文知识检索、完整参考回读、图谱邻接、图谱记忆、未同步工作流记忆、镜头处方明细、恢复原文 SHA256 和保存的原型清单。通用软件测试只使用合成数据。检索成功不等于原文已全文核读，也不等于 Zemax/LightTools 原生仿真或实测验收通过。

`optics_search_memory` 与 `optics_search_workflow_memory` 分开返回；安装和恢复不会把未同步的记录伪装成已关联图谱。使用 `optics_resolve_source` 按来源 SHA256 读取恢复后的路径和校验结果，再在副本上进行原生操作。

若旧索引的原文件在原电脑上已缺失，默认拒绝自动激活。核对私人缺失清单后，可显式加 `-AllowIncompleteBackup` 恢复可用部分；MCP 状态会持续显示缺失数量，不把它标记为完整恢复。
