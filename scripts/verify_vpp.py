# -*- coding: utf-8 -*-
"""Layer C — 通用 .vpp 结构核验（不绑定任务）。

用法：
  python verify_vpp.py <vpp_path> [spec_path]

校验项（全部可配置）：
  - 反序列化成功
  - ToolBlock 名称非空
  - 工具数量、名称列表（传 spec 则比对预期值，不传则只打印）
  - 输入/输出终端（同上）
  - LastRunRecordEnable (必须为 CompositeSubToolRecords，否则叠加不显示)
  - Script.Source 非空 + 脚本引用数非零
  - 脚本引用是否包含 spec["required_refs"] 中的程序集

exits 0 = 全过, exits 1 = 有失败项
"""
import os, sys, json

def delete_acc_env():
    for k in list(os.environ):
        if k.startswith("ACC_"):
            del os.environ[k]

def load_vp():
    """复用 probe 发现 VP 根，加 sys.path + clr，返回 CogSerializer。"""
    sys.path.insert(0, os.path.dirname(__file__))
    import probe_vp_env as probe
    probe.delete_acc_env()
    roots = probe.find_vp_roots()
    import clr
    for r in roots:
        core = probe.find_core_dll(r)
        if not core:
            continue
        ref_dir = os.path.join(r, "ReferencedAssemblies")
        bin_dir = os.path.join(r, "bin")
        if not os.path.isdir(ref_dir):
            ref_dir = os.path.dirname(core)
        sys.path.insert(0, ref_dir)
        if os.path.isdir(bin_dir):
            sys.path.insert(0, bin_dir)
        try:
            clr.AddReference("Cognex.VisionPro")
            clr.AddReference("Cognex.VisionPro.Core")
            clr.AddReference("Cognex.VisionPro.ToolGroup")
            from Cognex.VisionPro import CogSerializer
            return CogSerializer
        except Exception:
            continue
    raise SystemExit("无法加载 VP 程序集")

def verify(vpp_path, spec=None):
    """返回 (passed: bool, report: dict)"""
    report = {"file": vpp_path, "checks": []}
    passed = True

    if not os.path.isfile(vpp_path):
        report["checks"].append({"item": "file_exists", "ok": False, "msg": "文件不存在"})
        return False, report
    report["checks"].append({"item": "file_exists", "ok": True})
    report["vpp_size"] = os.path.getsize(vpp_path)

    # 反序列化
    try:
        CogSerializer = load_vp()
        tb = CogSerializer.LoadObjectFromFile(vpp_path)
        report["checks"].append({"item": "deserialize", "ok": True})
    except Exception as e:
        report["checks"].append({"item": "deserialize", "ok": False, "msg": str(e)})
        return False, report

    # 名称
    name = tb.Name or ""
    ok = len(name) > 0
    report["checks"].append({"item": "name", "ok": ok, "value": name})
    if not ok:
        passed = False

    # 工具
    tool_names = [t.Name for t in tb.Tools]
    report["tool_count"] = len(tool_names)
    report["tool_names"] = tool_names
    if spec and "tools" in spec:
        expected = [t["name"] for t in spec["tools"]]
        # 图源工具由 img_source 自动添加，补到 expected 里
        src = spec.get("img_source", "file")
        auto = []
        if src == "file":
            auto = ["CogImageFileTool1"]
        elif src == "input":
            auto = ["CogImageConvertTool1"]
        elif src == "both":
            auto = ["CogImageFileTool1", "CogImageConvertTool1"]
        expected_all = auto + expected
        for ename in expected_all:
            found = ename in tool_names
            report["checks"].append({"item": "tool:%s" % ename, "ok": found,
                                     "msg": "" if found else "缺失"})
            if not found:
                passed = False
        for tname in tool_names:
            if tname not in expected_all:
                report["checks"].append({"item": "tool:%s" % tname, "ok": False,
                                         "msg": "不在 spec 声明的工具列表中"})
                passed = False

    # 输入终端
    input_names = [i.Name for i in tb.Inputs]
    report["input_names"] = input_names
    if spec and "inputs" in spec:
        expected_in = [i["name"] for i in spec["inputs"]]
        # 自动终端
        src = spec.get("img_source", "file")
        if src in ("input", "both"):
            expected_in.insert(0, "InputImage")
        if src == "both":
            expected_in.insert(1, "UseFileImage")
            expected_in.insert(2, "ImageFilePath")
        for ein in expected_in:
            found = ein in input_names
            report["checks"].append({"item": "input:%s" % ein, "ok": found,
                                     "msg": "" if found else "缺失"})
            if not found:
                passed = False

    # 输出终端
    output_names = [o.Name for o in tb.Outputs]
    report["output_names"] = output_names
    if spec and "outputs" in spec:
        for eout in spec["outputs"]:
            found = eout["name"] in output_names
            report["checks"].append({"item": "output:%s" % eout["name"], "ok": found,
                                     "msg": "" if found else "缺失"})
            if not found:
                passed = False

    # LastRunRecordEnable
    try:
        lre = tb.LastRunRecordEnable
        lre_str = str(lre)
        ok_lre = "CompositeSubToolRecords" in lre_str or "Composite" in lre_str
        report["checks"].append({"item": "LastRunRecordEnable", "ok": ok_lre, "value": lre_str})
        if not ok_lre:
            passed = False
    except Exception as e:
        report["checks"].append({"item": "LastRunRecordEnable", "ok": False, "msg": str(e)})
        passed = False

    # 脚本引用
    try:
        refs = [ra.Name for ra in tb.Script.References]
        report["script_refs"] = refs
        report["checks"].append({"item": "script_refs_count", "ok": len(refs) > 0,
                                 "value": len(refs)})
    except Exception:
        report["checks"].append({"item": "script_refs_count", "ok": False, "msg": "无法读取"})
        passed = False

    if spec and "required_refs" in spec:
        for rr in spec["required_refs"]:
            found = any(rr in r for r in report.get("script_refs", []))
            report["checks"].append({"item": "ref:%s" % rr, "ok": found,
                                     "msg": "" if found else "缺失"})
            if not found:
                passed = False

    # 脚本源码
    src = tb.Script.Source or ""
    ok_src = len(src) > 100
    report["checks"].append({"item": "script_source", "ok": ok_src,
                             "value": "%d chars" % len(src)})
    if not ok_src:
        passed = False

    return passed, report


if __name__ == "__main__":
    delete_acc_env()
    vpp = sys.argv[1]
    spec = None
    if len(sys.argv) > 2:
        spec = json.load(open(sys.argv[2], encoding="utf-8"))
    ok, report = verify(vpp, spec)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print("\n===== 结果 =====")
    print("通过" if ok else "失败")
    sys.exit(0 if ok else 1)
