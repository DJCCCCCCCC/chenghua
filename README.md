# 城画 0.4.0

从本地 `YouYu自动绘画.exe` 的 Python 3.11 字节码分析其单色自动绘画链路，再独立编写实现。原始 EXE 未修改，重实现不会加载或执行提取的原程序代码。

核心流程：图片 -> 自适应 Canny -> 连续轮廓 -> 框选游戏画布 -> 缩放笔画坐标 -> Windows 鼠标拖动。

## 启动

Windows 10 / 11 x64 用户可从 GitHub Release 下载 `Chenghua-v0.4.0-windows-x64.exe` 直接运行，无需安装 Python。ZIP 版本包含同一 EXE、使用说明及第三方许可；附件 `SHA256SUMS.txt` 可用于校验下载文件。

打包版日志位于 `%LOCALAPPDATA%\Chenghua\chenghua_debug.log`，AI 生成图片保存在该目录下的 `ai_generated` 文件夹。源码运行时保存在项目目录。

源码运行：准备好 `.venv` 后，双击项目目录中的 **`start_chenghua.cmd`** 即可启动城画。旧启动脚本兼容保留。

在项目目录内用 PowerShell 启动：

```powershell
& '.\.venv\Scripts\python.exe' '.\youyu_reimplementation.py'
```

不要再使用旧的系统 Python 启动。原先的 `PIL.Image.Resampling` 兼容错误已处理；图像缩放也使用兼容写法。

在其他机器安装时使用 Windows、Python 3.11：

```powershell
py -3.11 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
& '.\.venv\Scripts\python.exe' '.\youyu_reimplementation.py'
```

## 在游戏画布上绘画

1. 打开“你画我猜”的绘画画面，在游戏内手动选好画笔、颜色和粗细，保持画布可见。
2. 在重实现程序中选择图片，点击“处理图片”。右侧显示实际将绘制的笔画，不只是边缘图片。
3. 在“画布设置”中点击“框选画布”。程序会最小化，拖动选出游戏画布内部区域，绿色笔画随选区缩放。
4. 按 **Enter** 或“确定画布区域”，再确认尺寸；按 **Esc** 取消。不要把工具栏、聊天区、弹窗或窗口边框圈进去。
5. 点击“开始绘画”。程序最小化，默认倒计时 3 秒后开始。此时不要移动鼠标、切换窗口或改变画布位置。
6. 按 **F8** 暂停/继续；按 **Esc** 或小键盘 **减号** 取消；小键盘 **加号**可恢复已暂停的任务。暂停会立即抬笔，恢复时返回上次绘到的位置。
7. 主操作区可拖动速度条，向右加速。最右端为 **极速 · 零等待**：取消逐点等待及落笔前、按下后、抬笔后的固定等待，保留全部路径点。绘画中 **上/右方向键加速，下/左方向键减速**，每次调整 1 ms/点，长按连续调整；在极速档按下/左可回到普通速度。

极速档以常见线稿 5 秒内完成为目标；结束时显示实际绘制耗时（不含启动倒计时，含中途暂停）。图片复杂度、Windows 输入处理和游戏采样会影响耗时及效果，不保证所有图片、游戏都在 5 秒内完整画出。极速出现漏线时向左降低速度。输入使用 SendInput 并禁止 Windows 合并移动消息，游戏自身仍可能丢弃高频输入。

绘画时显示置顶控制条，含进度状态、实时点间隔和“取消绘画”按钮。控制条仅放在选区之外；没有足够空间时会提示使用快捷键，避免遮挡画布。

这是真实鼠标自动化，不是向游戏后台上传图片。不要在绘画途中用鼠标点击软件的暂停按钮；优先使用快捷键。需要操作其他窗口时先暂停或停止。请仅在允许自动化的场景使用。

## 参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| 模糊核 | 7 | 降噪强度，内部使用正奇数 |
| 低/高阈值 | 50 / 150 | 与图像中值、Otsu 阈值共同确定 Canny 阈值 |
| 最短轮廓 | 20 px | 过滤较短的轮廓 |
| 简化精度 | 0 px | 0 保留轮廓点序；增大可减少路径点 |
| 绘画速度 | 5 ms/点 | 速度条范围 0–100 ms/点，0 为极速，普通档间隔越小越快 |
| 插值步长 | 5 px | 长线段插入中间鼠标位置 |
| 落笔前等待 | 150 ms | 普通档到起点后、按下鼠标前的等待；极速档忽略 |
| 倒计时 | 3 秒 | 开始绘画前的准备时间 |

默认按选框宽高分别缩放，与原程序一致；勾选“保持图像比例”可居中等比绘制。普通游戏画笔使用左键，“使用鼠标右键”只适用于确实用右键绘画的画布。

