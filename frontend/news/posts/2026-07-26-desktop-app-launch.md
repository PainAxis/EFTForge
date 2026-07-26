# The Desktop App is Here!

EFTForge is now available as a downloadable Windows app, alongside the website you already know. It's the same workbench, the same stats, the same everything, now running natively on your own machine instead of in a browser tab!

![The Desktop App](./news/images/desktopRelease/desktopApp.webp "The Desktop App")

---

## Why Use the Desktop App?

A few situations make a local app worth having:

**You're not near EFTForge.com's servers.** If you're using our services from outside of China, or your connection to the site is just slow or flaky on any given day, the desktop app sidesteps all of that. Every calculation runs on your own computer, so there's no round trip to a remote server for the workbench to feel instant.

**The site's services go down.** When EFTForge.com's backend is unreachable for whatever reason, the desktop app doesn't care, it isn't talking to it in the first place for anything that matters to your build (unless you're in connected mode, more on this later). You can keep modding guns, checking stats, and comparing attachments the entire time. The only thing you'll lose access to is community features (publishing builds, browsing community builds, comments, leaderboards) until the site is back, since those live on the server by nature.

**You just prefer a local-first tool.** Some people would rather not have a website tab open, or like knowing their build data lives in a folder they control rather than a browser's storage.

---

## Connected Mode & Local Mode

The app runs its own local backend in the background (the exact same one that powers the website), so all stat calculations and your locally saved builds are always handled on your own machine, regardless of which mode you pick.

What you get to choose is whether it also talks to **EFTForge.com's** live community servers:

- **Connected mode** - the app pulls community builds, leaderboards, comments, and profile data from EFTForge.com's live servers, same as the website.
- **Local mode** - the app never talks to EFTForge.com at all. Community features are simply switched off until you reconnect.

You can flip between the two at any time from the app's settings.

![radio](./news/images/desktopRelease/modeSwitch.webp "")

**One important note:** this toggle is only about EFTForge.com. Item data and every gun/attachment image still come straight from **tarkov.dev's** own API, not ours, so an internet connection is required either way, in both connected and local mode, to keep item data current and to load images. "Local mode" means EFTForge.com's community features are off, not that the app runs with no internet at all.

---

## Portable by Design

The installer doesn't scatter files across your system. Everything the app creates (your builds, settings, cache) lives in a `data` folder next to the exe. Want to move it to a USB stick or wipe it clean? Delete the folder and every trace is gone.

---

## Download

Grab the Windows installer from GitHub Releases, or from our Gitee mirror if GitHub is slow or blocked for you:

- **GitHub:** [github.com/SouthHorizons76/EFTForge/releases](https://github.com/SouthHorizons76/EFTForge/releases)

![installerDownload](./news/images/desktopRelease/githubDL.webp "Please download the option named 'EFTForge_x.x.x_x64-setup.exe' for the installer")

- **Gitee (mirror):** [gitee.com/morph1ne/eftforge-gitee-mirror/releases](https://gitee.com/morph1ne/eftforge-gitee-mirror/releases)

![installerDownload](./news/images/desktopRelease/giteeDL.webp "Please download the option named 'EFTForge_x.x.x_x64-setup.exe' for the installer")

A couple of notes for this first release:

- Windows only.
- The installer isn't Authenticode-signed yet, so Windows SmartScreen may warn you on first launch. The app itself still verifies its own auto-updates cryptographically, this warning is purely about the initial download.
- Found a bug? Please report it on [GitHub Issues](https://github.com/SouthHorizons76/EFTForge/issues/new) or DM me on [Bilibili](https://space.bilibili.com/650421245)!

---

_<span style="color:#f5c542;">Thanks for using EFTForge! -- From Morph1ne, with Love</span>_
