# -*- coding: utf-8 -*-
"""通用 VP ToolBlock 脚手架生成器 —— 不写死任何工具/算法/路径。

用法：写好 spec.json（工具清单、I/O、图源模式、两个 C# 片段文件），运行本脚本即可生成 .vpp。
算法逻辑写在 group_run.cs / modify_record.cs 两个片段里（不含 class 包裹），作为"插槽"注入。
环境（VP 根、引用目录、版本、脚本语言枚举）自动探测，无需硬编码。

spec 字段：
  tools        : [{"type": "Cognex.VisionPro.Caliper.CogFindCircleTool", "name": "CogFindCircleTool1"}, ...]
  inputs       : [{"name": "InputImage", "type": "ICogImage"}, ...]   # type 省略则默认 System.Object
  outputs      : [{"name": "ResultString", "type": "String"}, ...]
  img_source   : "file" | "input" | "both" | "folder"
                 file   = 内部 CogImageFileTool 零连线图源, 离线自测单张
                 input  = 相机实时, 预留 InputImage 终端且内部用 CogImageConvertTool 透传
                 both   = 相机+图片一键切换(UseFileImage bool + ImageFilePath str)
                 folder = 文件夹批量, 每次 Run 自动加载下一张(环), CurrentImage 输出文件名
                          spec 用 folder_path + folder_filter(默认 *.png)
  img_path     : file 模式下的图像绝对路径
  group_run    : GroupRun 算法片段文件路径（插入 __GROUP_RUN_BODY__）
  modify_record: ModifyLastRunRecord 叠加片段文件路径（插入 __MODIFY_RECORD_BODY__）
  out_vpp      : 输出 .vpp 绝对路径
  extra_usings : ["Cognex.VisionPro.PMAlign", ...]  # 片段用到的命名空间
"""
import os, sys, json, hashlib, time

# ---- 环境自适应：复用 probe_vp_env 的探测能力（不写死路径） ----
sys.path.insert(0, os.path.dirname(__file__))
import probe_vp_env as probe

# ============================================================
# 优化 B：VP 环境文件缓存
# 缓存 root/ref_dir/bin_dir + 全部已加载程序集名称列表。
# 缓存命中时直接按名加载全部（跳过注册表/glob 发现），
# VP 安装变更（程序集数量变化）自动失效重探测。
# ============================================================
_VP_CACHE_PATH = os.path.expanduser("~/.workbuddy/cache/vp_env_cache.json")

def _read_vp_cache():
    try:
        if not os.path.isfile(_VP_CACHE_PATH):
            return None
        with open(_VP_CACHE_PATH, "r") as f:
            data = json.load(f)
        root = data.get("root_used", "")
        ref = data.get("ref_dir", "")
        if root and os.path.isdir(root) and ref and os.path.isdir(ref):
            return data
        return None
    except Exception:
        return None