游戏漏线时先降低绘画速度；开始处漏笔时增加落笔前等待。提高“最短轮廓”或使用“简化当前笔画”可减少耗时，但会丢失细节。系统调度和游戏事件采样会影响实际速度，点间隔是等待配置而非实际速度保证。

## 文件

- `youyu_reimplementation.py`：界面、任务状态、热键轮询和线程调度。
- `image_processing.py`：图像预处理、轮廓提取、简化和实际笔画预览。
- `drawing_core.py`：坐标映射、插值、鼠标后端、暂停和停止控制。
- `canvas_selector.py`：透明框选和绿色笔画预览。
- `ai_image.py`：OpenAI Images / Gemini 协议适配和模型列表。
- `runtime_paths.py`：源码及打包版的持久输出目录。
- `scripts/build_release.py`：Windows x64 便携 EXE、ZIP、许可和校验文件的构建脚本。
- `REVERSE_ENGINEERING.md`：原程序证据、重实现对应关系、未覆盖项。
- `analysis_tools/`：本地分析辅助脚本；原 EXE、提取文件及分析输出不随仓库分发。
- `test_artifacts/`：测试运行后生成的输入、模拟画布结果和界面截图，不提交到仓库。

## 构建 EXE

使用 Windows x64、Python 3.11，在项目根目录执行：

```powershell
py -3.11 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-release.txt
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
& '.\.venv\Scripts\python.exe' scripts\build_release.py
& '.\.venv\Scripts\python.exe' scripts\smoke_exe.py .\dist\Chenghua-v0.4.0-windows-x64.exe
```

构建产物写入 `dist`，临时构建文件写入 `build`；两者均不提交。发布前运行 EXE 检查窗口启动与退出，下载校验可用 `Get-FileHash .\dist\Chenghua-v0.4.0-windows-x64.exe -Algorithm SHA256`。构建脚本不依赖原软件或提取目录。

## AI 生图

填写自己的 Base URL 和 API Key（可用 `CHENGHUA_BASE_URL`、`CHENGHUA_API_KEY` 环境变量，兼容旧 `SILICONFLOW_API_KEY`），自动读取模型，也可点击“刷新模型”。切换连接信息会清空旧模型；密钥仅保留在内存中，不写入配置文件。服务必须支持下列生图协议，旧环境变量仅用于预填连接配置，不代表支持 SiliconFlow 原生生图协议。

- 优先支持 OpenAI 兼容格式：`GET /models`、`POST /images/generations`；读取 `data[].b64_json` 或图像 URL。
- 同时支持 Gemini 格式：`GET /models`、`POST /models/{model}:generateContent`；读取候选内容中的内嵌图像。
- “自动”按 Base URL 域名识别官方 Gemini 服务，其他默认 OpenAI；代理站请显式选择协议。Base URL 带自定义路径时原样保留，只在裸域名上补充默认版本路径。
- 返回的模型按名称将常见图像模型优先排列，但模型列表通常不保证生图能力，需选择服务实际支持生图的模型；Gemini 的 `imagen` 预测接口不在此次支持范围。
- 生成成功后自动载入绘画工作台，仍需处理图片、框选画布，再开始绘画。生成操作可能由服务商收费；不会自动重试生图请求。

模型刷新会请求所配置服务，生图仅在点击“生成图片”后请求。未使用真实密钥或付费接口验证，不使用原软件中提取的密钥。

## 验证与范围

在项目目录执行：

```powershell
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
```

如需重新导出静态分析证据，可另行执行 `analysis_tools\export_drawing_evidence.py`，该命令依赖本地原 EXE 和已提取的 `analysis_extract/modules`，这些文件不随仓库分发，也不是运行或打包城画的依赖。

自动化测试覆盖连续轮廓、坐标缩放、Win32 调用参数、模拟画布绘画、暂停续画、异常抬笔、倒计时停止、重复启动保护、框选、导出和界面。**测试使用记录/栅格化后端及被替换的 Win32 调用，不向实际游戏或桌面发送鼠标事件。**

极速回归包含 24 笔、9,692 个原始路径点的栅格化模拟绘制：路径点未简化，测试中的 150 ms 落笔等待配置在极速档正确跳过。运行生成记录见 `test_artifacts/rapid_timing.json`；这是模拟后端耗时，不是实际游戏的完成时间。

已验证本地模拟画布流程，尚未在你的具体游戏窗口中联调。未复刻原程序的彩色分层换色、完整黑白线稿/骨架化模式、平滑算法、高延迟专用模式、登录/VIP/云图库等功能，也不包含登录或授权绕过。
