# Desktop Toolkit

桌面效率工具箱：截图、录屏、文件传输、系统清理、音乐、待办、便签、番茄钟、闹钟。

版本：**1.0.8**

## 功能

| 模块 | 说明 |
|------|------|
| 截图 | 区域 / 全屏截图，标注编辑，快捷键，可选云端上传 |
| 录屏 | 多目标录制，悬浮条画笔开关与清除 |
| 传输 | 局域网共享、跨网传文件 |
| 清理 | 可配置清理范围 |
| 效率 | 多开待办、多开便签、番茄钟、闹钟 |
| 助手 | 桌面悬浮快捷入口，提示与语音播报（可关） |
| 设置 | 开机自启、界面主题 |

## 运行

```bat
pip install -r requirements.txt
python main.py
```

快捷键：`Ctrl+Alt+T` 打开主窗口 · `Ctrl+Alt+A` 区域截图（可在截图页修改）

## 打包

```bat
pip install pyinstaller
python -m PyInstaller --noconfirm DesktopToolkit.spec
```

- 便携目录：`dist\DesktopToolkit\`
- 安装包（需本机安装 Inno Setup）：

```bat
ISCC installer\DesktopToolkit.iss
```

产物在 `dist\release\`：`*-windows-portable.zip`、`*-windows-setup.exe`

## 使用说明

- 安装包：双击 `*-windows-setup.exe` 安装后使用
- 便携包：解压 zip，运行 `DesktopToolkit.exe`
- 跨网传文件：双方填写同一中转地址与房间号；建议接收方先点「等待接收」，再由发送方发送文件

## License

MIT
