<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { state, toast } from '../store'
import ChartBox from '../components/ChartBox.vue'
import StatCard from '../components/StatCard.vue'
import TraceWaterfall from '../components/TraceWaterfall.vue'

const tab = ref('overview')
const overview = ref(null)
const traces = ref([])
const tools = ref([])
const topology = ref(null)
const evaluation = ref(null)
const system = ref(null)
const detail = ref(null)
const onlyFailed = ref(false)
const toolArgs = ref('{}')
const toolName = ref('search_guideline')
const toolResult = ref(null)
const runningEval = ref(false)

const AGENT_LABELS = { medqa: '医学知识问答', medreview: '病历内涵质控', preconsult: '门诊预问诊', orchestrator: '统一调度' }
const ROUTE_LABELS = { L0: '日常寒暄', L1: '规则直答', L2: '知识检索', 'L2-fallback': '外部检索', PIPELINE: '诊疗联动', '-': '未分类' }
const KIND_LABELS = {
  orchestration: '统一调度', agent: '业务处理', node: '环节处理', tool: '外部工具调用',
  retrieval: '知识检索', rerank: '结果排序', routing: '问题分流', llm: '模型处理',
  code: '规则处理', guard: '安全校验', concurrency: '并行处理',
}

const MODULE_DESC = {
  medqa: {
    title: '智能问答',
    desc: '面向临床医生的医学知识问答。回答只基于院内审核知识库，每条结论标注指南名称、章节与页码；依据不足时不给出结论，并提示转人工确认。',
    points: ['引用可追溯', '依据不足不作答', '覆盖指南与药品说明书'],
  },
  medreview: {
    title: '病历内涵质控',
    desc: '对住院病历做规则核查、六个维度的内涵评审与跨文档一致性比对，输出带病历原文证据的问题清单，医生可逐条采纳或驳回。',
    points: ['规则核查', '六维度内涵评审', '跨文档一致性', '问题可采纳 / 驳回'],
  },
  preconsult: {
    title: '门诊预问诊',
    desc: '患者在挂号前分阶段完成病史采集，结束后自动生成病历草稿送入质控；采集过程中命中风险症状会立即提醒医生接管。',
    points: ['分阶段采集病史', '风险症状实时提醒', '自动生成病历草稿'],
  },
}

const routeOption = computed(() => {
  const dist = overview.value?.runtime?.route_distribution || {}
  const colors = { L1: '#12805c', L2: '#1a6fd4', 'L2-fallback': '#c77700', L0: '#6941c6', PIPELINE: '#0d9b8a', '-': '#94a3b8' }
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: { fontSize: 11, color: '#64748b' } },
    series: [{
      type: 'pie', radius: ['48%', '72%'],
      label: { formatter: '{b}\n{c}', fontSize: 11 },
        data: Object.entries(dist).map(([k, v]) => ({ name: ROUTE_LABELS[k] || k, value: v, itemStyle: { color: colors[k] || '#64748b' } })),
    }],
  }
})

const agentOption = computed(() => {
  const dist = overview.value?.runtime?.agent_distribution || {}
  return {
    grid: { left: 70, right: 20, top: 16, bottom: 24 },
    xAxis: { type: 'value', axisLine: { show: false }, splitLine: { lineStyle: { color: '#eef2f7' } }, axisLabel: { fontSize: 10, color: '#94a3b8' } },
    yAxis: { type: 'category', data: Object.keys(dist).map((k) => AGENT_LABELS[k] || k), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { fontSize: 11, color: '#475569' } },
    series: [{ type: 'bar', data: Object.values(dist), barWidth: 14, itemStyle: { color: '#1a6fd4', borderRadius: [0, 4, 4, 0] }, label: { show: true, position: 'right', fontSize: 11, color: '#64748b' } }],
  }
})

const kindOption = computed(() => {
  const dist = overview.value?.runtime?.kind_duration_ms || {}
  const entries = Object.entries(dist).sort((a, b) => b[1] - a[1]).slice(0, 8)
  return {
    grid: { left: 90, right: 26, top: 12, bottom: 22 },
    xAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef2f7' } }, axisLabel: { fontSize: 10, color: '#94a3b8' } },
    yAxis: { type: 'category', data: entries.map((e) => KIND_LABELS[e[0]] || e[0]), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { fontSize: 11, color: '#475569' } },
    series: [{ type: 'bar', data: entries.map((e) => e[1]), barWidth: 13, itemStyle: { color: '#0d9b8a', borderRadius: [0, 4, 4, 0] }, label: { show: true, position: 'right', fontSize: 10, color: '#64748b', formatter: '{c} ms' } }],
  }
})

