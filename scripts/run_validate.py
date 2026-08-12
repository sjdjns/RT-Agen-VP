# -*- coding: utf-8 -*-
"""Layer A — 参数化交叉验证框架（不绑定任务）。

在 STA 线程中驱动 VP API 复跑检测逻辑，对真值比对量化指标。

用法：
  python run_validate.py <validate_spec.json>

validate spec 结构（完全参数化）：
  {
    "tools": [                          // 按序初始化并跑的工具列表
      {"type": "Cognex.VisionPro.Caliper.CogFindCircleTool", "name": "fc",
       "init": {"ExpectedCircularArc": {"CenterX": 500, "CenterY": 400, "Radius": 80}}},
      {"type": "Cognex.VisionPro.Blob.CogBlobTool", "name": "blob",
       "init": {"SegmentationParams": {"Mode": "HardFixedThreshold", "Polarity": "LightBlobs",
                                        "HardFixedThreshold": 150}}}
    ],
    "test_images": [                    // 测试图片路径列表
      "C:/path/to/image1.bmp",
      "C:/path/to/image2.bmp"
    ],
    "checks": [                         // 检测算法（每个 check 是处理一张图的函数名，对应下方 Python 函数）
      {"func": "check_circle_detection", "args": {"expected_cx": [500], "expected_cy": [400],
       "expected_r": [80], "tolerance": 10.0}},
      {"func": "check_blob_area", "args": {"ng_threshold": 400}}
    ],
    "image_prep": {                     // 图像预处理
      "convert_grey": true              // 是否先转灰度（默认 true）
    }
  }

所有阈值/期望值都由用户定义，Agent 不臆造。
"""
import os, sys, json, threading

def delete_acc_env():
    for k in list(os.environ):
        if k.startswith("ACC_"):
            del os.environ[k]


def run_validate(spec, base_dir="."):
    """在 STA 线程里跑验证。返回 (passed, report)。"""
    result = {"ok": None, "report": {}}
    err = [None]

    def _run():
        try:
            delete_acc_env()
            # ---- VP 加载 ----
            # 沿用 probe 能力发现 VP 根，此处简化：假设 sys.path 已配好
            sys.path.insert(0, r"D:\VisionPro\VisionPro\ReferencedAssemblies")
            sys.path.insert(0, r"D:\VisionPro\VisionPro\bin")
            import clr
            clr.AddReference("System.Drawing")
            clr.AddReference("Cognex.VisionPro")
            clr.AddReference("Cognex.VisionPro.Core")
            clr.AddReference("Cognex.VisionPro.Caliper")
            clr.AddReference("Cognex.VisionPro.Blob")
            clr.AddReference("Cognex.VisionPro.ImageFile")
            clr.AddReference("Cognex.VisionPro.ImageProcessing")
            clr.AddReference("Cognex.VisionPro.ToolGroup")
            from Cognex.VisionPro.ImageFile import CogImageFileTool, CogImageFileModeConstants
            from Cognex.VisionPro.ImageProcessing import CogImageConvertTool

            report = {"images": []}
            all_passed = True

            for img_path in spec.get("test_images", []):
                full_img = img_path if os.path.isabs(img_path) else os.path.join(base_dir, img_path)
                img_result = {"file": full_img, "checks": []}
                # 加载图像
                ft = CogImageFileTool()
                ft.Operator.Open(full_img, CogImageFileModeConstants.Read)
                ft.Run()
                raw = ft.OutputImage
                if raw is None:
                    img_result["error"] = "无法加载图像"
                    report["images"].append(img_result)
                    all_passed = False
                    continue
                # 转灰度
                conv = CogImageConvertTool()
                conv.InputImage = raw
                conv.Run()
                grey = conv.OutputImage
                # 初始化工具
                tools = {}
                import clr as _clr_ref
                for tdef in spec.get("tools", []):
                    full_type = tdef["type"]
                    name = tdef["name"]
                    ty = resolve_clr_type(full_type)
                    if ty is None:
                        img_result["checks"].append({"func": "init:%s" % name, "ok": False,
                                                      "msg": "类型未找到"})
                        continue
                    obj = _clr_ref.GetClrType(ty).Assembly.CreateInstance(ty.FullName)
                    if hasattr(obj, "Name"):
                        obj.Name = name
                    tools[name] = obj
                    # 设置参数
                    init = tdef.get("init", {})
                    _apply_init(obj, init)
                # 跑检测
                for ck in spec.get("checks", []):
                    func_name = ck["func"]
                    args = ck.get("args", {})
                    fn = globals().get(func_name)
                    if fn is None:
                        # 检查是否在本地定义
                        fn = CHECK_FUNCTIONS.get(func_name)
                    if fn is None:
                        img_result["checks"].append({"func": func_name, "ok": False,
                                                      "msg": "检测函数未定义"})
                        all_passed = False
                        continue
                    try:
                        ok, msg = fn(grey, tools, **args)
                    except Exception as e:
                        ok, msg = False, str(e)
                    img_result["checks"].append({"func": func_name, "ok": ok, "msg": msg})
                    if not ok:
                        all_passed = False
                report["images"].append(img_result)
            result["ok"] = all_passed
            result["report"] = report
        except Exception as e:
            err[0] = str(e)

    th = threading.Thread(target=_run)
    th.daemon = True
    th.start()
    th.join(timeout=120)
    if err[0]:
        return False, {"error": err[0]}
    return result["ok"], result["report"]


