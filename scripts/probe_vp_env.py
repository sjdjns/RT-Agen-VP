# -*- coding: utf-8 -*-
"""VP 环境自适应探测：自动发现安装目录 / 版本 / 可用程序集与工具类型。
不写死任何路径或工具名——全部靠注册表 + 文件系统扫描 + 反射枚举。
作为"通用 VP 工程构建"方案的环境探针，证明泛用性。
"""
import os, sys, glob

def delete_acc_env():
    for k in list(os.environ):
        if k.startswith("ACC_"):
            del os.environ[k]

def find_vp_roots():
    """返回可能的 VP 安装根目录列表（注册表优先，常见路径兜底）。"""
    roots = []
    # 1) 注册表（只读，不改任何东西）
    try:
        import winreg
        for hive, sub in [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Cognex\VisionPro"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Cognex\VisionPro"),
        ]:
            try:
                key = winreg.OpenKey(hive, sub)
                try:
                    roots.append(winreg.QueryValueEx(key, "InstallDir")[0])
                except Exception:
                    pass
                try:
                    print("[REG] Version =", winreg.QueryValueEx(key, "Version")[0])
                except Exception:
                    pass
                winreg.CloseKey(key)
            except Exception:
                pass
    except Exception as e:
        print("[REG] 不可用:", e)
    # 2) 常见安装路径（盘符根用 "\\"，不写死版本号，靠 isdir 探测）
    for drive in ("C:", "D:", "E:"):
        for cand in (
            os.path.join(drive + "\\", "VisionPro", "VisionPro"),
            os.path.join(drive + "\\", "Program Files", "Cognex", "VisionPro"),
            os.path.join(drive + "\\", "Program Files (x86)", "Cognex", "VisionPro"),
        ):
            if os.path.isdir(cand):
                roots.append(cand)
    # 去重保序
    seen, out = set(), []
    for r in roots:
        if r and r not in seen:
            seen.add(r); out.append(r)
    return out

def find_core_dll(root):
    """在 root 下模糊搜索 Cognex.VisionPro.dll（不限定 bin/ReferencedAssemblies 结构）。"""
    hits = glob.glob(os.path.join(root, "**", "Cognex.VisionPro.dll"), recursive=True)
    return hits[0] if hits else None

def load_all_cognex(ref_dir):
    """按名批量 AddReference 所有 Cognex 程序集（动态，不列清单）。
    调用前需把 ref/bin 加入 sys.path，否则按名解析会报"找不到文件"。
    Controls(WPF) 等少量程序集在非 GUI 上下文可能加载失败，跳过即可。"""
    import clr
    loaded = 0
    for dll in glob.glob(os.path.join(ref_dir, "Cognex.*.dll")):
        name = os.path.splitext(os.path.basename(dll))[0]
        try:
            clr.AddReference(name)
            loaded += 1
        except Exception:
            pass
    return loaded

def enumerate_tools_and_version(core_dll):
    """加载后反射：读出程序集版本 + 所有 *Tool / *ToolGroup 类型（工具动态发现）。"""
    import clr
    clr.AddReference("Cognex.VisionPro")
    clr.AddReference("Cognex.VisionPro.Core")
    import System
    from Cognex.VisionPro import CogSerializer  # 触发加载
    ver = System.Reflection.AssemblyName.GetAssemblyName(core_dll).Version
    tools = set()
    for asm in System.AppDomain.CurrentDomain.GetAssemblies():
        fn = asm.FullName or ""
        if "Cognex" not in fn:
            continue
        try:
            for t in asm.GetTypes():
                n = t.Name
                if n.endswith("Tool") or "CogToolGroup" in n or n == "CogToolBase":
                    tools.add(n)
        except Exception:
            pass
    return ver, sorted(tools)

def try_root(root):
    """尝试在一个安装根加载 VP：成功返回 (core, ver, tools)，失败返回 None（自动回退）。
    必须同时把 ref 和 bin 加进 sys.path 才能按名解析；x86 程序集在 64 位 Python 下会抛
    BadImageFormatException，被捕获后自动跳到下一个根。"""
    core = find_core_dll(root)
    if not core:
        return None
    ref_dir = os.path.join(root, "ReferencedAssemblies")
    bin_dir = os.path.join(root, "bin")
    if not os.path.isdir(ref_dir):
        ref_dir = os.path.dirname(core)
    try:
        for p in (ref_dir, bin_dir):
            if os.path.isdir(p):
                sys.path.insert(0, p)
        import clr
        clr.AddReference("System.Drawing")
        clr.AddReference("Cognex.VisionPro")
        clr.AddReference("Cognex.VisionPro.Core")
        clr.AddReference("Cognex.VisionPro.ToolBlock")
        from Cognex.VisionPro.ToolBlock import CogToolBlock
        _ = CogToolBlock()  # 实例化验证（x86 在 64 位 Python 下抛 BadImageFormat）
        n = load_all_cognex(ref_dir)
        print("  已 AddReference 的 Cognex 程序集数:", n)
        ver, tools = enumerate_tools_and_version(core)
        return (core, ver, tools)
    except Exception as e:
        print("  [跳过] 根", root, "加载失败:", repr(e)[:80])
        return None

if __name__ == "__main__":
    delete_acc_env()
    print("=== VP 安装根探测 ===")
    roots = find_vp_roots()
    print("候选根:", roots)
    result = None
    for r in roots:
        print("尝试根:", r)
        result = try_root(r)
        if result:
            break
    if not result:
        print("所有候选根均无法加载 Cognex 程序集"); sys.exit(1)
    core, ver, tools = result
    print("成功根:", core)
    print("=== 版本 + 工具枚举 ===")
    print("VP 程序集版本 (AssemblyVersion):", ver)
    print("探测到的工具/组类型数:", len(tools))
    for t in tools:
        print("  -", t)
