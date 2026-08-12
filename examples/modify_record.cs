    // ===== ModifyLastRunRecord 图形叠加插槽（任务驱动，以下为"画圆+标注"示例）=====
    // 此时 tb / term(="CogImageFileTool1.OutputImage") / imgRec 已就绪。
    // 所有图形必须 AddGraphicToRunRecord 到 term，否则看不到。
    var circle = (CogFindCircleTool)tb.Tools["CogFindCircleTool1"];
    if (circle.Results != null && circle.Results.Count > 0) {
      CogCircle c = circle.Results.GetCircle();
      // 黄色圆框表示检测到的圆
      CogCircle g = new CogCircle();
      g.CenterX = c.CenterX; g.CenterY = c.CenterY; g.Radius = c.Radius;
      g.Color = CogColorConstants.Yellow;
      tb.AddGraphicToRunRecord(g, lastRecord, term, "DETECTED_CIRCLE");
      // 文字标签（字体别太大，多行会重叠；可用 \n）
      CogGraphicLabel lbl = new CogGraphicLabel();
      lbl.Font = new System.Drawing.Font("Arial", 9);
      lbl.Text = "X:" + c.CenterX.ToString("F1") + " Y:" + c.CenterY.ToString("F1");
      lbl.X = c.CenterX + 12; lbl.Y = c.CenterY - 12;
      lbl.Color = CogColorConstants.Yellow;
      lbl.BackgroundColor = CogColorConstants.Black;
      tb.AddGraphicToRunRecord(lbl, lastRecord, term, "CIRCLE_LABEL");
    }
