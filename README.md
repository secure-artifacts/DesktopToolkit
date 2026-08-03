# Desktop Toolkit

桌面效率工具箱：截图、录屏、文件传输、系统清理、音乐、待办、便签、番茄钟、闹钟。

版本：**1.1.0**（Windows 安装包 + macOS 源码 / `build_mac.sh` 打 .app）

## 功能

| 模块 | 说明 |
|------|------|
| 截图 | 区域 / 全屏截图，标注编辑，快捷键，可选云端上传 |
| 录屏 | 多目标录制，悬浮条画笔；**录制全程静默**（ffmpeg 无控制台闪窗） |
| 传输 | 局域网共享、跨网传文件 |
| 清理 | **Windows / macOS** 分别提供合适的清理范围 |
| 效率 | 多开待办（勾选完成、▲▼ 调序、折叠/置顶/改大小）、便签、番茄钟（番茄配色+置顶） |
| 助手 | 桌面悬浮快捷入口，提示与语音播报（可关） |
| 设置 | 开机自启（Win Run / Mac LaunchAgent）、界面主题、检查更新 |

## 1.1.0 更新

- 待办：左侧可见勾选框 + 点文字完成；柔和便签配色；▲▼ 调序不误触
- 待办/便签/番茄：置顶、折叠、右下角改大小；位置记忆并在多分辨率下钳制到可见屏幕
- 录屏：确认静默（`CREATE_NO_WINDOW` + 隐藏 STARTUPINFO）
- macOS：清理范围 / LaunchAgent 自启 / `build_mac.sh` 打包脚本

## 运行

```bash
pip install -r requirements.txt
python main.py
```

Windows 快捷键：`Ctrl+Alt+T` 打开主窗口 · `Ctrl+Alt+A` 区域截图（可改）

macOS：全局热键依赖系统能力，部分功能（按窗口录制）在 Windows 更完整；屏幕区域录制可用。首次录屏请在 **系统设置 → 隐私与安全性 → 屏幕录制** 中授权。

## 打包

**Windows**

```bat
pip install pyinstaller
python -m PyInstaller --noconfirm DesktopToolkit.spec
ISCC installer\DesktopToolkit.iss
```

便携包：将 `dist\DesktopToolkit` 打成 zip，命名 `DesktopToolkit-<ver>-windows-portable.zip`。

**macOS（本机或 GitHub Actions）**

本机：

```bash
chmod +x build_mac.sh
./build_mac.sh
```

GitHub：推送 `v*` 标签或在 Actions 里手动运行 **Build and Release**（可指定 tag）。  
`macos-14` runner 会打出 `DesktopToolkit-<ver>-macos.zip` 并挂到该 Release。

产物：Windows 见 `dist/release/`；macOS 见 `dist/release/DesktopToolkit-*-macos.zip`。

## 使用说明

- 安装包：双击 `*-windows-setup.exe` 安装后使用
- 便携包：解压 zip，运行 `DesktopToolkit.exe`
- 跨网传文件：双方填写同一中转地址与房间号；建议接收方先点「等待接收」，再由发送方发送文件

## License

MIT