const latencyOption = computed(() => {
  const items = [...traces.value].reverse()
  return {
    grid: { left: 46, right: 18, top: 18, bottom: 26 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: items.map((_, i) => `#${i + 1}`), axisLine: { lineStyle: { color: '#e2e8f0' } }, axisLabel: { fontSize: 10, color: '#94a3b8' } },
    yAxis: { type: 'value', name: 'ms', nameTextStyle: { fontSize: 10, color: '#94a3b8' }, splitLine: { lineStyle: { color: '#eef2f7' } }, axisLabel: { fontSize: 10, color: '#94a3b8' } },
    series: [{
      type: 'line', smooth: true, data: items.map((t) => Math.round(t.elapsed_ms)),
      areaStyle: { color: 'rgba(26,111,212,0.12)' }, lineStyle: { color: '#1a6fd4', width: 2 },
      itemStyle: { color: '#1a6fd4' },
    }],
  }
})

onMounted(load)

async function load() {
  try {
    overview.value = await api('/api/v1/admin/overview', { token: state.token })
    traces.value = (await api(`/api/v1/admin/traces?limit=40${onlyFailed.value ? '&only_failed=true' : ''}`, { token: state.token })).items
    topology.value = await api('/api/v1/admin/agents/topology')
    system.value = await api('/api/v1/admin/system')
    const t = await api('/api/v1/admin/mcp/tools')
    tools.value = t.tools
    toolName.value = tools.value[0]?.name || ''
    evaluation.value = await api('/api/v1/evaluation/report')
  } catch (err) {
    toast(err.message, 'error')
  }
}

async function openTrace(id) {
  try {
    detail.value = await api(`/api/v1/admin/traces/${id}`, { token: state.token })
  } catch (err) {
    toast(err.message, 'error')
  }
}

async function callTool() {
  try {
    const args = JSON.parse(toolArgs.value || '{}')
    toolResult.value = await api('/api/v1/admin/mcp/call', { method: 'POST', body: { tool: toolName.value, args }, token: state.token })
  } catch (err) {
    toast(`调用失败：${err.message}`, 'error')
  }
}

async function runEval() {
  runningEval.value = true
  try {
    evaluation.value = await api('/api/v1/evaluation/run', { method: 'POST', token: state.token })
    toast('评测完成', 'success')
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    runningEval.value = false
  }
}
</script>

