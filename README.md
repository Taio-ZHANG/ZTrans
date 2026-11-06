# ZTrans 1.2.3

Windows 本地优先翻译工具：悬浮翻译窗口、划词翻译、文档导入导出和离线拾词便签。

A local-first Windows translator with Ollama/OpenAI-compatible backends and an offline vocabulary widget.

## 功能

- 对接本机 Ollama，默认模型 `hy-mt1.5:7b`；也可手动配置 OpenAI 兼容 HTTPS API。
- F1 划词翻译、Ctrl+Alt+Z 显示窗口、流式翻译、术语和翻译风格设置。
- 导入 PDF / Word / 文本和网页正文，导出双语 Word / PDF / HTML。
- 闲置切换拾词便签，离线音标、中文释义和 Windows 语音朗读。

## 从源码运行

需要 Windows 10/11、Python 3.12。建议把仓库放在较短路径（例如 `C:\src\ZTrans`），避免 Windows 路径长度限制影响 Qt 依赖安装。模型服务需自行安装，本仓库不分发模型权重。

```powershell
cd source
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe app.py
```

如使用 Ollama，请先启动服务，并自行下载所需模型。应用不会在本地翻译失败时自动改用付费服务。
首次使用请在设置中检查开机启动偏好；公共源码保留原版应用的默认行为。

## 验证与构建

在 `source` 目录运行：

```powershell
.\.venv\Scripts\python.exe -m pytest test_core.py test_regressions.py -q
.\build.ps1
```

构建输出为 `source/dist/ZTrans`。`INSTALL.ps1` 默认安装到当前用户的本地程序目录；桌面快捷方式和开机启动分别通过 `-DesktopShortcut`、`-StartAtLogin` 显式启用。
`--smoke-test` 会调用本机 Ollama；常规回归测试使用模拟请求和合成文本。

## 数据和隐私

源码运行时，设置、窗口状态和用户单词保存在仓库根目录的 `data/`；打包后位于 EXE 旁的 `data/`。该目录已整体排除版本控制。
公开版本不含用户 API Key、DPAPI 加密配置、私人词库或会话内容。离线公共词典位于 `source/ipa` 和 `source/meaning`。
在线服务只有在主动选择并确认后才会收到原文。详细说明见 [PRIVACY.md](source/PRIVACY.md) 和 [使用指南](source/README.md)。

## 许可证

本项目按 [AGPL-3.0-only](LICENSE) 开源。当前文档功能使用 PyMuPDF 的 AGPL 版本，因此公开版采用 AGPL-3.0，而非统一使用 MIT。
第三方库、Qt 与词典数据保留各自原始许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 `THIRD_PARTY_LICENSES/`。

本次公开的是可审查源码快照；不分发本机已有 EXE 和运行库。贡献与反馈见 [CONTRIBUTING.md](CONTRIBUTING.md)。