def _write_vp_cache(data):
    try:
        os.makedirs(os.path.dirname(_VP_CACHE_PATH), exist_ok=True)
        data["cached_at"] = time.time()
        with open(_VP_CACHE_PATH, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

def _count_cognex_dlls(ref_dir):
    """快速统计 ref_dir 下 Cognex.*.dll 数量，用于缓存有效性校验。"""
    try:
        return sum(1 for d in os.listdir(ref_dir)
                   if d.startswith("Cognex.") and d.endswith(".dll"))
    except Exception:
        return -1

# ============================================================
# 优化 C：memoize resolve_lang
# ============================================================
_LANG_CACHE = None


def load_vp():
    """删 ACC_* 后自动发现 VP 安装根，加载基座 + 全部 Cognex 程序集（保证 100% 覆盖）。
    首次运行做注册表+glob+全量加载，后续从缓存验证后直载（发现阶段瞬时跳过）。
    VP 安装变更（程序集数量变化）自动触发重探测。"""
    probe.delete_acc_env()
    import clr

    # ---- 缓存命中：只需验证安装未变，然后直接批量加载 ----
    cached = _read_vp_cache()
    if cached:
        root_used = cached["root_used"]
        ref_dir = cached["ref_dir"]
        bin_dir = cached.get("bin_dir", os.path.join(root_used, "bin"))
        cached_count = cached.get("assembly_count", -1)
        cached_names = cached.get("assembly_names", [])
        # 快速校验：VP 安装变动（增减了程序集）→ 缓存失效
        actual_count = _count_cognex_dlls(ref_dir)
        if actual_count < 0 or cached_count < 0 or actual_count != cached_count:
            print("[cache] 程序集数量变化 (%d → %d)，重新探测" % (cached_count, actual_count))
            cached = None
        else:
            sys.path.insert(0, ref_dir)
            if os.path.isdir(bin_dir):
                sys.path.insert(0, bin_dir)
            clr.AddReference("System.Drawing")
            for name in cached_names:
                try:
                    clr.AddReference(name)
                except Exception:
                    pass
            from Cognex.VisionPro.ToolBlock import CogToolBlock
            _ = CogToolBlock()
            n = len(cached_names)
            print("[cache] VP 根: %s | 程序集: %d (全部直载)" % (root_used, n))
            return root_used, ref_dir

    # ---- 缓存未命中：完整发现 + 全量加载 ----
    roots = probe.find_vp_roots()
    core, ref_dir, root_used, bin_dir = None, None, None, None
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
            clr.AddReference("System.Drawing")
            clr.AddReference("Cognex.VisionPro")
            clr.AddReference("Cognex.VisionPro.Core")
            clr.AddReference("Cognex.VisionPro.ToolGroup")
            from Cognex.VisionPro.ToolBlock import CogToolBlock
            _ = CogToolBlock()
            root_used = r
            break
        except Exception as e:
            print("  [跳过] 根", r, "加载失败:", repr(e)[:80])
            continue
    if not root_used:
        raise SystemExit("所有候选根均无法加载 Cognex 程序集（检查 VP 是否安装 / 位数是否匹配）")

    # 全量加载全部 Cognex.*.dll，收集程序集名称列表
    assembly_names = []
    for dll in sorted(d for d in os.listdir(ref_dir)
                      if d.startswith("Cognex.") and d.endswith(".dll")):
        name = os.path.splitext(dll)[0]
        try:
            clr.AddReference(name)
            assembly_names.append(name)
        except Exception:
            pass
    count = len(assembly_names)
    print("  [探测] VP 根: %s | 程序集: %d (全量加载)" % (root_used, count))
    _write_vp_cache({
        "root_used": root_used, "ref_dir": ref_dir, "bin_dir": bin_dir,
        "assembly_names": assembly_names, "assembly_count": count,
    })
    return root_used, ref_dir


def resolve_type(s):
    """把 spec 里的类型全名解析成 CLR Type，不写死具体类型。"""
    import clr
    s = (s or "").strip()
    if not s or s in ("Object",):
        return __import__("System").Object
    if s == "String":
        return __import__("System").String
    if s == "Boolean":
        return __import__("System").Boolean
    if s == "Int32":
        return __import__("System").Int32
    if s == "Double":
        return __import__("System").Double
    if s == "ICogImage":
        from Cognex.VisionPro import ICogImage
        return ICogImage
    from System import Type as _ST
    t = _ST.GetType(s)
    if t is not None:
        return t
    # 回退：pythonnet 模块式解析（需对应程序集已加载）
    try:
        mod_name, cls_name = s.rsplit(".", 1)
        mod = __import__(mod_name, fromlist=[cls_name])
        return getattr(mod, cls_name)
    except Exception:
        return __import__("System").Object


def resolve_lang():
    """反射拿到 CogScriptLanguageConstants 枚举。C 优化：结果缓存，只跑一次。"""
    global _LANG_CACHE
    if _LANG_CACHE is not None:
        return _LANG_CACHE
    import clr
    from System import AppDomain
    for asm in AppDomain.CurrentDomain.GetAssemblies():
        try:
            types = asm.GetTypes()
        except Exception:
            continue
        for t in types:
            if t is not None and t.Name == "CogScriptLanguageConstants":
                try:
                    mod = __import__(t.Namespace, fromlist=[t.Name])
                    _LANG_CACHE = getattr(mod, t.Name)
                    return _LANG_CACHE
                except Exception:
                    return t
    return None


# ---- C# 脚本骨架：算法是插槽，不写死 ----
SCAFFOLD = r"""
using System;
using System.Collections.Generic;
using System.Drawing;
using Cognex.VisionPro;
using Cognex.VisionPro.ToolBlock;
__USING_IMAGEPROC__
// 注意：CogImageFileTool 在不同 VP 安装/位数下的程序集引用可能不同，
// 图源模板里用全名访问，避免 using 冲突导致脚本编译失败。
__EXTRA_USINGS__

public class CogToolBlockAdvancedScript : CogToolBlockAdvancedScriptBase
{
  private CogToolBlock _tb = null;
__CLASS_FIELDS__
  public override void Initialize(Cognex.VisionPro.ToolGroup.CogToolGroup host)
  { _tb = (CogToolBlock)host; base.Initialize(host); }

  public override bool GroupRun(ref string message, ref CogToolResultConstants result)
  {
    message = ""; result = CogToolResultConstants.Accept;
    CogToolBlock tb = _tb;
    // ---- 图像获取（由图源模式决定，不写死） ----
    __IMAGE_ACQUIRE__
    // ---- 检测算法插槽（任务驱动） ----
    __GROUP_RUN_BODY__
    return true;
  }

  public override void ModifyLastRunRecord(ICogRecord lastRecord)
  {
    try {
      CogToolBlock tb = _tb;
      // 叠加记录必须是"图像型工具的 OutputImage"子记录。ToolBlock 的 InputImage/OutputImage
      // 终端自身不产生可叠加子记录——所以 file 模式用内部 CogImageFileTool，input(相机) 模式
      // 用内部 CogImageConvertTool 透传，二者都提供稳定的 OutputImage 子记录来承载叠加。
      string term = "__OVERLAY_TERM__";
      ICogRecord imgRec = tb.FindRunRecord(lastRecord, term);
      if (imgRec == null) return;
      // ---- 图形叠加插槽（任务驱动） ----
      __MODIFY_RECORD_BODY__
    } catch (Exception) { }
  }
}
"""

IMAGE_ACQUIRE = {
    "file": r"""
    ICogImage img = null;
    try {
      var ft = (Cognex.VisionPro.ImageFile.CogImageFileTool)tb.Tools["CogImageFileTool1"];
      ft.Operator.Open(@"__IMG_PATH__", Cognex.VisionPro.ImageFile.CogImageFileModeConstants.Read);
      ft.Run();
      img = ft.OutputImage;
    } catch (Exception e0) { message += "IMG:" + e0.Message + ";"; }
    if (img == null) { message += "NO_IMAGE;"; return true; }
""",
    "input": r"""
    // 相机(或任意外部源)必须把图喂到 ToolBlock.InputImage 终端；ToolBlock 内部不写死任何图。
    // 经内部 CogImageConvertTool 透传：保证拿到稳定的灰度图(供分析) + 一个真实的 OutputImage
    // 子记录(承载叠加)。QuickBuild 连线：CogAcqFifoTool.OutputImage -> CogToolBlock1.InputImage
    ICogImage raw = (ICogImage)tb.Inputs["InputImage"].Value;
    if (raw == null) { message += "NO_IMAGE: connect camera to InputImage;"; return true; }
    var conv = (CogImageConvertTool)tb.Tools["CogImageConvertTool1"];
    conv.InputImage = raw;
    try { conv.Run(); } catch (Exception ec) { message += "CONV:" + ec.Message + ";"; }
    ICogImage img = conv.OutputImage;
    if (img == null) { message += "CONV_NULL;"; return true; }
""",
    "both": r"""
    // 可切换图源（相机 / 图片），由 UseFileImage 输入终端一键切换，无需改连线、无需改脚本。
    //  - UseFileImage=false(默认): 外部源(相机)喂 ToolBlock.InputImage
    //      QuickBuild: CogAcqFifoTool.OutputImage -> CogToolBlock1.InputImage
    //  - UseFileImage=true: 加载 ImageFilePath 输入终端指定的任意图片
    // 两者都经内部 CogImageConvertTool1(灰度透传)，叠加记录("CogImageConvertTool1.OutputImage")
    // 完全一致，切换零成本。
    bool useFile = false;
    try { useFile = (bool)tb.Inputs["UseFileImage"].Value; } catch (Exception) { }
    ICogImage raw = null;
    if (useFile) {
      var ft = (Cognex.VisionPro.ImageFile.CogImageFileTool)tb.Tools["CogImageFileTool1"];
      string fp = "";
      try { fp = (string)tb.Inputs["ImageFilePath"].Value; } catch (Exception) { }
      try {
        ft.Operator.Open(fp, Cognex.VisionPro.ImageFile.CogImageFileModeConstants.Read);
        ft.Run();
        raw = ft.OutputImage;
      } catch (Exception e0) { message += "IMG:" + e0.Message + ";"; }
      if (raw == null) { message += "NO_IMAGE(file):" + fp + ";"; return true; }
    } else {
      try { raw = (ICogImage)tb.Inputs["InputImage"].Value; }
      catch (Exception e0) { message += "IMG:" + e0.Message + ";"; }
      if (raw == null) { message += "NO_IMAGE: connect source to InputImage, or set UseFileImage=true + ImageFilePath;"; return true; }
    }
    var conv = (CogImageConvertTool)tb.Tools["CogImageConvertTool1"];
    conv.InputImage = raw;
    try { conv.Run(); } catch (Exception ec) { message += "CONV:" + ec.Message + ";"; }
    ICogImage img = conv.OutputImage;
    if (img == null) { message += "CONV_NULL;"; return true; }
""",
    "folder": r"""
    // 文件夹批量模式：每次 Run 自动加载下一张图片，循环遍历。
    // 输入终端 ImageFolderPath 指定文件夹；类字段 m_CurrentIndex + m_Files 维护遍历状态。
    // 输出终端 CurrentImage 显示当前文件名，叠加层可用 __FOLDER_INDEX__ 标记 [N/Total]。
    if (m_Files == null || m_Files.Length == 0) {
      string folder = "";
      try { folder = (string)tb.Inputs["ImageFolderPath"].Value; } catch (Exception) { }
      if (string.IsNullOrEmpty(folder)) { message += "NO_FOLDER;"; return true; }
      try {
        m_Files = System.IO.Directory.GetFiles(folder, __FOLDER_FILTER__);
        System.Array.Sort(m_Files);
      } catch (Exception e0) { message += "DIR:" + e0.Message + ";"; return true; }
      if (m_Files == null || m_Files.Length == 0) { message += "NO_FILES;"; return true; }
      m_CurrentIndex = 0;
    }
    // 循环索引（到达末尾回到开头）
    if (m_CurrentIndex >= m_Files.Length) m_CurrentIndex = 0;
    string currentFile = m_Files[m_CurrentIndex];
    ICogImage img = null;
    try {
      var ft = (Cognex.VisionPro.ImageFile.CogImageFileTool)tb.Tools["CogImageFileTool1"];
      ft.Operator.Open(currentFile, Cognex.VisionPro.ImageFile.CogImageFileModeConstants.Read);
      ft.Run();
      img = ft.OutputImage;
    } catch (Exception e0) { message += "IMG:" + e0.Message + ";"; }
    if (img == null) { message += "NO_IMAGE:" + currentFile + ";"; return true; }
    // 输出当前文件信息
    try { tb.Outputs["CurrentImage"].Value = "[" + (m_CurrentIndex + 1) + "/" + m_Files.Length + "] " + System.IO.Path.GetFileName(currentFile); }
    catch (Exception) { }
    m_CurrentIndex++;
""",
}


def make_terminal(entry, kind):
    """按 spec 创建 ToolBlock 终端；type 决定值类型，省略则默认 System.Object。"""
    from Cognex.VisionPro.ToolBlock import CogToolBlockTerminal
    name = entry["name"]
    ty = resolve_type(entry.get("type"))
    return CogToolBlockTerminal(name, ty)


# ============================================================
# 优化 D：TempCompile 源文件哈希缓存（源码不变则跳过编译检查）
# ============================================================
_SOURCE_HASH_CACHE = {}  # md5hex -> True/False


def set_script(tb, src, base_class, check=False):
    """注入 C# 源码到 ToolBlock。
    默认跳过 TempCompile/Build —— 沙箱编译器与本机 VP 编译器不同，结果不可靠；
    真正的编译发生在 VP 打开 .vpp 时。check=True 才跑语法检查（调试用）。"""
    from Cognex.VisionPro.ToolBlock import CogToolBlockScriptTypeConstants
    Lang = resolve_lang()
    script_csharp = getattr(Lang, "ScriptCSharp") if Lang else None
    tb.CreateNewScript(script_csharp, CogToolBlockScriptTypeConstants.Advanced)
    tb.Script.Source = src

    if not check:
        print("TempCompile: skipped (fast mode — VP recompiles on open)")
        return

    h = hashlib.md5(src.encode("utf-8")).hexdigest()
    if h in _SOURCE_HASH_CACHE:
        print("TempCompile: cached", _SOURCE_HASH_CACHE[h], "(source unchanged)")
        return
    try:
        ok = tb.Script.TempCompile()
        print("TempCompile:", ok)
        _SOURCE_HASH_CACHE[h] = ok
        # Build 在沙箱永远失败（csc.exe 拦截），跳过省时间
        if ok:
            try:
                res = tb.Script.Build(base_class, "")
                if res is not None and len(res) >= 2:
                    bok, errs = res[0], res[1]
                    print("Build ok:", bok, "| errors:", str(errs))
            except Exception:
                print("Build: skipped (sandbox limitation)")
        else:
            print("NOTE: TempCompile=False，本机 VP 打开时重编译。")
    except Exception as e:
        print("编译检查异常（跳过，本机 VP 打开会重编译）:", e)


def generate(spec, base_dir=None, check=False):
    """根据 spec 生成 ToolBlock 并保存为 .vpp。
    base_dir 用于把 spec 里的相对路径（group_run/modify_record/img_path）解析为绝对路径；
    check=True 才运行沙箱 TempCompile（调试用，默认跳过——VP 打开时自己编译）。"""
    if base_dir is None:
        base_dir = os.getcwd()
    import System
    import clr

    def _rp(p):
        if not p:
            return p
        return p if os.path.isabs(p) else os.path.join(base_dir, p)

    # ---- VP 环境准备（缓存加速，全量加载保证 100% 覆盖） ----
    core, ref_dir = load_vp()

    # 读取算法源码
    gr_body = (open(_rp(spec["group_run"]), encoding="utf-8").read()
               if spec.get("group_run") else "// (no group-run body)")
    mr_body = (open(_rp(spec["modify_record"]), encoding="utf-8").read()
               if spec.get("modify_record") else "// (no overlay)")
    extra = "\n".join("using " + u + ";" for u in spec.get("extra_usings", []))

    from Cognex.VisionPro.ToolBlock import (CogToolBlock, CogToolBlockTerminal,
                                              CogToolBlockAdvancedScriptBase)
    from Cognex.VisionPro import CogSerializer
    from Cognex.VisionPro.ImageFile import CogImageFileTool, CogImageFile, CogImageFileModeConstants
    from Cognex.VisionPro.ImageProcessing import CogImageConvertTool

    tb = CogToolBlock()
    tb.Name = "CogToolBlock1"
    lrEnum = tb.GetType().GetProperty("LastRunRecordEnable").PropertyType
    tb.LastRunRecordEnable = System.Enum.Parse(lrEnum, "CompositeSubToolRecords")

    # 图源：
    src_mode = spec.get("img_source", "file")
    overlay_term = "CogImageFileTool1.OutputImage"
    if src_mode == "file":
        ft = CogImageFileTool(); ft.Name = "CogImageFileTool1"
        try:
            ft.Operator = CogImageFile()
        except Exception as e:
            print("file operator init warn:", e)
        ft.Operator.Open(spec["img_path"], CogImageFileModeConstants.Read)
        tb.Tools.Add(ft)
    elif src_mode == "input":
        conv = CogImageConvertTool(); conv.Name = "CogImageConvertTool1"
        tb.Tools.Add(conv)
        overlay_term = "CogImageConvertTool1.OutputImage"
    elif src_mode == "both":
        ft = CogImageFileTool(); ft.Name = "CogImageFileTool1"
        try:
            ft.Operator = CogImageFile()
        except Exception as e:
            print("file operator init warn:", e)
        tb.Tools.Add(ft)
        conv = CogImageConvertTool(); conv.Name = "CogImageConvertTool1"
        tb.Tools.Add(conv)
        overlay_term = "CogImageConvertTool1.OutputImage"
    elif src_mode == "folder":
        ft = CogImageFileTool(); ft.Name = "CogImageFileTool1"
        try:
            ft.Operator = CogImageFile()
        except Exception as e:
            print("file operator init warn:", e)
        tb.Tools.Add(ft)
        overlay_term = "CogImageFileTool1.OutputImage"

    # 动态添加工具（类型由 spec 给全名，不写死映射）
    for t in spec.get("tools", []):
        full = t["type"]
        ty = resolve_type(full)
        if ty is None:
            raise SystemExit("找不到类型: " + full + "（请确认程序集已引用）")
        obj = __import__("System").Activator.CreateInstance(ty)
        obj.Name = t["name"]
        tb.Tools.Add(obj)

    # I/O 终端
    auto_inputs = []
    if src_mode in ("input", "both"):
        auto_inputs.append({"name": "InputImage", "type": "ICogImage"})
    if src_mode == "both":
        auto_inputs.append({"name": "UseFileImage", "type": "Boolean"})
        auto_inputs.append({"name": "ImageFilePath", "type": "String"})
    if src_mode == "folder":
        auto_inputs.append({"name": "ImageFolderPath", "type": "String"})
    seen = set()
    for i in auto_inputs + spec.get("inputs", []):
        if i["name"] in seen:
            continue
        seen.add(i["name"])
        try:
            tb.Inputs.Add(make_terminal(i, "Input"))
        except Exception as e:
            print("Inputs.Add warn:", i["name"], e)
    if src_mode == "both":
        try:
            tb.Inputs["UseFileImage"].Value = System.Boolean(False)
        except Exception:
            pass
        try:
            tb.Inputs["ImageFilePath"].Value = spec.get("img_path", "")
        except Exception:
            pass
    if src_mode == "folder":
        try:
            tb.Inputs["ImageFolderPath"].Value = spec.get("img_path", spec.get("folder_path", ""))
        except Exception:
            pass
        try:
            tb.Outputs.Add(CogToolBlockTerminal("CurrentImage", System.String))
        except Exception:
            pass
    for o in spec.get("outputs", []):
        tb.Outputs.Add(make_terminal(o, "Output"))

    # 拼 C# 源码（源码文件已在上方读取，此处复用）
    folder_filter = spec.get("folder_filter", "*.png")
    class_fields = ""
    using_imgproc = ""  # 仅 input/both 需要 CogImageConvertTool
    if src_mode == "folder":
        class_fields = "  private int m_CurrentIndex = 0;\n  private string[] m_Files = null;"
    if src_mode in ("input", "both"):
        using_imgproc = "using Cognex.VisionPro.ImageProcessing;"
    acquire = IMAGE_ACQUIRE[src_mode].replace(
        "__IMG_PATH__", spec.get("img_path", "")).replace(
        "__FOLDER_FILTER__", '"' + folder_filter + '"')
    src = (SCAFFOLD
           .replace("__EXTRA_USINGS__", extra)
           .replace("__USING_IMAGEPROC__", using_imgproc)
           .replace("__CLASS_FIELDS__", class_fields)
           .replace("__IMAGE_ACQUIRE__", acquire)
           .replace("__OVERLAY_TERM__", overlay_term)
           .replace("__GROUP_RUN_BODY__", gr_body)
           .replace("__MODIFY_RECORD_BODY__", mr_body))

    set_script(tb, src, CogToolBlockAdvancedScriptBase, check=check)

    out = spec["out_vpp"]
    CogSerializer.SaveObjectToFile(tb, out)
    print("SAVED:", out, "| exists:", os.path.isfile(out))
    return out


if __name__ == "__main__":
    import clr  # 先注册 pythonnet，System 命名空间才可被 import
    import System
    from System import Threading
    check = "--check" in sys.argv
    spec_path = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "spec_example.json"
    if not os.path.isfile(spec_path):
        spec_path = sys.argv[2] if len(sys.argv) > 2 else "spec_example.json"
    spec_path = os.path.abspath(spec_path)
    spec = json.load(open(spec_path, encoding="utf-8"))
    def _run():
        generate(spec, base_dir=os.path.dirname(spec_path), check=check)
    th = Threading.Thread(Threading.ThreadStart(_run))
    th.SetApartmentState(Threading.ApartmentState.STA)
    th.Start(); th.Join()
