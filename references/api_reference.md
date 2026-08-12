# VP ToolBlock Builder — API 约束与踩坑笔记

本文档收录在 Cognex VisionPro 9.x 上用 pythonnet 程序化构建 `.vpp` 时**反复踩过的坑**。
每一条都经过了实测验证（不是猜的）。遇到 VP API 报错时，优先查这里。

---

## 1. 环境准备（任何操作的前提）

- **必须删除 `ACC_*` 环境变量再 `import clr`**。这些变量会让 VP 加载错误的程序集版本，
  导致后续反射/类型解析全部失效。在 `probe_vp_env.py` 里用 `delete_acc_env()` 统一处理。
- **VP 是 COM/STA 组件**：所有 VP API 调用必须在 STA 线程上跑，否则随机抛
  `InvalidCastException` / `RPC_E_WRONG_THREAD`。
  模式：`Thread(ThreadStart(...)); th.SetApartmentState(ApartmentState.STA); th.Start(); th.Join()`。
- **pythonnet 的 `type` 没有 `.GetProperty`**：C# 反射用 `type.GetProperty("X")`，
  但 pythonnet 暴露的 Python `type` 不支持。必须用 `clr.GetClrType(obj.GetType())` 拿真正的
  CLR Type，再 `.GetProperty/.GetValue/.SetValue`。这是全工具统一的反射入口。

## 2. 版本与程序集发现（不写死路径）

- VP 安装根通过**注册表只读**探测：`HKLM\SOFTWARE\Cognex\VisionPro`，再用常见盘符路径兜底。
- **多根回退**：机器上可能同时存在 x86 (`C:\Program Files (x86)`) 和 x64 根。x86 的 DLL 在
  64 位 Python 下会抛 `BadImageFormatException`，必须 try/except 跳过，自动选能加载的根。
- **核心程序集**：`Cognex.VisionPro.dll`。其**同级** `ReferencedAssemblies` 目录才是真正要
  `clr.AddReference` 的目录（不是 dll 所在子目录如 `CogPlus`）。
- **批量加载**：遍历 `<root>\ReferencedAssemblies` 下所有 `Cognex.*.dll` 并 `AddReference`，
  才能枚举到 Caliper/ID/PMAlign/PatInspect 等全部工具类型。
- **版本号**：用 `AssemblyName.GetAssemblyName(core).Version` 读，例如 `59.2.0.0`
  对应 VP 9.x 产品线。不要硬编码版本判断，用反射读到的为准。

## 3. 致命限制：没有"连线"API

- **ToolBlock 内部连线 / Job 层连线没有任何公开 API**。已确认：
  `CogToolBlock` 没有 `Connections` 属性；全局类型里不存在 `CogToolBlockTerminalConnection`；
  脚本基类没有 `ConnectTools` 之类的方法。
- **结论**：不要试图用代码"连工具"。采用 **自包含 ToolBlock**：在 `GroupRun` 里用代码把图像对象
  直接传给其他工具的 `InputImage`，实现**内部零手动连线**。
- **三种图源模式（都不写死图）**：
  - `file`（离线自测）：把 `CogImageFileTool` 放进 ToolBlock 内部当图源，GroupRun 里
    `ft.Operator.Open(path).Run()` 取图。用户双击 Run 即出效果。
  - `input`（相机实时，推荐用于真实环境）：**不内置任何图像文件**。保留 `InputImage` 终端，
    由外部 `CogAcqFifoTool`（相机）连线喂图：`CogAcqFifoTool.OutputImage -> CogToolBlock1.InputImage`
    （这是用户在本机 QuickBuild 只需做的**一条**标准连线）。ToolBlock 内部放一个
    `CogImageConvertTool`，GroupRun 里 `conv.InputImage = InputImage; conv.Run()` 透传，
    得到稳定的灰度 `OutputImage` 供分析与叠加。相机未连时 GroupRun 优雅返回 `NO_IMAGE`，
    不会崩。
  - `both`（相机 + 图片，一键切换，**最通用**）：ToolBlock 内部**同时**放 `CogImageFileTool1`
    和 `CogImageConvertTool1`，并暴露两个输入终端：`UseFileImage`(bool，默认 false=相机) 和
    `ImageFilePath`(string，默认路径可在 spec 里给)。GroupRun 按 `UseFileImage` 选择图源——
    图片模式下运行时 `ft.Operator.Open(ImageFilePath).Run()`，两种模式都经同一个
    `CogImageConvertTool1` 透传，所以叠加记录 `"CogImageConvertTool1.OutputImage"` 完全一致，
    **切换只需在 VP 里勾一下 `UseFileImage`/填个路径，不改连线、不改脚本**。没有相机时用图片
    自测，有相机时秒切实时，二者自由切换。
