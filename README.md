# MediAgent · 面向医疗机构的智能诊疗协作多 Agent 平台（Demo）

> 医学知识问答（MedQA）· 病历内涵质控（MedReview）· 门诊预问诊（PreConsult）
> 统一收口到 **Orchestrator 编排层**，三个子 Agent 用**三种不同复杂度的 LangGraph 范式**。

这是一个**可以完整跑起来、可以点、可以演示**的作品集 Demo：设计方案里的每一条架构决策都落成了真实代码 —— 引用溯源、置信度拒答、三轨并行质控、状态机 + `interrupt()` 医生接管、MCP 工具层、全链路 Trace、离线评测。

---

## 1. 30 秒启动

### 前置条件

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | **3.11+**（必需） | LangGraph 的异步 `interrupt()` 在 3.11 以下无法在异步节点中读取运行上下文 |
| Node.js | 18+（推荐 20+） | 仅前端需要；不装也能只用后端 API |

### Windows 一键启动

```powershell
cd MediAgent
.\start.ps1
```

脚本会自动：查找 Python 3.11+ → 创建 `.venv` → 安装依赖 → 安装前端依赖 → 同时拉起后端(8000)与前端(5173) → 打开浏览器。

### macOS / Linux

```bash
cd MediAgent
chmod +x start.sh && ./start.sh
```

### 手动启动

```bash
# 后端
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000

# 前端（另开一个终端）
cd frontend
npm install
npm run dev            # http://127.0.0.1:5173
```

打开 **http://127.0.0.1:5173**，在登录页选一个演示身份（医生 / 质控科医师 / 患者 / 管理员）即可进入对应视图。
后端接口文档：**http://127.0.0.1:8000/docs**

> 默认使用**内置领域仿真模型**（`LLM_PROVIDER=sim`），零 API Key、零外部服务即可完整演示。
> 想接真实大模型：复制 `.env.example` 为 `.env`，把 `LLM_PROVIDER` 改成 `deepseek` 并填 `LLM_API_KEY` —— **业务代码零改动**。

---

## 2. 六个页面分别演示什么

| 页面 | 演示的核心机制 |
|------|----------------|
| **医生工作站** `/doctor` | MedQA 完整链路：Query 二分类 → 混合检索 + 精排 → 置信度三向门控 → 结构化引用卡片。右侧实时展示节点级链路、MCP 工具调用、检索证据与 Span 瀑布 |
| **病历质控后台** `/qc` | MedReview 三轨并行：规则引擎（零 Token）+ 六维度 LLM 并发评审 + 跨文档比对；问题清单每条带病历原文证据，可逐条采纳 / 驳回 |
| **门诊预问诊** `/preconsult` | PreConsult 五阶段状态机：阶段进度、槽位填充、回答质量四档与追问分支；一键触发红旗症状 → `interrupt()` 挂起 |
| **医生接管工作台** `/handover` | 红旗告警队列 → 患者摘要 + 最近 6 轮对话 → `take_over / refer_emergency / continue` → `Command(resume=)` 从断点恢复 |
| **深度编排** `/pipeline` | `preconsult_review` 全链路：门控（红旗 / 完整度）是 Pipeline 的断路器，中止时不触发下游；显式字段映射表 |
| **管理后台** `/admin` | 指标大盘、Trace 检索与瀑布图、MCP 工具（含 Tool Schema 与在线调用）、三个 Agent 的图拓扑、离线评测报告、系统配置与工程取舍 |

---

## 3. 代码结构与设计的对应关系

