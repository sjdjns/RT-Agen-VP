# RT-VP

**用脚本生成 Cognex VisionPro `.vpp` 检测项目，不碰 QuickBuild GUI。**

拖工具、连 IO、调参数、写脚本——每次换需求在 QuickBuild 里重搭一遍是体力活。RT-VP 让你用几行 JSON + C# 片段就生成一个可直接运行的 `.vpp` 文件。

## 快速开始

```bash
# 1. 写 spec（工具、IO、图源模式）
cat > spec.json << EOF
{
  "img_source": "file",
  "img_path": "C:/path/to/image.bmp",
  "tools": [
    {"type": "Cognex.VisionPro.Caliper.CogFindCircleTool", "name": "CogFindCircleTool1"}
  ],
  "outputs": [{"name": "ResultString", "type": "String"}],
  "group_run": "group_run.cs",
  "modify_record": "modify_record.cs",
  "out_vpp": "output.vpp"
}
EOF

# 2. 写检测算法（C# 片段，不用写 class）
cat > group_run.cs << 'EOF'
var fc = (CogFindCircleTool)tb.Tools["CogFindCircleTool1"];
fc.InputImage = (CogImage8Grey)img;
fc.Run();
tb.Outputs["ResultString"].Value = fc.Results.GetCircle().Radius.ToString();
EOF

# 3. 生成
python scripts/build_toolblock.py spec.json

# 4. 验证结构
python scripts/verify_vpp.py output.vpp spec.json

# 5. 双击 output.vpp，QuickBuild 里 Run
```

## 四选一图源

| `img_source` | 场景 |
|-------------|------|
| `file` | 单张图片离线测试 |
| `input` | 相机实时（`CogAcqFifoTool` 喂 `InputImage`） |
| `both` | 相机 + 图片一键切换 |
| `folder` | 文件夹批量遍历，逐张检测 |

## 三层验证

不靠肉眼判断对错：

- **C** — 反序列化 `.vpp`，断言结构完整性
- **B** — OpenCV 渲染叠加预览图
- **A** — STA 线程直驱 VP API 复跑，对比真值

## 设计决策

1. **不连线**。VP 的 ToolBlock 内部连线无公开 API，代码无法操作。方案：把图源放进 ToolBlock 内部，`GroupRun` 脚本直接传 `InputImage` 给下游工具。
2. **全量加载**。88 个 Cognex 程序集一次加载，保证任何工具都能解析，不会出现"命名空间不存在"的半路上报错。
3. **环境自适应**。注册表探测 + 多盘符兜底 + x86/x64 多根回退，不写死路径。
4. **缓存加速**。首次探测后写入缓存，后续秒开，VP 版本变更自动重探测。

## 前置条件

- Cognex VisionPro 9.x 安装在本机
- Python 3.10+ + pythonnet
- `pip install pythonnet numpy opencv-python`

## API 陷阱

VP 的命名和 .NET 习惯差异很大，凭直觉写几乎一定出错。常见陷阱已整理在 [references/api_reference.md](references/api_reference.md)。

## 限制

- 适用于 VP 9.x（.NET Framework + COM）。VP 10+ 需要重写加载链路。
- 必须本机装 VP；沙箱只能生成不能真跑。
- QuickBuild 私有配方 / Job 层连线不适用（VP 不暴露相关 API）。

## 许可

MIT