def resolve_clr_type(full):
    """CLR 类型解析（同 build_toolblock 的 resolve_type）。"""
    from System import Type as ST
    t = ST.GetType(full)
    if t is not None:
        return t
    try:
        mod_name, cls_name = full.rsplit(".", 1)
        mod = __import__(mod_name, fromlist=[cls_name])
        return getattr(mod, cls_name)
    except Exception:
        return None


def _apply_init(obj, params):
    """递归设置对象属性（支持嵌套 dict）。"""
    for key, val in (params or {}).items():
        try:
            prop = clr.GetClrType(obj.GetType()).GetProperty(key)
        except Exception:
            continue
        if prop is None:
            continue
        if isinstance(val, dict):
            inner = prop.GetValue(obj, None)
            if inner is not None:
                _apply_init(inner, val)
        elif prop.CanWrite:
            prop.SetValue(obj, val, None)


# ---- 内置通用检测函数（参数化，不写死） ----
CHECK_FUNCTIONS = {}

def check_circle_detection(grey_img, tools, expected_cx=None, expected_cy=None,
                           expected_r=None, tolerance=10.0, tool_name="fc"):
    fc = tools.get(tool_name)
    if fc is None:
        return False, "工具 %s 未初始化" % tool_name
    fc.InputImage = grey_img
    fc.Run()
    res = fc.Results
    if res is None or res.Count < 1 or res.GetCircle() is None:
        return False, "未找到圆"
    c = res.GetCircle()
    ok = True
    msgs = []
    if expected_cx and len(expected_cx) > 0:
        dx = abs(c.CenterX - expected_cx[0])
        ok = ok and dx <= tolerance
        msgs.append("cx_err=%.2f" % dx)
    if expected_cy and len(expected_cy) > 0:
        dy = abs(c.CenterY - expected_cy[0])
        ok = ok and dy <= tolerance
        msgs.append("cy_err=%.2f" % dy)
    if expected_r and len(expected_r) > 0:
        dr = abs(c.Radius - expected_r[0])
        ok = ok and dr <= tolerance
        msgs.append("r_err=%.2f" % dr)
    return ok, " | ".join(msgs) if msgs else "OK"


CHECK_FUNCTIONS["check_circle_detection"] = check_circle_detection


def check_blob_area(grey_img, tools, ng_threshold=400, tool_name="blob"):
    blob = tools.get(tool_name)
    if blob is None:
        return False, "工具 %s 未初始化" % tool_name
    blob.InputImage = grey_img
    blob.Run()
    res = blob.Results
    if res is None:
        return False, "Blob 无结果"
    blobs = res.GetBlobs()
    if blobs is None:
        return False, "GetBlobs 返回 null"
    defect_area = 0.0
    for b in blobs:
        if b.Area >= 8:
            defect_area += b.Area
    is_ng = defect_area >= ng_threshold
    return not is_ng, "defect_area=%.1f, threshold=%.1f, %s" % (defect_area, ng_threshold,
                                                                  "NG" if is_ng else "OK")


CHECK_FUNCTIONS["check_blob_area"] = check_blob_area


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python run_validate.py <validate_spec.json>")
        sys.exit(1)
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(sys.argv[1]))
    ok, report = run_validate(spec, base)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print("\n===== 结果 =====")
    print("通过" if ok else "失败")
    sys.exit(0 if ok else 1)