- 优先用 `CogToolBlock` 容器，**不要**用 `CogJob` —— Job 层宿主态更难加载，且无连线 API。

## 4. 脚本注入（最关键的可用模式）

验证可用的注入顺序（错一步脚本就不生效）：

```
tb.CreateNewScript(Lang.ScriptCSharp, CogToolBlockScriptTypeConstants.Advanced)
tb.Script.Source = src          # src 是完整 C# 类源码（含 class 定义）
ok = tb.Script.TempCompile()
res = tb.Script.Build(CogToolBlockAdvancedScriptBase, "")
```

- **`Lang` 不是直接 import 的常量**，要反射：`Assembly.GetTypes()` 找
  `Name == "CogScriptLanguageConstants"`，取其 `ScriptCSharp` 值。
- **不要用 `tb.ScriptText` 反射赋值** —— ToolBlock 上没有这个属性，设了也白设，脚本根本没注入。
- **沙箱 `Build()` 几乎必失败**：返回 `No Script Class Found`，原因是沙箱禁止 `csc.exe` 动态
  加载程序集。这**不影响 .vpp 可用性**——源码已随 `Script.Source` 嵌入，用户本机 VP 打开会
  **自动重编译**。检测逻辑应在 Python 侧用交叉验证保证正确（见第 6 节）。
- 脚本类必须继承 `CogToolBlockAdvancedScriptBase`，实现 `Initialize / GroupRun /
  ModifyLastRunRecord` 三个 override。

## 5. 图形叠加（Overlay）的隐藏坑

- **叠加必须挂到"图像型工具的 `OutputImage`"子记录**，而不是 ToolBlock 的 `OutputImage` 输出终端。
  `InputImage` / `OutputImage` 终端自身都不会生成可查看的 LastRun 子记录，画上去看不到。
  - `file` 模式：`"CogImageFileTool1.OutputImage"`
  - `input`(相机) 模式：`"CogImageConvertTool1.OutputImage"`（即内部透传工具的 OutputImage）
  正确写法：`tb.FindRunRecord(lastRecord, term)`，再 `tb.AddGraphicToRunRecord(graphic, lastRecord, term, "NAME")`。
- **`LastRunRecordEnable` 必须设为 `CompositeSubToolRecords`**，否则根本不生成叠加记录。
  用反射设置：`lrEnum = tb.GetType().GetProperty("LastRunRecordEnable").PropertyType;
  tb.LastRunRecordEnable = System.Enum.Parse(lrEnum, "CompositeSubToolRecords")`。
- **可用图形类型**：`CogRectangle`（框）、`CogLineSegment`（线）、`CogGraphicLabel`（文字，
  支持 `\n` 多行）、`CogCircle`（圆）。都用 `AddGraphicToRunRecord` 挂。
- **颜色枚举没有 `Transparent`**：`CogColorConstants.Transparent` 不存在，本机打开会编译报错。
  用 `Black` / `Green` / `Red` / `Yellow` 等真实成员；若想让背景透明，别设 BackgroundColor
  或设为 Black。