```
MediAgent/
├── backend/
│   ├── main.py                      # FastAPI 入口：认证 / 租户解析 / SSE / 静态资源
│   ├── config.py                    # 全局配置（环境变量或 .env 覆盖）
│   ├── api/                         # 接入层
│   │   ├── deps.py                  #   JWT → RequestContext(tenant_id/user_id/role)
│   │   ├── chat.py                  #   统一对话入口（SSE 事件流）
│   │   ├── medqa.py / medreview.py / preconsult.py / pipeline.py
│   │   └── admin.py                 #   指标 / Trace / MCP / 拓扑 / 系统信息
│   ├── orchestrator/                # ★ 编排层：统一契约 + 二级路由 + Pipeline + 三层兜底
│   │   ├── schema.py                #   AgentRequest / AgentResponse / RouteResult
│   │   ├── router.py                #   L1 规则前置拦截（零 Token）+ L2 LLM 意图分类
│   │   ├── pipeline.py              #   Pipeline 定义 + 门控 + CONTEXT_MAPPING 字段映射
│   │   ├── registry.py              #   图懒加载（import 写在函数内部）
│   │   └── core.py                  #   Orchestrator 主体（路由 / 分发 / 传数据 / 兜底）
│   ├── agents/
│   │   ├── medqa/                   # ★☆☆ 条件分支 + 单链路 RAG
│   │   ├── medreview/               # ★★☆ 三轨并行 + 节点内 asyncio.gather
│   │   └── preconsult/              # ★★★ 有限状态机 + interrupt() 人机协同
│   ├── tools/                       # MCP 工具层
│   │   ├── framework.py             #   与 FastMCP 同构的极简工具框架（含 JSON Schema 生成）
│   │   ├── registry.py              #   工具注册中心：统一超时 + 重试；transport 可插拔
│   │   └── servers/                 #   medical-kb / web-search 两个 MCP Server
│   ├── rag/                         # 知识库 · 分块 · 稠密编码 · BM25 · 融合 · 精排
│   ├── memory/                      # Checkpointer 工厂 + 上下文压缩策略
│   ├── infra/                       # LLM Factory · 数据库 · 重试 · 向量库接入 · 仿真模型
│   ├── observability/               # 自研轻量 Trace（request_id 透传 + span 埋点 + 结构化日志）
│   └── evaluation/                  # 三层离线评测：检索 / Agent / 医疗安全
├── frontend/                        # Vue 3 + Vite + ECharts（自建设计系统，无 UI 库依赖）
├── tests/                           # 27 个用例：单元（节点 / 路由 / 规则）+ 集成（三个 Agent）
└── deploy/                          # Dockerfile · docker-compose · nginx.conf · PostgreSQL schema.sql
```

---

## 4. 三条最有面试价值的实现细节

### 4.1 「阶段判定不给 LLM」是怎么落地的

`backend/agents/preconsult/stages.py` 里的 `evaluate_stage()` 是纯函数：**轮数达标 且 槽位齐备**才推进，两个条件必须同时满足。

- 零 Token：不消耗任何模型调用
- 100% 可测：`tests/unit/test_stage_machine.py` 覆盖了「轮数够但槽位不全」「槽位全但轮数不够」两个反例
- 分工：LLM 只负责**内容生成**（这个阶段该怎么说）与**质量评估**（答得好不好）；「评估完之后做什么」（追问 / 换问法 / 下一题）由代码决定

### 4.2 「三轨并行」为什么用 `asyncio.gather` 而不是 LangGraph Send API

`backend/agents/medreview/nodes.py::run_three_tracks_node`：三轨数量**确定**且都在同一节点内完成，`gather` 代码更短、调试更直观（一个断点就能看到三轨全部返回）。LLM 轨内部再嵌一层 `asyncio.gather` 并发六个维度 —— 维度彼此正交，串行跑就是 6 倍耗时。

同时在 `state.py` 里保留了注释：**若改成图级并发，字段必须写成 `Annotated[list, operator.add]` 由 Reducer 合并**，否则多个节点写同一字段会互相覆盖。

### 4.3 「可溯源」与「该拒答就拒答」是结构保证，不是约定

- 引用：`AnswerWithCitations` 用 Pydantic 强约束输出，`citations` 独立成字段（而不是塞进答案字符串），前端直接渲染成引用卡片
- 拒答：置信度 `= 0.45×精排最高分 + 0.25×Top3均分 + 0.15×词项覆盖 + 0.15×文档数因子`，三向门控 `≥0.62 生成 / 0.42~0.62 联网兜底 / <0.42 拒答`。**宁可拒答，不可幻觉。**

---

