    // ===== GroupRun 算法插槽（任务驱动，以下为"抓圆+输出圆心"示例）=====
    // 此时 tb / img 已就绪（img 来自内部 CogImageFileTool1 或 Inputs["InputImage"]）。
    // 任何工具都通过 tb.Tools["工具名"] 取出，类型按 spec.tools 的全名强转。
    var circle = (CogFindCircleTool)tb.Tools["CogFindCircleTool1"];
    // 若图像非灰度，按需强转（彩色图直接传可能类型不符）：
    circle.InputImage = (CogImage8Grey)img;
    circle.Run();
    if (circle.Results != null && circle.Results.Count > 0) {
      CogCircle c = circle.Results.GetCircle();
      // 写进输出终端（类型由 spec.outputs 定义，这里是 String）
      tb.Outputs["ResultString"].Value =
          "X:" + c.CenterX.ToString("F2") + " Y:" + c.CenterY.ToString("F2");
    } else {
      tb.Outputs["ResultString"].Value = "NG";
    }