- **字体/布局**：标签字体过大 + 字符串过长 + 多行挤在一起会重叠。经验值：7pt 字体、行距 16px、
  SN 串截断显示。文字锚点放在搜索框外侧（上方）避免压物料。
- **图像强转**：工具的 `InputImage` 常需 `CogImage8Grey` 强转（彩色图直接传可能类型不符）。

## 6. 验收：不靠 GUI 怎么确认"做对了"

三层验收，全部可配置、不写死阈值：

- **Layer A 交叉验证（核心）**：`run_validate.py` 模式——STA 线程直驱 VP API 复跑检测逻辑，
  对真值（ground truth）比对量化指标：圆心坐标误差、解码成功率、NG 计数、IoU、缺陷漏检率等。
  阈值由用户在任务时定义，Agent 不臆造。
- **Layer B 视觉预览**：`make_preview.py` 模式——用 cv2 渲染与 `.vpp` 叠加**完全一致**的预览图
  （绿框/红分区线/黄测量线+距离/四行标签）。沙箱里没有 VP 画面，靠它当"眼睛"核对布局。
- **Layer C 结构核验**：`verify_vpp.py` 模式——`CogSerializer.LoadObjectFromFile` 反序列化，
  断言工具数量、I/O 终端、LastRunRecordEnable 是否正确。

## 7. 版本/机器迁移风险点

- 同代（VP 9.x）基本直接复用：路径/工具均已反射发现，无需改代码。
- 跨大版本（如 VP 10+ 脱离 .NET Framework/COM）需重新验证：`clr` 加载链路、脚本编译器、
  个别属性名微调。这些都不应硬编码，全部走探测+反射兜底。
- 必须依赖 QuickBuild 私有可视化配方、或 Job 层连线的工程，本方案不适用（无连线 API）。
- 需要特定相机/GPU 驱动的任务，只能在用户本机真跑，沙箱只做结构与逻辑验证。

## 8. 常见工具 API 非直觉对照表（写 C# 前必读）

**核心原则：不要凭直觉猜 Cognex API 的属性和枚举名**——VP 的命名约定和 .NET 常规习惯差异很大。
以下每一条都来自实战编译错误，写 `group_run.cs` / `modify_record.cs` 之前查一遍。

### Blob 工具 (Cognex.VisionPro.Blob)

| 直觉写法（❌ 会编译报错） | 正确写法 | 原因 |
|---|---|---|
| `blob.RunParams.HardFixedThreshold = 150` | `blob.RunParams.SegmentationParams.HardFixedThreshold = 150` | 阈值在 `SegmentationParams` 子对象里 |
| `blob.RunParams.ConnectivityMode = EightConnected` | `blob.RunParams.ConnectivityMode = CogBlobConnectivityModeConstants.GreyScale` | 枚举名完全不同，无 `EightConnected` |
| `blob.RunParams.SegmentationParams.Polarity = LightBlobs` | `blob.RunParams.SegmentationParams.Polarity = CogBlobSegmentationPolarityConstants.LightBlobs` | 极性是枚举常量，不是裸字符串 |
| `blob.Results[0].Area` | `CogBlobResultCollection blobs = blob.Results.GetBlobs(); foreach(CogBlobResult b in blobs) { b.Area }` | 必须调用 `GetBlobs()` 获取集合 |
| `blob.Results[0].GetBoundingBox()` | `b.GetBoundingBox(CogBlobAxisConstants.PixelAlignedNoExclude)` | `GetBoundingBox` 需要轴对齐参数 |
| `blob.Results[0].GetBoundary()` | 直接用 `b.GetBoundary()` | `GetBoundary()` 无参，返回 `CogPolygon` |
| `CogBlobResult b; b.Width` / `b.Height` | 无此属性 | 用 `GetBoundingBox(...).SideXLength / SideYLength` 间接获取尺寸 |

### 图形 (CogRectangle / CogCircle / CogLineSegment / CogGraphicLabel)