## 5. 接口一览

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/chat/stream` | POST | 统一对话入口（SSE：`route / node / tool_call / citation / delta / interrupt / done`） |
| `/api/v1/chat` | POST | 同上，非流式（便于脚本与自动化测试） |
| `/api/v1/medqa/ask` | POST | 知识问答（医生工作站内嵌调用） |
| `/api/v1/medreview/submit` · `/upload` | POST | 提交病历质控（文本 / PDF / DOCX） |
| `/api/v1/medreview/{id}` | GET | 质控结果与问题清单 |
| `/api/v1/medreview/{id}/issues/{issue_id}` | PATCH | 医师采纳 / 驳回某条问题 |
| `/api/v1/preconsult/start` · `/{sid}/answer` | POST | 发起预问诊与逐轮回答 |
| `/api/v1/preconsult/{sid}/handover` | POST | 医生接管（对应 `Command(resume=)`） |
| `/api/v1/preconsult/alerts/pending` | GET | 待处理红旗告警 |
| `/api/v1/pipeline/preconsult-review` | POST | 预问诊 → 病历质控 全链路 |
| `/api/v1/admin/overview` · `/traces` · `/mcp/tools` · `/agents/topology` · `/system` | GET | 管理后台数据 |
| `/api/v1/evaluation/run` | POST | 一键跑离线评测（检索 / 路由 / 安全） |

---

## 6. 建议的演示动线（面试 8 分钟版）

1. **登录页**：选「临床医生」→ 说明多租户隔离（`tenant_id` 从 Token 解析后全链路透传）
2. **医生工作站**：问「二甲双胍的禁忌症有哪些？」→ 指出引用卡片带章节与页码；再问「今天股市怎么样」→ 指出拒答分支；右侧看节点链路与 Span 瀑布
3. **病历质控后台**：载入「心内科 · 不稳定型心绞痛入院记录」→ 说明三轨并行，点开一条严重问题看证据原文；切到「三轨明细」看规则表与六维度评分
4. **门诊预问诊**：点「自动演示」走完五阶段 → 展示阶段进度与槽位；再点「触发红旗」→ `interrupt()` 挂起告警
5. **医生接管工作台**：看到告警队列 → 点「我来接管」→ 说明从断点恢复、不重跑之前节点
6. **深度编排**：用刚才的 session 跑全链路 → 展示门控与字段映射表
7. **管理后台**：Trace 里任点一个 `request_id` 看全链路瀑布；跑一次离线评测看四项指标

---

## 7. 关于「仿真模型」：这是工程取舍，不是套壳

`backend/infra/sim/` 是**领域仿真模型**，它复刻的是真实模型在**每个节点上的输出契约与判据**：

| 节点 | 仿真实现 | 接真实模型后 |
|------|----------|--------------|
| Query 分类 | 关键词 + 短句规则 | LLM 温度 0 + 结构化输出 |
| 答案生成 | 从检索片段中抽取最相关句子并强制编号引用 | 同一 `AnswerWithCitations` Schema |
| 六维度评审 | 每个维度的确定性 + 语义判据（含 eGFR、剂量等定量校验） | 同一 `DimensionResult` Schema |
| 回答质量 | 长度 + 槽位覆盖度 | LLM 四档标签 |

这样做的价值：**没有 API Key、没有 GPU 也能完整演示架构与交互**，而切换到真实模型只改 `.env`。
代价也很清楚：仿真模型的医学判断力**远不如真实模型**，它只负责证明链路是通的。生产环境必须使用真实模型 + 院内审核过的知识库。

---

## 8. 已知边界（先写在前面）

| 边界 | 现状 | 升级路径 |
|------|------|----------|
| 知识库规模 | 17 份文献 / 42 个知识块（演示语料） | 院内药学部 / 质控科提供，做版本化管理与增量更新 |
| 向量检索 | 内置轻量索引（BM25 + 哈希稠密向量） | 配 `MILVUS_URI` 即切 Milvus 2.4；`EMBEDDING_PROVIDER=bge` 切 BGE-M3 |
| 精排 | 本地交叉编码近似实现 | `RERANK_PROVIDER=bge` 切 BGE-Reranker |
| 会话状态 | `MemorySaver`（进程内，多副本不共享） | `get_memory_saver()` 工厂已留好接缝 → 换 `PostgresSaver` |
| 数据库 | SQLite（开箱即用） | `DATABASE_URL` 换 PostgreSQL，DDL 见 `deploy/schema.sql` |
| MCP transport | 默认进程内（`inproc`） | `pip install mcp` 后 `MCP_TRANSPORT=stdio` 走标准 MCP 协议 |
| 联网搜索 | 返回模拟结果并显式标注 `simulated: true` | 替换 `_provider_call` 接真实搜索 API |

> ⚠️ **免责声明**：本仓库中的知识库条目与病历样例均为**演示数据**，仅用于展示检索、质控与协作链路，**不得用于真实临床决策**。

---

## 9. 测试

```bash
python -m pytest -q                  # 27 个用例：单元 + 集成
cd frontend && npm run check:sfc     # 前端单文件组件静态编译校验
```

覆盖的关键行为：

- 阶段推进的两个条件必须同时满足（含两个反例）
- L1 规则拦截：寒暄 / 转人工 / 会话状态继承
- 规则引擎轨对样例病历的确定性结论、结构化字段解析
- 检索 Top-3 命中与置信度三向门控
- 三个 Agent 的真实图：MedQA 引用与拒答、MedReview 三轨与问题证据、PreConsult 全流程与**红旗中断 → 接管恢复**
