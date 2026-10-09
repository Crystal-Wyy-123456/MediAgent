"""Checkpointer 工厂 —— 按 Agent 类型提供独立的 MemorySaver。

为什么要按 Agent 类型分开：三个 Agent 的 State 结构完全不同
（QAState / ReviewState / PreConsultState），共用一个 saver 会让
thread_id 命名空间混乱，排查问题时也分不清是谁的状态。

为什么抽成工厂函数：MemorySaver 是进程内实现，多副本部署时会话状态不共享，
上量时要换成 PostgresSaver —— 提前留好这个接缝，换实现时业务代码零改动。
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver

_SAVERS: dict[str, MemorySaver] = {}


def get_memory_saver(agent: str) -> MemorySaver:
    if agent not in _SAVERS:
        _SAVERS[agent] = MemorySaver()
    return _SAVERS[agent]


def memory_info() -> dict:
    return {
        "backend": "服务端自动保存",
        "agents": sorted(_SAVERS.keys()),
        "thread_id_format": "tenant_{tenant_id}_patient_{patient_id}_session_{session_id}",
        "upgrade_path": "支持切换为集群化存储，业务代码无需改动",
    }
