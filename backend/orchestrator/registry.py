"""Agent 图懒加载注册表。

为什么必须懒加载：MedQA 图要建检索索引、MedReview 要加载文档解析器、
PreConsult 要建 Checkpointer。启动时全量初始化会让启动等几十秒，而且内存常驻。
关键细节：import 必须写在函数内部，否则模块被 import 时依赖就被加载了，懒加载白做。
"""

from __future__ import annotations

import time
from typing import Any

from ..observability.logger import log_event
from .schema import AgentType


class GraphRegistry:
    def __init__(self) -> None:
        self._graphs: dict[AgentType, Any] = {}
        self._built_at: dict[AgentType, float] = {}

    def get(self, agent_type: AgentType):
        if agent_type not in self._graphs:
            t0 = time.perf_counter()
            if agent_type is AgentType.MEDQA:
                from ..agents.medqa.graph import build_medqa_graph  # ★ 函数内 import

                self._graphs[agent_type] = build_medqa_graph()
            elif agent_type is AgentType.MEDREVIEW:
                from ..agents.medreview.graph import build_medreview_graph

                self._graphs[agent_type] = build_medreview_graph()
            elif agent_type is AgentType.PRECONSULT:
                from ..agents.preconsult.graph import build_preconsult_graph

                self._graphs[agent_type] = build_preconsult_graph()
            else:  # pragma: no cover
                raise ValueError(f"未知 Agent 类型：{agent_type}")
            self._built_at[agent_type] = time.time()
            log_event(
                "agent_graph_initialized",
                agent=agent_type.value,
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )
        return self._graphs[agent_type]

    def status(self) -> list[dict]:
        from .schema import AGENT_META

        out = []
        for agent in AgentType:
            meta = AGENT_META[agent.value]
            out.append(
                {
                    "agent_type": agent.value,
                    "name": meta["name"],
                    "label": meta["label"],
                    "difficulty": meta["difficulty"],
                    "paradigm": meta["paradigm"],
                    "loaded": agent in self._graphs,
                    "built_at": self._built_at.get(agent),
                }
            )
        return out


graph_registry = GraphRegistry()
