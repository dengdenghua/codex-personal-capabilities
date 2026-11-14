---
name: optics-workbench
description: 检索本机光学知识库、证据图谱、个人记忆与镜头库，检查独立私人备份和换机恢复状态。
---

先调用 optics_stats、optics_graph_stats、optics_private_status；未配置私人库时明确说明当前是演示环境。原文、模型、图谱、用户记忆和密码不得提交公开仓库。

使用 optics_search_documents / optics_search_knowledge / optics_search_graph 检索，保留来源和适用范围；使用 optics_search_memory 读取图谱库中的记忆，optics_search_workflow_memory 读取未同步的本地续接记录，二者不能混称；是否关联具体图谱节点须核对记录。镜头库用 optics_search_lens 和 optics_lens_detail。通过 optics_resolve_source 核对恢复映射和文件 SHA256。

原始证据只读，模型验收使用副本。检索命中不等于全文核读、原生仿真或实测通过；历史项目参数不能成为新项目默认指标。备份、恢复只通过操作者命令行执行，不提供接受任意文件路径的上传或删除工具。

换机安装和恢复见仓库 OPTICS.md。恢复时核对 manifest、SQLite 一致性和实际工具调用；有缺失文件时必须报告，不能宣称完整恢复。现有图谱、项目版本和记忆身份保持不变，启动时不自动重建已恢复索引。
