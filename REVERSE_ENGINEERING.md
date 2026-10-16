# YouYu 单色自动绘画链路逆向记录

日期：2026-10-16。

## 目标与证据边界

- 原始文件：`D:\桌面\Code\绘图工具逆向\YouYu自动绘画.exe`。
- 文件大小：317,360,145 字节。
- SHA-256：`48ed9d296958432b5d8e500e68fa6db4dba2cb7f5270b916f576e4ff4cef67db`。
- 提取结构显示 PyInstaller 打包的 Python 3.11 应用；主界面使用 PyQt5，画布选择器使用 Tk。
- 本次结论来自已提取 `.marshal` 的 code object、调用关系、常量与 `dis` 反汇编，没有执行原程序模块、登录服务或调用游戏接口。
- 当前会话没有可调用的 REA 分析工具；以下为本地 Python 静态分析证据，不冒充 REA Evidence ID，也不把静态结论描述为原程序运行观测。

可重生成证据：

```powershell
& '.\.venv\Scripts\python.exe' -X utf8 analysis_tools\export_drawing_evidence.py
```

结果目录 `analysis_extract/drawing_evidence/`：`manifest.json` 记录原 EXE 哈希、模块哈希所在文件、函数限定名及**原始源码行号**。下面的行号是 code object 携带的 `co_firstlineno`，不是反汇编文本文件行号。字节码里的字符串仅作被分析数据，不作为执行指令。

## 已确认链路

| 环节 | 原函数及源码起始行 | 静态观察 | 重实现 |
| --- | --- | --- | --- |
| 处理任务 | `modern_app.ImageProcessThread.run:183` | 调用预处理、轮廓提取、笔画生成；普通边缘模式不默认骨架化 | `App._process_worker` |
| 边缘检测 | `imgprocess.ImageProcessor.preprocess:61` | 灰度、CLAHE、GaussianBlur、自适应 Canny；少边缘时降低阈值重试 | `ImageProcessor.preprocess` |
| 连续轮廓 | `imgprocess.ImageProcessor.extract_contours:202` | `RETR_LIST`、`CHAIN_APPROX_NONE`；按开放弧长过滤并排序 | `ImageProcessor.extract_strokes` |
| 笔画顺序 | `imgprocess.ImageProcessor.get_drawing_points:361` | 保留轮廓点序；支持平滑、简化、从上到下排序 | 保留点序和排序，可选简化；未逐行复刻平滑 |
| 选择画布 | `modern_app.ModernDrawingApp.select_position:5157` | 最小化主窗口，调用框选器，取得起点和宽高 | `App._select_area`、`CanvasSelector` |
| 框选预览 | `area_selector.AreaSelectorV2.select_area:233`、`on_mouse_drag:373`、`_draw_preview_strokes:464`、`on_confirm:533` | 透明顶层窗口，拖动预览；确认后返回区域，宽高必须大于 10 | `CanvasSelector` |
| 启动 | `modern_app.ModernDrawingApp.start_drawing:5316` | 检查笔画及区域、读取延迟参数、启动监听并最小化 | `App._start_drawing` |
| 绘画线程 | `modern_app.DrawingThread.run:348` | 倒计时、缩放每个点、逐笔执行、进度和暂停逻辑 | `App._draw_worker` |
| 鼠标移动 | `mctl.MouseController.move_to:52` | 把屏幕坐标归一化为 0..65535，调用 `mouse_event` 绝对移动 | `Win32MouseBackend.move` |
| 按住拖动 | `mctl.MouseController.draw_stroke:92` | 到起点、等待、按下、插值移动、抬起；支持左右键及暂停 | `WindowsMouseController.draw_stroke` |

对应证据文件为 `modern_app.txt`、`imgprocess.txt`、`area_selector.txt`、`mctl.txt`。

### 图像处理

普通边缘路径使用 CLAHE `clipLimit=2.0`、`tileGridSize=(8,8)`。模糊后图像的中值和 Otsu 阈值参与 Canny 阈值计算：

```text
low  = max(10, min(int(median*0.5), int(otsu*0.5), user_low))
high = max(50, min(200, int(median), int(otsu), user_high))
```

如果边缘像素少于 500，降低阈值再试；仍少于 100 时用 `(5,30)`。之后过滤 `arcLength(contour, False) <= min_length` 的轮廓。

重要修正：绘画点必须沿轮廓连续排列，不能把连通分量里的点按主轴、X 或 Y 简单重排，否则圆形、转角等会被错误连线。重实现保留 OpenCV 返回的轮廓点序。绘画顺序排序只作用于整笔，不重排一笔内部的点。

“人类顺序”原实现按首点 Y 划分顶部、中部、底部，各区内按首点 `(y,x)` 排序；这里等价地按全体笔画首点 `(y,x)` 排序。关闭时按点数从多到少排序。原程序普通模式还启用平滑；当前实现默认保留未平滑轮廓，因此不宣称与原版逐点一致。

### 画布坐标

原绘画线程的主要计算：

```text
scale_x = canvas_width  / image_width
scale_y = canvas_height / image_height
screen_x = offset_x + int(round(image_x * scale_x))
screen_y = offset_y + int(round(image_y * scale_y))
```

这说明核心能力是模拟鼠标在选定矩形内绘画，**不是游戏接口上传，也不是在自己的预览窗口里画完就结束**。这一结论限于已跟踪的单色绘画链路，不用于断言原软件所有功能都不联网。

