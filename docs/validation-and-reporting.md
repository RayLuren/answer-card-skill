# 验证与报告

AI 接纳层只裁决：JSON 白名单、安全禁用字段、status、必填字段、固定枚举、正数分值和框高、页码范围、题型高度范围、unknown/95mm fallback，以及人工确认固定字段。

它明确不裁决显示题号重复、连续性、父子并存、数字排序、总分是否合理、printed 占比是否合计 100，也不重新计算 AI 给出的 derived 占比。

最终报告记录 AI status、attempt/revision、人工确认轮次、来源指纹和页数、实际总分、printed/derived 占比合计、unknown fallback 机器键、显示题号配图清单、PDF/预览页数和每轮页框对齐。

页框在 200 DPI 测量，默认容差为 1.1 mm。报告保留 pass 0、每个校正 pass、顶部/底部 spread、判定标准和最终超差量。任何缺失的配图或对齐细节必须显式警告。
