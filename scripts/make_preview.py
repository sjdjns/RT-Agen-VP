# -*- coding: utf-8 -*-
"""Layer B — 参数化视觉预览框架（不绑定任务）。

用法：
  在 Python 里用 cv2 渲染与 .vpp ModifyLastRunRecord 完全一致的叠加预览图。
  也可以直接运行：python make_preview.py <overlay_spec.json>

overlay spec 结构（所有字段可配）：
  {
    "image":         "素材图路径（cv2.imread 支持）",
    "output":        "输出预览图路径",
    "elements": [
      // 矩形框
      {"type":"rect", "x":100,"y":200,"w":50,"h":50,"color":[0,255,0],"thickness":2,"label":"OK"},
      // 圆
      {"type":"circle", "cx":500,"cy":400,"r":80,"color":[255,0,0],"thickness":2},
      // 线段
      {"type":"line", "x1":0,"y1":0,"x2":1000,"y2":0,"color":[0,0,255],"thickness":3},
      // 文字
      {"type":"text", "x":40,"y":40,"text":"OK\\nR=300.0","color":[0,255,0],"size":1.5,"thickness":2}
    ]
  }

不绑定任何具体任务——测量/缺陷/ID 等场景只需改 spec 即可生成对应预览图。
"""
import cv2, numpy as np, json, sys, os


def draw_elements(img, elements):
    """在 img (BGR ndarray) 上绘制所有元素（原地修改）。"""
    for el in elements:
        t = el.get("type", "")
        color = tuple(int(c) for c in el.get("color", [0, 255, 0]))
        thick = el.get("thickness", 2)
        if t == "rect":
            cv2.rectangle(img, (int(el["x"]), int(el["y"])),
                          (int(el["x"] + el["w"]), int(el["y"] + el["h"])),
                          color, thick)
        elif t == "circle":
            cv2.circle(img, (int(el["cx"]), int(el["cy"])),
                       int(el["r"]), color, thick)
        elif t == "line":
            cv2.line(img, (int(el["x1"]), int(el["y1"])),
                     (int(el["x2"]), int(el["y2"])), color, thick)
        elif t == "text":
            lines = str(el.get("text", "")).split("\\n")
            x, y = int(el["x"]), int(el["y"])
            size = el.get("size", 1.0)
            for i, line in enumerate(lines):
                cv2.putText(img, line, (x, y + i * 35), cv2.FONT_HERSHEY_SIMPLEX,
                            size, color, thick, cv2.LINE_AA)
        elif t == "polygon":
            pts = el.get("points", [])
            if len(pts) >= 3:
                pts_arr = np.array([(int(p[0]), int(p[1])) for p in pts], np.int32)
                cv2.polylines(img, [pts_arr], True, color, thick)


def make_preview(spec):
    img_path = spec["image"]
    out_path = spec["output"]
    if not os.path.isfile(img_path):
        raise FileNotFoundError("素材图不存在: " + img_path)
    img = cv2.imread(img_path)
    if img is None:
        # 中文路径兜底：Opencv imread 不支持 unicode 路径
        import numpy as np
        buf = np.fromfile(img_path, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法读取图像: " + img_path)
    draw_elements(img, spec.get("elements", []))
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    cv2.imwrite(out_path, img)
    print("预览图已保存:", out_path, "| 大小:", img.shape)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python make_preview.py <overlay_spec.json>")
        sys.exit(1)
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    make_preview(spec)
