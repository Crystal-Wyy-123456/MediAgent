"""PreConsult Prompt。"""

EVAL_PROMPT = """请评估患者对一个预问诊问题的回答质量，并抽取其中的槽位信息。

当前阶段：{stage}
提问：{question}
患者回答：{answer}

质量四档：
  EXCELLENT —— 信息丰富且具体
  ADEQUATE  —— 基本回答了问题
  WEAK      —— 信息过少或答非所问
  NO_ANSWER —— 明确表示不知道/没注意
"""

RED_FLAG_PROMPT = """判断下面这句话是否提示需要医生立即介入的危急症状。

患者表述：{text}

关注：胸痛伴大汗、意识障碍、呼吸困难、呕血咯血、高热伴皮疹等。
"""

QUESTION_PROMPT = """你是门诊预问诊助手，当前处于「{stage}」阶段。
请用通俗、简短、一次只问一到两个要点的方式向患者提问。

当前阶段已采集的槽位：{slots}
仍缺少的信息：{missing}
"""

FOLLOWUP_PROMPT = """患者上一个回答质量较高，请针对「{stage}」阶段提一个更深入的追问，
用于补充细节，不要重复原问题。

患者回答：{answer}
"""

REPHRASE_PROMPT = """患者表示不知道或没有回答，请换一种更通俗、更具体的问法重新提问。

原问题：{question}
阶段：{stage}
"""

SUMMARY_PROMPT = """请把预问诊采集到的信息整理成病历草稿。

采集槽位：{slots}
"""
