# Desktop Toolkit（桌面效率工具箱）

**独立产品**：截图 / 录屏 / 传输 / 清理 / 音乐 / 待办 / 便签 / 番茄钟 / 闹钟。  


版本：**v1.0.4**

## 功能

| 模块 | 说明 |
|------|------|
| 截图 | 区域/全屏、类 Flameshot 标注、快捷键、可选 Google 云端 |
| 录屏 | 多目标、悬浮条画笔开/关与清除笔画 |
| 传输 | 局域网共享（文件列表）、跨网 P2P（Cloudflare 中转） |
| 清理 | 范围清理、深色主题内嵌页 |
| 效率 | 多开待办、多开便签、番茄钟、闹钟 |
| 助手 | 右下角悬浮机器人快捷入口；字幕提示与语音播报（可关） |
| 系统 | 开机自启、暗黑/白天主题 |

## 运行（开发）

```bat
cd DesktopToolkit
pip install -r requirements.txt
python main.py
```

快捷键：`Ctrl+Alt+T` 主窗口 · `Ctrl+Alt+A` 区域截图（可在截图页改）

## 打包（本地）

```bat
pip install pyinstaller
python -m PyInstaller --noconfirm DesktopToolkit.spec
```

输出目录：`dist\DesktopToolkit\`

**便携包 zip：**

```bat
Compress-Archive -Path dist\DesktopToolkit\* -DestinationPath dist\release\DesktopToolkit-1.0.4-windows-portable.zip
```

**安装包 Setup.exe（Inno Setup）：**

```bat
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\DesktopToolkit.iss
```

产物：`dist\release\DesktopToolkit-1.0.4-windows-setup.exe`  
双击安装 → 开始菜单 / 可选桌面图标 / 可选开机自启 / 可卸载。

## 发布（安全标准）

按 [安全发布自动化引导](https://tpscsm-docs.pages.dev/ai/)：

1. 项目类型：**PyInstaller 桌面应用** → 审核类型 **软件**（`kind=software`）
2. CI：`.github/workflows/release.yml`（tag `v*` 触发）
3. 权限：`id-token: write` / `contents: write` / `attestations: write`
4. 产物：`release-assets/DesktopToolkit-*-windows-portable.zip` + sha256
5. Attestation：`actions/attest-build-provenance@v2`
6. Release：`softprops/action-gh-release@v2`

打 tag 发布：

```bat
git tag -a v1.0.4 -m "Release version 1.0.4"
git push origin v1.0.4
```

## 仓库

推送到组织：`secure-artifacts`  
GitHub 用户：以当前 `gh` 登录账号为准。

## 许可

内部安全审核发布用途；以组织策略为准。
