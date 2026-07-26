# EFTForge 桌面版正式上线！

EFTForge 现在有了可下载的 Windows 桌面版，与你熟悉的网站版并行提供。功能完全一致，同样的工作台、同样的属性计算，只是这次是在你自己的电脑上原生运行，而不是浏览器标签页里。

![桌面版](./news/images/desktopRelease/desktopApp.webp "桌面版 EFTForge")

---

## 为什么要做桌面版

以下几种情况下，本地客户端会很有用：

**你离 EFTForge.com 的服务器比较远。** 如果你的所在地区访问我们位于国内的服务器速度较慢，或者网络连接不太稳定，桌面版可以绕开这个问题。所有计算都在你自己的电脑上运行，工作台不需要向 EFTForge.com 服务器往返请求就能保持流畅。

**网站服务不可用。** 当 EFTForge.com 的后端因为各种原因无法访问时，桌面版完全不受影响，因为它本来就不依赖 EFTForge.com 的服务器来完成任何与你装配相关的核心功能。改枪、查看属性、比较配件，全程都能正常使用。唯一暂时用不了的是社区功能（发布方案、浏览他人方案、评论、排行榜），因为这些本身就存储在服务器上，得等主站服务恢复后才能继续使用。

**你就是更喜欢本地优先的工具。** 有些人不想常开着一个网站标签页，或者更放心把配置数据存在自己可控的文件夹里，而不是浏览器的存储空间中。

---

## 联网模式舆本地模式

桌面版的 EFTForge 会在后台运行着一个本地后端（和网站版用的完全是同一套后端），所以无论选择哪种模式，属性计算以及本地保存的方案，永远都在你自己的电脑上运行。

你能选择的，是是否要连接 **EFTForge.com** 的线上社区服务：

- **联网模式** - 应用会从 EFTForge.com 的线上服务器拉取社区方案、排行榜、评论和资料数据，和直接使用主站一样。
- **本地模式** - 应用完全不与 EFTForge.com 通信。社区功能会直接关闭，直到你重新连接。

你可以随时在应用设置中切换这两种模式。

![模式切换](./news/images/desktopRelease/modeSwitch.webp "")

**需要特别说明：** 这个切换开关只影响是否连接 EFTForge.com。所有物品数据以及每一张枪械/配件图片，实际上都直接来自 **tarkov.dev** 自己的API，而不是我们的服务器，所以无论联网模式还是本地模式，都仍然需要联网才能保持物品数据更新及加载图片。"本地模式"指的是关闭 EFTForge.com 的社区功能，并不代表应用可以完全零网络运行。

---

## 便携式设计

安装程序不会把文件散落到系统各处。应用创建的所有内容（你的方案、设置、缓存）都保存在安装目录的 `data` 文件夹里。想把它搬到 U 盘上或者彻底清除，移动或删除安装目录就行，不留任何痕迹。

---

## 下载

可以从 GitHub Releases 下载 Windows 安装包，如果国内 GitHub 访问较慢或不稳定，也可以使用我们的 Gitee 镜像：

- **GitHub：** [github.com/SouthHorizons76/EFTForge/releases](https://github.com/SouthHorizons76/EFTForge/releases)

![GitHub 下载](./news/images/desktopRelease/githubDL.webp "请下载名为 'EFTForge_x.x.x_x64-setup.exe' 的安装包")

- **Gitee（镜像）：** [gitee.com/morph1ne/eftforge-gitee-mirror/releases](https://gitee.com/morph1ne/eftforge-gitee-mirror/releases)

![Gitee 下载](./news/images/desktopRelease/giteeDL.webp "请下载名为 'EFTForge_x.x.x_x64-setup.exe' 的安装包")

关于这次首个版本，有几点需要说明：

- 仅支持 Windows。
- 安装包暂未进行 Authenticode 签名，因此首次启动时 Windows SmartScreen 可能会弹出警告。应用本身的自动更新依然会进行加密签名校验，这个警告只是针对首次下载的提示。
- 如使用中发现任何问题，请在 [GitHub Issues](https://github.com/SouthHorizons76/EFTForge/issues/new) 反馈，或者 [B站](https://space.bilibili.com/650421245) 私信！

---

_<span style="color:#f5c542;">感谢大家使用 EFTForge！ -- From Morph1ne, with Love</span>_
