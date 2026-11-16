# 私人知识库的云端加密备份

公开仓库只发布工具。私人归档、密文仓库、恢复记录、密码、云盘登录配置都留在仓库外；密文也不允许提交到此公开 Git 仓库。

## 加密与密钥边界

使用固定版本 restic 0.19.1 做加密、认证和快照。夸克通过官方 Quark Drive CLI 传输，其他私人云盘或对象存储可选 rclone 1.76.0。下载官方程序时核对固定 SHA256，不自行实现加密算法。自动安装工具目前支持 Windows/Linux x64。

正文、原文件名、目录树和快照内容经过本地加密。云端会存在 restic 标准的**加密密钥封装**及少量库格式信息，不含可直接解密的明文密钥；恢复所需的随机密码仅写入本机 `password.key`，不上传。具体格式见 [restic 官方设计](https://restic.readthedocs.io/en/stable/100_references.html)，云传输方式见 [官方 rclone 后端说明](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html#other-services-via-rclone)。

密钥目录与密文目录强制分离，拒绝 Git 工作区和已知同步文件夹。Windows 新密钥目录仅授权当前用户和 SYSTEM；Linux 使用目录 0700、密钥 0600。请把恢复记录和密钥另存到自己的离线介质；丢失本地恢复秘密后，云盘账号本身不能解密资料。

## 第一次备份

### 夸克网盘

准备 Git（Windows 包含 Git Bash）、Python 3.11+、Node.js 16+。首次使用会从夸克官方地址下载并校验安装包，在全局 skills 目录安装；不会将第三方 CLI 或登录凭据复制进本仓库。之后运行官方安装检查。若已有不完整的 skill 目录，停止并提示修复，不覆盖用户文件。

先通过官方 skill 的 `login` 命令在浏览器中登录并授权自己的夸克账号。这一步需要本人登录，不需要把密码或令牌发给助手。默认全局位置为 `$HOME/.codex/skills/quarkclouddrive`，也可通过 `-QuarkSkill` 指定已有安装位置。

```powershell
./Backup-Cloud.ps1 -Provider Quark -Archive 'D:\PrivateBackup\optics.private.zip' -KeyDirectory "$env:LOCALAPPDATA\CodexPrivateBackup\keys\optics" -LocalRepository 'D:\PrivateBackup\encrypted-vault' -ReadbackCache 'D:\PrivateBackup\quark-readback'
```

不指定上传目录，遵循官方 CLI 的默认账号目录；不会创建分享链接。只上传经过白名单检查的加密对象，按文件身份保存云端定位，恢复时重建 restic 的目录结构。密文对象在网盘中显示为无语义名称，原文标题和原始目录结构均在密文内部。

恢复记录只在本地保存：含云端文件身份、每个密文对象的 SHA256、大小、固定快照身份。上传完成后还会**重新读取全部云端对象**并核对，再验证完整归档的解密认证、长度和 SHA256，最后才标记为云端备份成功。上传和读取都有逐文件检查点，重新运行会复用已确认的对象；主动验证命令会重新读取云端，不用旧缓存冒充本次云端验证。

已有本地密文无需重新加密，可分步执行：

```powershell
python scripts/optics_cloud.py publish-quark --recovery <密钥目录>/recovery.json
python scripts/optics_cloud.py verify-quark --recovery <密钥目录>/recovery.json --cache-dir <独立的密文回读目录>
```

全量回读中断时，在同一目录添加 `--resume-readback`，逐文件重新核对本地 SHA256 后只下载缺失对象。仅限尚未完成验证的快照；已验证的快照仍需重新读取云端。可在子命令前指定 `--quark-workers 8` 调整并发（1–64，默认 3；高并发须先核对 RAM 与可分配内存余量），按网络与可用内存选择，避免大量 CLI 进程占满内存。回读目录中的 `.quark-readback-progress.json` 记录当前已核对数量和字节数，不代表最终解密验证通过。

后续备份仍使用 `-Provider Quark`。工具保留当前已验证恢复记录，新的快照上传并验证完成后才切换，最近一次记录另存为同一密钥目录中的 `previous-recovery.json`。不删除旧云端对象。若原本的本地密文镜像已不存在，会停止追加备份，提示先恢复镜像。

### 其他 rclone 云盘

先准备 [OPTICS.md](OPTICS.md) 中已校验的 `optics.private.zip` 及 SHA256 文件。运行 `python scripts/cloud_tools.py` 安装并查看两个工具的位置；使用该 rclone 程序的 `config` 命令在本机登录网盘。无需把账号密码、OAuth 令牌、对象存储密钥发到聊天中。

选择自己账户内未共享的专用目录。工具不创建公开链接，也不创建或使用 GitHub 备份仓库。常见可用目标包括 OneDrive、S3 兼容的私人 OSS/COS 存储、SFTP 等 rclone 直接后端；实际容量、网络和权限需在该账号上验证。不能把本地磁盘适配器的测试当成公网验收。

以下路径仅是示例：

```powershell
./Backup-Cloud.ps1 -Archive 'D:\PrivateBackup\optics.private.zip' -KeyDirectory "$env:LOCALAPPDATA\CodexPrivateBackup\keys\optics" -LocalRepository 'D:\PrivateBackup\encrypted-vault' -Remote 'private:OpticsKnowledgeVault'
```

首次会生成随机恢复密码、初始化独立密文库、加密归档并完整回读校验，再上传密文、从目标回读校验。成功后，本地 `recovery.json` 才记录云端位置、库身份、固定快照 ID 和归档 SHA256。网盘身份文件仍由 rclone 本地管理，可用 `-RcloneConfig <本机配置>` 指定。

如果暂不提供 `-Remote`，只生成并验证本地密文，**不代表已经云端备份**。随后可单独发布，不必重复加密：

```powershell
python scripts/optics_cloud.py --rclone-config <本机配置> publish --recovery <密钥目录>/recovery.json --remote private:OpticsKnowledgeVault
```

上传失败后保留本地材料，重新执行发布可复用已上传且未改变的密文对象。目标已有其他文件、不同库或修改过的对象时停止，不覆盖它们。发布成功后的后续备份直接在同一云端库新增快照，不自动删除旧版本，也不执行 prune。

## 换电脑一键下载恢复

第一次在新电脑安装 Git、Python 3.11+、Codex CLI（夸克另需 Node.js 16+），登录同一个云存储，并把 **`recovery.json` 与 `password.key` 两个文件**从离线介质放到本机私有目录。不能把密钥上传网盘来完成这一步。恢复入口从记录自动识别夸克或 rclone；rclone 连接使用与恢复记录相同的 remote 名称。

从此仓库检出 `v1.3.1`，然后运行：

```powershell
./Restore-Cloud.ps1 -Recovery 'D:\OfflineRecovery\recovery.json' -RestoreTo 'D:\OpticsKnowledge' -AllowIncompleteBackup
```

可用 `-QuarkWorkers 8` 调整下载并发。`-CacheDir` 可把解密归档放到另一块盘；`-CiphertextCache` 可复用工具先前建立的回读目录，所有已有密文仍会重新核对 SHA256。复用缓存的恢复测试与再次从云端下载验证是两件事，报告应分别记录。

Windows NTFS 空间紧张时，可添加 `-NtfsCompressed`，只对新建的恢复目录启用透明压缩，按原字节恢复并验证全部文件。它不修改系统压缩设置，也不保证任意资料都能压缩到可用空间内；恢复过程持续检查余量，低于 2 GiB 时停止、保留部分暂存目录，不覆盖现有资料。正常模式仍预检完整逻辑大小；跨盘缓存分别检查空间。目录压缩语义见 [Microsoft compact 文档](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/compact)。

这一条命令安装固定版本工具、验证库身份、下载解密、验证归档 SHA256、恢复数据库/原文/路径映射，并安装插件与 MCP。下载在快照专属暂存目录中进行，中断后重跑可修复和复用暂存文件；认证和校验成功前不会交给安装器。已有非本次恢复的资料目录不会被覆盖。

`-AllowIncompleteBackup` 仅用于你已经接受历史缺失清单的备份；完整备份不需此参数。缺失状态会继续显示，云端加密不会把原本缺失的文件变回来。`-CacheDir` 可复用已验证的归档；正常安装后重开 Codex 对话。不安装插件、仅验收恢复时可显式使用 `-SkipInstall`。

为密文缓存、下载归档和独立恢复副本预留足够磁盘空间；夸克恢复需要三者之和。程序会预检空间，并保留可复用的缓存以便中断后续接。恢复校验通过后可删除本次专用缓存，保留离线恢复记录和密码。备份程序只加密已有一致性快照，不直接复制正在写入的原始数据库；明文旧备份可作为本地回退。

## 验证与版本

```powershell
python scripts/optics_cloud.py --rclone-config <本机配置> verify --recovery <密钥目录>/recovery.json
```

该操作完整读取所选快照中的归档，验证解密认证、长度及 SHA256，会消耗对应下载流量。恢复记录固定到已验证快照，后续更新成功才切换；保留旧恢复记录可选回对应快照，始终使用该库的本地密钥。

自动化覆盖真实 restic 加密/解密、SQLite 恢复、错误密钥、密文篡改、断点暂存修复、硬链接保护、既有资料保护、rclone 传输适配和秘密上传边界。真实用户云盘上传必须另外确认账号、容量与权限；测试通过不等于已经上传你的资料。

夸克适配另有合成协议测试，覆盖逐文件断点、损坏密文、恢复路径保护和移除原镜像后的恢复。该测试中的网盘是合成适配器，不等同于真实云端验收；真实账号结果单独记录。官方 1.0.25 文档描述 `read-file`，实际 CLI 帮助提供 `download --fid --output-dir`；适配器检测实际命令后选择对应模式，两种模式均有边界测试，不修改或分析官方运行时源码。
