# Armada：PR #594 + PR #712 个人构建

本仓库直接 fork 自 [armada-os/armada](https://github.com/armada-os/armada)。官方 `main` 保留作基线，自定义分支为 `custom-pr594-pr712`。

## 包含的功能

- 官方基线：`f1e136a24ceff4ba1817dfb71613842e764558ee`，官方镜像版本 `20261013.f1e136a`。保留该版本的全部官方用户空间和已有内核补丁，包括 Iris 串流绿屏修复、新 Steam Remote Play 环境变量及官方打包重组。
- [PR #712](https://github.com/armada-os/armada/pull/712)：KONKR Pocket FIT Elite 休眠时关闭手柄 MCU 电源；提供 `power_off_in_suspend` 参数，默认启用。
- [PR #594](https://github.com/armada-os/armada/pull/594)：修正 WCN7860 的固件频率范围，按固件范围拆分扫描，并在已关联时保护发送流程，改善开机后的 5 GHz AP 发现。
- 两个 PR 保留原作者提交。#594 的内核补丁针对当前官方代码适配，保留官方已有的 `wiphy_delayed_work` 扫描超时修复；不能把旧版补丁直接叠加到当前内核。

这些补丁仍属于个人测试构建，不等同于官方合并或设备实测通过。Wi-Fi AP 的区域、DFS、固件和信号因素仍可能影响扫描结果。

## 最新 main 基线重建

已合并官方 `f1e136a2` 并保留两个 PR；官方基础镜像已通过 registry manifest/config 校验，revision 与源码对应，固定 digest 为 `sha256:7f58782ac02be17fc007123dc4ad5d1392f392cd470167dcb431289a9f3ae37e`。

- [新版 Actions 构建成功](https://github.com/Nayus/armada/actions/runs/38509101735)，耗时 8 分 13 秒；实际编译源码为 [`5af4dda683f41ecc70a3d08869a85ec62897ef53`](https://github.com/Nayus/armada/commit/5af4dda683f41ecc70a3d08869a85ec62897ef53)。利用 ccache 加速重新构建，没有复用旧内核产物。
- 版本：`20261013.f1e136a-pr594-pr712.5af4dda`，ARM64，实际内核及模块 `7.2.6`。
- 标签：`ghcr.io/nayus/armada-custom:pr594-pr712-20261014-f1e136a`。
- 测试请使用此不可变引用：

  ```text
  ghcr.io/nayus/armada-custom@sha256:159b4b4b203c702761df960254aa9175f2c73c1711c304e700af92a2493602dc
  ```

已独立验证匿名拉取 manifest/config、两者 SHA256、架构、版本与源码 revision。官方的 128 个基础层 payload 完整保留，只新增一个约 106.81 MiB 的内核层；共 129 层，压缩总量约 6.34 GiB。CI 检查 ath12k / qcom-iris 模块、MCU 参数、FIT Elite DTB、Steam Remote Play 环境变量及 initramfs 九个启动必需路径均通过。`bootc container lint`：12 项通过、1 项跳过、2 项非致命警告（运行时目录内容、gamemode 组缺少 sysusers.d 条目）。镜像继承的 Fedora `ostree.linux` 标签不是实际 Armada 内核版本；以模块产物和启动后 `uname -r` 为准。

这是未官方签名的个人测试镜像，尚未设备实测；本次未访问或操作设备（此前只读连接失败），未部署或重启。

最新组合已在全新 Linux 7.2.6 源码上实际应用完整序列：202/202 补丁、1005/1005 hunk 成功，0 失败、0 fuzz；四个自定义补丁及两个新 Iris 补丁均无 offset。官方其他补丁的正常行号 offset 单独记录。详见 [CUSTOM-VALIDATION.json](CUSTOM-VALIDATION.json)，这不代表编译或设备实测通过。

设备已更新官方 main 的用户，应测试上方新版，不要安装下方历史镜像。bootc 切换是替换整套系统与内核，不是只安装两项驱动补丁；此固定 digest 也不会自动跟随未来官方 main 更新。

## 旧基线镜像（历史记录，不建议覆盖新版官方系统）

- [Actions 构建成功](https://github.com/Nayus/armada/actions/runs/38434804569)，耗时约 46 分钟；实际编译源码提交为 [`bb5bf25802a84db8460a75940d33571b0cf43f1a`](https://github.com/Nayus/armada/commit/bb5bf25802a84db8460a75940d33571b0cf43f1a)。后续文档提交不包含在此镜像的 revision 中。
- 版本：`20261013.fd0ed0f-pr594-pr712.bb5bf25`，ARM64，内核及模块 `7.2.6`。
- 标签：`ghcr.io/nayus/armada-custom:pr594-pr712-20261013-fd0ed0f`。
- 历史构建的不可变引用：

  ```text
  ghcr.io/nayus/armada-custom@sha256:90ae3dc6ba26124001903d82eaeadb7e029025277f2e4bf777f7a3a73cd5770c
  ```

已在 CI 以外验证匿名访问 manifest 和 config，并核对 SHA256、ARM64 架构、bootc 标签、版本及源码 revision。官方基础镜像的 128 层全部保留，新增一层内核替换内容；镜像共 129 层，压缩总量约 5.91 GiB，现有基础层可复用。

全部 200 个内核补丁成功应用；ath12k 实际编译链接、MCU 参数、FIT Elite DTB、initramfs 的九个必需路径检查通过。`bootc container lint` 为 13 项通过、1 项跳过、1 项运行时目录内容警告，未阻止构建。此镜像尚未在设备上启动测试，不是官方签名发布；设备没有被修改或重启。

## 可重复构建

在 [Actions](https://github.com/Nayus/armada/actions) 中选择 **Build Armada bootc with PR594 and PR712**，在 `custom-pr594-pr712` 分支运行。

- `base_image`：固定的新版官方基础镜像，默认 `ghcr.io/armada-os/armada@sha256:7f58782ac02be17fc007123dc4ad5d1392f392cd470167dcb431289a9f3ae37e`。CI 同时核验官方 version 和 revision。
- `image_tag`：默认 `pr594-pr712-20261014-f1e136a`，发布到 `ghcr.io/nayus/armada-custom`。
- `kernel_artifact_run`：首次运行留空；仅当内核输入与构建配方完全一致时，允许复用本仓库旧运行的内核产物。不能复用只带 #712 的旧内核。

工作流使用官方 Fedora 工具链从当前源码重新编译完整内核及模块，替换固定官方镜像中的内核、模块、DTB，并重新生成 initramfs。它生成完整的可部署 bootc 镜像，不是让设备手工覆盖启动文件。使用官方基础层是为了保留该版本全部官方用户空间功能，避免不必要地重新构建不变的软件包。

CI 检查补丁清单、产物校验和、FIT Elite DTB、内核 MCU 参数、ath12k 模块、initramfs、`bootc container lint`、架构、镜像版本和源码 revision；成功后 Summary 给出不可变的 `repository@sha256:...`，Artifacts 提供内核及镜像校验元数据。

个人 GHCR 包首次发布可能是私有的：需要在包设置中改为 Public，或者为设备配置读取授权。请勿把 GitHub token 写进仓库、镜像或命令记录。

## 部署与回退

构建过程不会操作设备。仅在 Actions 全部成功、镜像可拉取且已备份重要数据后，由设备所有者执行部署。

```bash
# 先检查没有已有待重启部署；如有，先处理它，不要盲目叠加切换。
sudo bootc status
sudo ostree admin status

# 只有确认当前 booted 部署序号为 0、且没有 staged 部署时：
sudo ostree admin pin 0

# 最新 main + 双 PR 的已验证不可变引用，不要替换成历史旧基线 digest。
sudo bootc switch 'ghcr.io/nayus/armada-custom@sha256:159b4b4b203c702761df960254aa9175f2c73c1711c304e700af92a2493602dc'
sudo bootc status

# 仅在 switch 成功且 staged 镜像正确时，执行正常完整重启。
sudo systemctl reboot
```

这是原地系统切换，不重新刷机，正常保留用户数据；测试内核仍可能出现设备相关问题，因此备份不能省略。使用完整重启而不是 kexec，确保 Armada 的启动镜像 finalize 钩子完成。

重启后验证：

```bash
sudo bootc status
cat /usr/lib/armada/version
uname -r
cat /sys/module/mcu_joystick/parameters/power_off_in_suspend
nmcli -f IN-USE,SSID,FREQ,SIGNAL device wifi list --rescan yes
```

版本应为 `20261013.f1e136a-pr594-pr712.5af4dda`，`uname -r` 应为 `7.2.6`，MCU 参数应为 `Y`。实际测试休眠、唤醒、手柄、冷开机后的 5 GHz AP 发现和联网，以及 Steam Remote Play 是否仍有绿屏；CI 无法代替这些硬件测试。

若还能进入系统但出现问题：

```bash
sudo bootc rollback
sudo systemctl reboot
```

无法进入系统时，需要备用启动介质和已保存的正常启动镜像恢复，不能在失去启动能力后依赖终端回滚命令。固定 digest 的个人镜像不会自动跟随官方发布；今后升级官方基线时，需重新审查、适配这两个 PR 并构建验证。
