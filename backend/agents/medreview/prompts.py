"""MedReview Prompt —— 六维度评审 + 结构化提取。"""

EXTRACT_PROMPT = """请把下面这份病历抽取成结构化字段，用于后续质控。
只做抽取，不要评价，不要补充病历中没有的内容。

## 病历原文
{document}
"""

DIMENSION_PROMPTS = {
    "completeness": "请评审这份病历的**完整性**：必填要素是否齐全、现病史六要素是否完整、关键信息是否缺失。只提出有证据支撑的问题，每条问题必须引用病历原文片段。\n\n病历：\n{document}\n",
    "consistency": "请评审这份病历的**一致性**：主诉与现病史、诊断与病史、既往史与过敏史之间是否自洽。重点找出前后矛盾的表述，并引用原文作为证据。\n\n病历：\n{document}\n",
    "diagnosis_basis": "请评审这份病历的**诊断依据**：初步诊断是否有症状、体征、辅助检查支撑，是否缺少关键检查。\n\n病历：\n{document}\n",
    "medication_rationality": "请评审这份病历的**用药合理性**：剂量、配伍、禁忌、用药指征与监护要求。涉及禁忌证必须明确指出依据。\n\n病历：\n{document}\n",
    "logic": "请评审这份病历的**逻辑性**：病程演变是否合理、诊疗计划与病情是否对应、时间顺序是否正确。\n\n病历：\n{document}\n",
    "standardization": "请评审这份病历的**规范性**：术语是否规范、主诉写法是否符合「症状+时长」、是否使用非规范缩写。\n\n病历：\n{document}\n",
}

DIMENSION_LABELS = {
    "completeness": "完整性",
    "consistency": "一致性",
    "diagnosis_basis": "诊断依据",
    "medication_rationality": "用药合理性",
    "logic": "逻辑性",
    "standardization": "规范性",
}