重实现默认相同缩放，并额外钳制右/下边界，避免四舍五入越出所选区域。可选等比居中、多显示器虚拟桌面坐标支持属于新增实现，不是对原版能力的断言。

### 实际控件默认值

依据 `ModernDrawingApp.create_left_panel:3164` 及线程参数单位转换，而不是仅凭帮助文案：

| 参数 | 原始默认值/换算 | 当前默认值 |
| --- | --- | --- |
| 模糊核 | 7 | 7 |
| 速度 | 0.0001 秒 | 0.0001 秒 |
| 插值步长 | `step_div=5` | 5 px |
| 点间额外延迟 | `min_speed=5`，除以 1000 | 5 ms |
| 落笔前等待 | `min_lift=15`，除以 100 | 150 ms |
| 倒计时 | 3 | 3 秒 |

原线程缺参时 `draw_max_step` 回退 10000，但实际滑块默认是 5，不能把回退值当界面默认值。原 `draw_stroke` 在按下后再等待约 0.02 秒，抬起后约 0.03 秒；重实现保留这两个间隔。

## 重实现的安全性与差异

- 只用独立 Python 源码及公开图像库，不调用原字节码，不改动原 EXE。
- 图像处理放后台线程；Tk 控件只在主线程操作。画布坐标和笔画在启动时快照，点间等待通过加锁共享值实时读取，避免任务中途产生混合坐标。
- 开始前检查画布范围，未框选不会绘画；旧绘画线程退出前不能重复启动。
- 暂停、停止、异常、关窗都进行抬笔清理；恢复先抬笔移回上一次绘到的位置，再继续当前线段。
- 每个插值点都检查停止/暂停，等待可以被停止打断；这比原代码稀疏检查更及时，但受操作系统和 UI 轮询调度影响，不是硬实时保证。
- 全局键仅在绘画任务期间轮询指定控制键，不记录文本输入。F8 暂停/继续，Esc/小键盘减号停止，小键盘加号恢复；不实现热键直接启动未确认的新任务。
- 多显示器坐标、DPI 意识、等比选项、边界钳制为新增防护；异构 DPI 多屏、屏幕间空洞和实际游戏采样仍需实机联调。
- `PIL.Image.Resampling` 改为兼容访问；项目独立 `.venv` 避免旧系统 Python/Pillow 与项目依赖混用。

## 验证记录

命令：`.venv\Scripts\python.exe -m unittest discover -s tests -v`。

初版结果：**36 项测试全部通过**，约 11.2 秒。运行环境为 Python 3.11.9、Pillow 12.3.0、OpenCV 4.14.0；源码编译检查通过。

测试分为数学/图像/控制器与 Tk 工作流，覆盖：

- 不同缩放、边界、负屏幕坐标、等比选项和非法参数；
- 分离物体不跨笔连接，圆形轮廓内部连续，简化后端点保留；
- 空白图、透明图、真实笔画预览和 JSON 原生整数坐标；
- 左右键配对、长线插值、暂停即时抬笔、恢复回到断点、停止打断等待、异常释放；
- Win32 绝对移动和左右键标志（替换真实系统调用，不发送输入）；
- 完整导入/处理/模拟画布绘画、框选确认/取消、重复启动拒绝、倒计时停止；
- 导航保留参数、热键边沿防抖、960x650 和 1120x760 界面控件可访问。

`test_artifacts/sample_input.png` 是测试自建图；`stroke_preview.png` 是路径预览；`simulated_canvas.png` 是记录鼠标后端逐笔栅格化的输出，并非游戏截图。界面截图是本地 Tk 窗口截图。

## 城画 0.3 交互更新

2026-10-16：重实现的产品名称统一为“城画”，原始 EXE 和逆向证据中的名称不改动。

本次完整回归：**51 项测试通过**，约 12.6 秒；五个应用模块的 `py_compile` 检查通过。

- 速度条常驻主操作区；绘画中上/右方向键加速，下/左减速，逐点读取生效。
- 框选后明确确认选区；绘画中显示不遮挡选区的取消控制条，无空间时改为提示快捷键。
- 自定义 Base URL、OpenAI Images 与 Gemini generateContent、自动/手动刷新模型列表及模型下拉框。
- 接口模拟测试和本地 HTTP 测试覆盖模型列表、鉴权、分页、两种生图响应；未请求真实付费服务。
- GUI 测试新增选区拒绝/确认、方向键、自动读取模型、旧模型失效、生成图片载入及浮窗取消。

## 尚未完成或验证

城画 0.4 速度更新：最右端新增零等待极速档，逐点等待与每笔固定等待均跳过，仍保留路径、抬笔和取消检查；普通档保持等待策略。Win32 后端改为 SendInput，移动带 NOCOALESCE 标记。57 项回归测试通过，24 笔 / 9,692 点模拟画布测试约 0.30 秒；不代表游戏实测速度。

- **未在用户的具体“你画我猜”版本/游戏窗口中实测**。真实鼠标事件是否被接受、画笔宽度、速度与游戏画布配合情况仍未知。
- 当前是单色主流程复现，不是原软件全功能的等价克隆。未复刻彩色分层/自动换色、完整黑白骨架化、原版平滑、高延迟专用参数组等。
- 原程序登录、VIP、收费、云图库及相关服务未复刻，不做授权绕过。
- 可选 AI 适配需用户自己的密钥；未调用外部生图服务进行验证，也不复制提取出来的任何凭证。