<template>
  <div class="stack">
    <div class="grid grid-4">
      <StatCard label="累计请求" :value="overview?.runtime?.requests ?? 0" :foot="`自动降级率 ${(((overview?.runtime?.fallback_rate ?? 0) * 100)).toFixed(1)}%`" />
      <StatCard label="平均耗时 / P95" :value="`${(overview?.runtime?.avg_elapsed_ms ?? 0).toFixed(0)} / ${(overview?.runtime?.p95_elapsed_ms ?? 0).toFixed(0)}ms`" tone="teal" foot="平台服务 P95 目标 < 300ms" />
      <StatCard label="模型调用量（估算）" :value="(overview?.runtime?.total_tokens ?? 0).toLocaleString()" tone="purple" foot="按模型统一计量" />
      <StatCard label="规则直答率" :value="`${(((overview?.runtime?.routing?.l1_hit_rate ?? 0) * 100)).toFixed(0)}%`" tone="warn" foot="无需模型调用即可回答" />
    </div>

    <div class="card">
      <div class="tabs">
        <div class="tab" :class="{ active: tab === 'overview' }" @click="tab = 'overview'">运行总览</div>
        <div class="tab" :class="{ active: tab === 'trace' }" @click="tab = 'trace'">调用记录</div>
        <div class="tab" :class="{ active: tab === 'mcp' }" @click="tab = 'mcp'">外部服务</div>
        <div class="tab" :class="{ active: tab === 'graph' }" @click="tab = 'graph'">业务拓扑</div>
        <div class="tab" :class="{ active: tab === 'eval' }" @click="tab = 'eval'">质量评测</div>
        <div class="tab" :class="{ active: tab === 'system' }" @click="tab = 'system'">系统信息</div>
      </div>

      <!-- 总览 -->
      <div v-if="tab === 'overview'" class="card-body stack">
        <div class="grid grid-3">
          <div><b class="tiny muted">回答方式分布</b><ChartBox :option="routeOption" height="220px" /></div>
          <div><b class="tiny muted">业务模块调用分布</b><ChartBox :option="agentOption" height="220px" /></div>
          <div><b class="tiny muted">各处理环节平均耗时</b><ChartBox :option="kindOption" height="220px" /></div>
        </div>
        <div><b class="tiny muted">最近请求耗时趋势（ms）</b><ChartBox :option="latencyOption" height="200px" /></div>
        <div class="grid grid-4">
          <StatCard label="质控份数" :value="overview?.quality?.reviews ?? 0" :foot="`平均 ${overview?.quality?.avg_score ?? '—'} 分`" tone="teal" />
          <StatCard label="质控问题总数" :value="overview?.quality?.issue_total ?? 0" :foot="`严重占比 ${(((overview?.quality?.error_ratio ?? 0) * 100)).toFixed(0)}%`" tone="danger" />
          <StatCard label="预问诊会话" :value="overview?.preconsult?.sessions ?? 0" :foot="`医生接管 ${overview?.preconsult?.handover_count ?? 0} 次`" />
          <StatCard label="知识库规模" :value="`${overview?.runtime?.knowledge_base?.documents ?? 0} 文献`" :foot="`${overview?.runtime?.knowledge_base?.indexed_chunks ?? 0} 条知识条目`" tone="purple" />
        </div>
      </div>

      <!-- Trace -->
      <div v-else-if="tab === 'trace'" class="card-body">
        <div class="row-between" style="margin-bottom: 10px">
          <div class="tiny muted">每次调用都会生成唯一编号，可按编号回溯完整处理过程，失败可定位到具体环节</div>
          <div class="row" style="gap: 8px">
            <label class="row tiny" style="gap: 5px; cursor: pointer"><input v-model="onlyFailed" type="checkbox" @change="load" /> 仅看失败</label>
            <button class="btn sm" @click="load">刷新</button>
          </div>
        </div>
        <table class="table">
          <thead>
            <tr><th>调用编号</th><th>业务模块</th><th>回答方式</th><th>状态</th><th>环节数</th><th>耗时</th><th>模型用量</th><th>用户问题</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="t in traces" :key="t.request_id">
              <td class="mono tiny">{{ t.request_id }}</td>
              <td><span class="badge blue">{{ AGENT_LABELS[t.agent_type] || t.agent_type }}</span></td>
              <td><span class="badge" :class="t.route_level === 'L1' ? 'green' : t.route_level === 'L2-fallback' ? 'amber' : 'purple'">{{ ROUTE_LABELS[t.route_level] || t.route_level }}</span></td>
              <td><span class="badge" :class="t.status === 'success' ? 'green' : 'red'">{{ t.status === 'success' ? '成功' : '失败' }}</span></td>
              <td class="mono">{{ t.span_count }}</td>
              <td class="mono">{{ t.elapsed_ms.toFixed(0) }}ms</td>
              <td class="mono">{{ t.total_tokens }}</td>
              <td class="tiny muted" style="max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ t.query }}</td>
              <td><button class="btn sm ghost" @click="openTrace(t.request_id)">详情</button></td>
            </tr>
            <tr v-if="!traces.length"><td colspan="9" class="empty tiny">暂无调用记录</td></tr>
          </tbody>
        </table>
      </div>

      <!-- 外部服务 -->
      <div v-else-if="tab === 'mcp'" class="card-body stack">
        <div class="tiny muted">
          平台通过标准接口对接外部知识与工具服务，业务侧只按名称调用。新增或替换外部服务时，主流程无需改动。
        </div>
        <div class="grid grid-2">
          <div class="stack">
            <div v-for="t in tools" :key="t.name" class="card" style="box-shadow: none">
              <div class="card-body" style="padding: 12px 14px">
                <div class="row-between">
                  <b>{{ t.description }}</b>
                  <span class="badge grey">{{ t.server }}</span>
                </div>
                <div class="tiny muted mono" style="margin-top: 5px">{{ t.name }}</div>
              </div>
            </div>
          </div>
          <div class="card" style="box-shadow: none; align-self: start">
            <div class="card-head"><div class="card-title">服务联通性检测</div></div>
            <div class="card-body stack">
              <div class="field">
                <label>选择服务</label>
                <select v-model="toolName" class="select">
                  <option v-for="t in tools" :key="t.name" :value="t.name">{{ t.description }}</option>
                </select>
              </div>
              <div class="field">
                <label>检测参数</label>
                <textarea v-model="toolArgs" class="textarea mono" rows="4" />
              </div>
              <button class="btn primary" @click="callTool">开始检测</button>
              <div v-if="toolResult" class="badge green">检测通过 · 服务响应正常</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 业务能力 -->
      <div v-else-if="tab === 'graph'" class="card-body stack">
        <div v-for="agent in topology?.agents || []" :key="agent.agent" class="card" style="box-shadow: none">
          <div class="card-head">
            <div class="card-title">
              <span class="badge blue">{{ AGENT_LABELS[agent.agent] || agent.agent }}</span>
              {{ MODULE_DESC[agent.agent]?.title || '' }}
            </div>
          </div>
          <div class="card-body">
            <div style="font-size: 12.5px; line-height: 1.8; color: var(--ink-2)">
              {{ MODULE_DESC[agent.agent]?.desc }}
            </div>
            <div class="divider"></div>
            <div class="row wrap" style="gap: 6px">
              <span v-for="f in MODULE_DESC[agent.agent]?.points || []" :key="f" class="badge grey">{{ f }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 评测 -->
      <div v-else-if="tab === 'eval'" class="card-body stack">
        <div class="row-between">
          <div class="tiny muted">评测样本：知识检索 {{ evaluation?.datasets?.retrieval }} 条 · 问题分流 {{ evaluation?.datasets?.routing }} 条 · 医疗安全 {{ evaluation?.datasets?.refuse }} 条 · 风险症状 {{ evaluation?.datasets?.red_flag }} 条</div>
          <button class="btn sm primary" :disabled="runningEval" @click="runEval">
            <span v-if="runningEval" class="spinner"></span>重新跑评测
          </button>
        </div>
        <div class="grid grid-4">
          <StatCard label="知识检索命中率" :value="evaluation?.retrieval?.value" :foot="`目标 ≥ ${evaluation?.retrieval?.target}`" :tone="evaluation?.retrieval?.pass ? 'teal' : 'danger'" />
          <StatCard label="问题分流准确率" :value="evaluation?.agent?.value" :foot="`目标 ≥ ${evaluation?.agent?.target}`" :tone="evaluation?.agent?.pass ? 'teal' : 'danger'" />
          <StatCard label="安全拒答准确率" :value="evaluation?.safety?.value" :foot="`目标 ≥ ${evaluation?.safety?.target?.refuse}`" :tone="evaluation?.safety?.pass ? 'teal' : 'danger'" />
          <StatCard label="风险症状识别准确率" :value="evaluation?.safety?.red_flag_value" :foot="`目标 ≥ ${evaluation?.safety?.target?.red_flag}`" :tone="evaluation?.safety?.pass ? 'teal' : 'danger'" />
        </div>
        <div class="grid grid-2">
          <div class="card" style="box-shadow: none">
            <div class="card-head"><div class="card-title">检索命中明细</div><span class="badge grey">平均排名 {{ evaluation?.retrieval?.mrr }}</span></div>
            <div class="card-body flush" style="max-height: 320px; overflow-y: auto">
              <table class="table">
                <thead><tr><th>咨询问题</th><th>命中位置</th></tr></thead>
                <tbody>
                  <tr v-for="c in evaluation?.retrieval?.cases || []" :key="c.query">
                    <td class="tiny">{{ c.query }}</td>
                    <td><span class="badge" :class="c.rank ? 'green' : 'red'">{{ c.rank ? `第 ${c.rank} 位` : '未命中' }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div class="card" style="box-shadow: none">
            <div class="card-head"><div class="card-title">医疗安全专项</div></div>
            <div class="card-body flush" style="max-height: 320px; overflow-y: auto">
              <table class="table">
                <thead><tr><th>用例</th><th>期望</th><th>结果</th></tr></thead>
                <tbody>
                  <tr v-for="c in evaluation?.safety?.cases || []" :key="c.query">
                    <td class="tiny">{{ c.query }}</td>
                    <td class="tiny">{{ c.expected_refuse ? '拒答' : '作答' }}</td>
                    <td><span class="badge" :class="c.ok ? 'green' : 'red'">{{ c.gate_refuse ? '拒答' : '作答' }}</span></td>
                  </tr>
                  <tr v-for="c in evaluation?.safety?.red_flag_cases || []" :key="c.text">
                    <td class="tiny">{{ c.text }}</td>
                    <td class="tiny">{{ c.expected ? '风险症状' : '无风险' }}</td>
                    <td><span class="badge" :class="c.ok ? 'green' : 'red'">{{ c.hit ? '风险症状' : '无风险' }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- 系统 -->
      <div v-else class="card-body stack">
        <div class="grid grid-2">
          <div class="card" style="box-shadow: none">
            <div class="card-head"><div class="card-title">服务配置</div></div>
            <div class="card-body">
              <dl class="kv">
                <dt>问答模型</dt><dd>{{ system?.llm?.mode }}</dd>
                <dt>知识库规模</dt><dd class="mono">{{ system?.retrieval?.collection?.documents }} 份文献 / {{ system?.retrieval?.collection?.chunks }} 条知识条目</dd>
                <dt>覆盖科室</dt><dd>{{ (system?.retrieval?.collection?.departments || []).join('、') }}</dd>
                <dt>检索深度</dt><dd class="mono">每轮检索 {{ system?.retrieval?.top_n }} 条 → 采用 {{ system?.retrieval?.top_k }} 条</dd>
                <dt>回答策略</dt><dd>依据充分时作答，依据不足时提示补充信息或转人工</dd>
                <dt>知识库说明</dt><dd class="tiny">{{ system?.retrieval?.collection?.notice }}</dd>
              </dl>
            </div>
          </div>
          <div class="card" style="box-shadow: none">
            <div class="card-head"><div class="card-title">数据与运维</div></div>
            <div class="card-body">
              <dl class="kv">
                <dt>问诊会话保存</dt><dd>{{ system?.memory?.backend }}</dd>
                <dt>扩容方案</dt><dd class="tiny">{{ system?.memory?.upgrade_path }}</dd>
                <dt>调用记录留存</dt><dd>{{ (system?.observability?.trace_sinks || []).join(' + ') }}</dd>
                <dt>采样率</dt><dd class="mono">{{ system?.observability?.sample_rate }}</dd>
                <dt>版本</dt><dd class="mono">{{ system?.app?.name }} v{{ system?.app?.version }}</dd>
              </dl>
            </div>
          </div>
        </div>
        <div class="card" style="box-shadow: none">
          <div class="card-head"><div class="card-title">设计原则</div></div>
          <div class="card-body">
            <div class="grid grid-2" style="gap: 10px">
              <div v-for="p in system?.principles || []" :key="p" class="evidence" style="border-left-color: var(--brand)">{{ p }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 调用详情 -->
    <Transition name="fade">
      <div v-if="detail" class="overlay" @click.self="detail = null">
        <div class="modal" style="width: min(880px, 100%)">
          <div class="modal-head">
            <div class="row" style="gap: 8px">
              <span class="badge blue mono">{{ detail.request_id }}</span>
              <span class="badge" :class="detail.status === 'success' ? 'green' : 'red'">{{ detail.status === 'success' ? '成功' : '失败' }}</span>
              <b>{{ AGENT_LABELS[detail.agent_type] || detail.agent_type }}</b>
            </div>
          </div>
          <div class="modal-body">
            <dl class="kv" style="margin-bottom: 14px">
              <dt>用户问题</dt><dd>{{ detail.query }}</dd>
              <dt>回答方式</dt><dd>{{ ROUTE_LABELS[detail.route_level] || detail.route_level }} · {{ detail.route_reason }}</dd>
              <dt>耗时 / 模型用量</dt><dd class="mono">{{ detail.elapsed_ms }} ms / {{ detail.total_tokens }}</dd>
              <dt>所属院区</dt><dd>{{ state.tenantName }}</dd>
              <dt>自动降级</dt><dd>{{ detail.fallback_used ? '已降级' : '否' }}</dd>
            </dl>
            <b class="tiny muted">各环节耗时明细</b>
            <div style="margin-top: 8px"><TraceWaterfall :spans="detail.spans" :total-ms="detail.elapsed_ms" /></div>
          </div>
          <div class="modal-foot"><button class="btn" @click="detail = null">关闭</button></div>
        </div>
      </div>
    </Transition>
  </div>
</template>
