---
name: RT-VP-1.0.0
description: >-
  Programmatically build, configure, and validate Cognex VisionPro (.vpp) vision inspection projects
  WITHOUT using the QuickBuild GUI. This skill should be used when a user asks to generate a VisionPro
  job/toolblock for any visual task (measurement, defect inspection, OCR/barcode ID, PMAlign
  alignment, Blob, color matching, geometric fitting, etc.), when the user wants to operate VisionPro
  from code because GUI/manual wiring is impractical, or when the user needs to verify whether a
  VisionPro task meets its acceptance criteria. It covers environment auto-discovery (version +
  tool inventory via reflection, no hardcoded paths), a generic ToolBlock scaffold with
  requirement-driven algorithm/graphic slots, and a three-layer acceptance framework
  (STA-driven API replay, cv2 visual preview, .vpp structure check).
agent_created: true
---

# VP ToolBlock Builder

## Overview

Enable an AI agent to produce runnable Cognex VisionPro `.vpp` projects for **any** visual task
entirely from code, and to verify that a built task actually meets its acceptance criteria —
all without touching the QuickBuild GUI. The approach is deliberately **generic**: no tool name,
file path, or algorithm is hardcoded.

## When To Use

- User asks to build a VisionPro job/toolblock for measurement, defect inspection, OCR/ID,
  alignment, Blob, color matching, geometric fitting, etc.
- User cannot or will not manually wire tools in QuickBuild and wants a zero-wiring `.vpp`.
- User needs to confirm a VisionPro task is "done correctly" without opening the GUI.
- User switches VisionPro versions or machines and the old hardcoded paths break.

## Resources

- `scripts/probe_vp_env.py` — Auto-discover the VP install root, version, and full tool inventory
  via registry + filesystem scan + reflection.
- `scripts/build_toolblock.py` — Generic ToolBlock scaffold generator. Takes a spec (tool list,
  image source, I/O terminals, algorithm/overlay slot files) and emits a `.vpp`.
- `scripts/verify_vpp.py` — **Layer C**: structure check (deserialize, assert tools/IO/refs).
- `scripts/make_preview.py` — **Layer B**: cv2-based overlay preview (parameterized spec).
- `scripts/run_validate.py` — **Layer A**: STA-driven VP API replay + ground-truth comparison.
- `references/api_reference.md` — Hard-won VP API constraints and workarounds.

## Workflow（强制执行顺序，不可跳过）

### Step 0 — 前置确认
与用户确认需求后，必须在后续步骤中**严格遵守**：
- 所有工具名必须从 `probe_vp_env.py` 的枚举列表中匹配，**不得凭记忆编造**。
- 不写死任何路径、阈值、算法——一切由 spec 驱动。
- 生成 `.vpp` 后必须跑 Step 4 三层验证，全部通过才算完成。

### Step 1 — 环境探测（强制执行，不可跳过）
运行 `scripts/probe_vp_env.py`。拿到：
- VP 安装根路径 + `ReferencedAssemblies` 目录
- 程序集版本号
- **完整工具枚举列表**（所有 `*Tool` / `*ToolGroup` 类型）

此步骤必须**最先执行**。之后所有工具选择、类型引用都只能从这次探测的输出中选取。

### Step 2 — 工具选择 + API 确认（禁止凭直觉）
根据任务需求，**从 Step 1 的工具枚举列表中匹配**合适的工具名（含完整命名空间）。

**强制规则**：
- 编写 `group_run.cs` / `modify_record.cs` 之前，**必须先读** `references/api_reference.md` 的
  **第 8 节"常见工具 API 非直觉对照表"**，确认你用的每个属性/枚举/方法名真实存在。
  VP 的 API 命名与 .NET 常规习惯差异极大（例如阈值在 `SegmentationParams` 子对象、矩形尺寸叫
  `SideXLength` 而非 `Width`），凭直觉编写几乎一定出错。宁可多花 30 秒查表，省下 3 轮编译回合。

### Step 3 — 生成 .vpp（spec 驱动，四选一图源）
编写 `spec.json` + `group_run.cs` + `modify_record.cs`，调用 `scripts/build_toolblock.py` 生成。
spec 字段见 build_toolblock.py 顶部文档。图源模式：
- `file`：单张图片离线自测
- `input`：相机实时（预留 InputImage 终端，外部 `CogAcqFifoTool` 喂图）
- `both`：相机+图片一键切换（`UseFileImage` + `ImageFilePath` 终端）
- `folder`：文件夹批量遍历，每次 Run 加载下一张（`ImageFolderPath` 终端，`CurrentImage` 输出当前文件名，类字段 `m_CurrentIndex` / `m_Files` 维护遍历状态）

### Step 4 — 三层验证（全部通过才算完成）
**每生成一个 .vpp 必须跑完三层**，不通过则修改 spec/算法后重新生成。

- **Layer C**：`python verify_vpp.py <vpp_path> [spec_path]`
  反序列化→检查工具名/数量→输入/输出终端→LastRunRecordEnable→脚本引用→源码长度。
- **Layer B**：`python make_preview.py <overlay_spec.json>`
  用 cv2 渲染叠加预览图，用户不开 VP 即可核对布局。
- **Layer A**：`python run_validate.py <validate_spec.json>`
  在 STA 线程中驱动 VP API 复跑检测，对比真值（圆心偏差、缺陷面积阈值等）。

### Step 5 — 交付与迭代
用户打开 `.vpp`，选 `LastRun.CogImageFileTool1.OutputImage`（file 模式）或
`LastRun.CogImageConvertTool1.OutputImage`（input/both 模式）查看叠加。
按反馈修改 spec/算法/叠加，重新生成并验证。

## Key Constraints
- ToolBlock/Job 内部连线**无公开 API** → 自包含图源零手动连线。
- 沙箱 `csc.exe` 拦截 → `Build()` 永远失败；VP 打开时自动重编译。
- VP COM/STA → 所有 VP API 调用在 STA 线程。
- `CogColorConstants` 无 `Transparent`；用 `Black/Red/Green/Blue/Yellow`。
- 性能策略：首次全量加载 88+ dll（≈5s），后续缓存验证后直载（≈4s）；VP 安装变更自动重探测。