| 直觉写法（❌） | 正确写法 | 原因 |
|---|---|---|
| `rect.Width / rect.Height` | `rect.SideXLength / rect.SideYLength` | `CogRectangleAffine` 没有 Width/Height 属性 |
| `rect.SetXY(x, y)` | `rect.SetCenterWidthHeight(cx, cy, w, h)` | `CogRectangle` 用 `SetCenterWidthHeight` |
| `rect.LineWidth = 3` | `rect.LineWidthInScreenPixels = 3` | 属性名带 `InScreenPixels` 后缀 |
| `label.SetXY(x, y)` | `label.X = x; label.Y = y` | `CogGraphicLabel` 用属性赋值，没有 `SetXY` |
| `label.FontSize = 20` | `label.Font = new System.Drawing.Font("Arial", 20, FontStyle.Bold)` | 没有 `FontSize` 属性，用完整 `Font` 对象 |
| `circle.SetRadius(r)` | `circle.SetCenterRadius(cx, cy, r)` | `CogCircle` 必须同时设置圆心和半径 |
| `new CogRectangle(x, y, w, h)` | `new CogRectangle(); rect.SetCenterWidthHeight(...)` | 构造函数不接受参数 |

### 图像类型

| 直觉写法（❌） | 正确写法 | 原因 |
|---|---|---|
| `CogImage8Grey img8 = (CogImage8Grey)img` | 直接强转即可（灰度源时） | 但如果 `img` 是彩色 `CogImage24PlanarColor`，强转会抛异常。先用 `CogImageConvertTool` 转灰度 |
| `img8 = CogImage8Grey(img)` | 构造器不接受 `ICogImage` | `CogImage8Grey` 构造器只接受 `System.Drawing.Bitmap` |

### ToolBlock 脚本通用

| 直觉写法（❌） | 正确写法 | 原因 |
|---|---|---|
| `tb.Tools[0]` | `tb.Tools["CogBlobTool1"]` | ToolBlock 工具集合是**字符串索引器**，不接受 int |
| `tb.Inputs[0]` | `tb.Inputs["Threshold"]` | 同上，Inputs/Outputs 也是字符串索引 |
| 把 `public` 字段声明在 `GroupRun()` 方法体内 | 声明在 `class CogToolBlockAdvancedScript` 层级 | 跨方法传数据必须用**脚本类的 public 字段**（如 `public int m_Index;`），不能在方法体里声明 |
| 跨 `GroupRun` / `ModifyLastRunRecord` 传数据用局部变量 | 声明类级 public 字��� | 两个方法各自独立，局部变量不可跨用；类字段持久存在于 ToolBlock 实例 |

### 批量/文件夹遍历

| 需求 | 模式 | 说明 |
|---|---|---|
| 逐张处理多张图片 | 不能在 ToolBlock 初始化时 `Open` 固定路径 | 在 `GroupRun` 脚本里用 `Directory.GetFiles(folder, "*.png")` 遍历，维护 `m_CurrentIndex` 类字段，每次 Run 加载下一张 |
| `CogImageFileTool` 一次只能加载一张 | 不是 bug，是设计 | 批量遍历是脚本逻辑，不是图源工具的能力 |

### 通用编码规则

- **枚举常量永远要带完整命名空间前缀**（如 `CogBlobConnectivityModeConstants.GreyScale`），不能写裸常量名。
- **`CogColorConstants` 没有 `Transparent`** —— 用 `Black` 代替。
- **集合遍历**：VP 的结果集合（`CogBlobResultCollection` / `CogIDResultCollection` 等）必须用 `foreach` 遍历单个元素，不能直接索引 `[0]`。
- **图像处理管道**：`InputImage`(彩色) → `CogImageConvertTool`(转灰度) → **所有分析工具都用灰度图**。直接在彩色图上跑 Caliper/Blob/ID 可能导致类型不匹配。
