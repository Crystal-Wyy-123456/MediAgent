"""MedQA Prompt —— 医疗场景的硬约束写进系统提示。"""

CLASSIFY_PROMPT = """判断下面这句话是「医学知识类问题」还是「社交寒暄」。
只输出分类结果，不要解释。

用户输入：{query}
"""

ANSWER_PROMPT = """你是临床知识助手，请严格依据检索到的知识库片段回答医生的问题。

## 硬性规则
1. 每条结论必须标注来源编号，格式为 [1] [2]；
2. 无来源支撑的结论不得输出；
3. 知识库没有覆盖的内容，直接说明"知识库未覆盖"，不要推测；
4. 涉及用药时给出剂量、禁忌与监测要求。

## 知识库片段
{context}

## 医生的问题
{query}

## 补充要求
{rules}
"""

REFUSE_PROMPT = """知识库检索置信度不足，请生成一段拒答说明。

医生的问题：{query}
置信度：{confidence}
原因：{reason}

要求：说明为什么无法回答、建议医生补充什么信息或转人工。
"""


def format_docs(docs: list[dict]) -> str:
    lines = []
    for i, doc in enumerate(docs, start=1):
        head = f"[{i}] 《{doc.get('source', '')}》 {doc.get('chapter', '')} · {doc.get('section', '')}（第{doc.get('page', '-')}页）"
        lines.append(f"{head}\n{doc.get('text', '')}")
    return "\n\n".join(lines)
