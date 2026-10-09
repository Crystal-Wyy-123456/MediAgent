<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, upload } from '../api'
import { state, toast } from '../store'
import ChartBox from '../components/ChartBox.vue'
import StatCard from '../components/StatCard.vue'

const samples = ref([])
const history = ref([])
const text = ref('')
const title = ref('')
const running = ref(false)
const result = ref(null)
const tab = ref('issues')
const filter = ref('all')
const rules = ref([])

const DIM_LABELS = {
  completeness: '完整性',
  consistency: '一致性',
  diagnosis_basis: '诊断依据',
  medication_rationality: '用药合理性',
  logic: '逻辑性',
  standardization: '规范性',
  rule: '规则核查',
  cross_doc: '跨文档一致性',
}

const SEVERITY = { error: { label: '严重', cls: 'red' }, warn: { label: '警告', cls: 'amber' }, info: { label: '提示', cls: 'grey' } }

const filtered = computed(() => {
  if (!result.value) return []
  return filter.value === 'all' ? result.value.issues : result.value.issues.filter((i) => i.severity === filter.value)
})

const radarOption = computed(() => {
  const dims = result.value?.report?.dimension_scores || {}
  const keys = Object.keys(dims)
  return {
    radar: {
      indicator: keys.map((k) => ({ name: DIM_LABELS[k] || k, max: 10 })),
      radius: '66%',
      splitLine: { lineStyle: { color: '#e2e8f0' } },
      axisName: { color: '#64748b', fontSize: 11 },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: keys.map((k) => dims[k]),
            areaStyle: { color: 'rgba(26,111,212,0.18)' },
            lineStyle: { color: '#1a6fd4', width: 2 },
            itemStyle: { color: '#1a6fd4' },
          },
        ],
      },
    ],
  }
})

const issueOption = computed(() => {
  const counts = { error: 0, warn: 0, info: 0 }
  ;(result.value?.issues || []).forEach((i) => (counts[i.severity] = (counts[i.severity] || 0) + 1))
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: { fontSize: 11, color: '#64748b' } },
    series: [
      {
        type: 'pie',
        radius: ['52%', '74%'],
        avoidLabelOverlap: true,
        label: { show: true, formatter: '{c}', fontSize: 12 },
        data: [
          { value: counts.error, name: '严重', itemStyle: { color: '#d92d20' } },
          { value: counts.warn, name: '警告', itemStyle: { color: '#c77700' } },
          { value: counts.info, name: '提示', itemStyle: { color: '#94a3b8' } },
        ],
      },
    ],
  }
})

onMounted(async () => {
  try {
    samples.value = (await api('/api/v1/library/records')).items
    rules.value = (await api('/api/v1/medreview/rules')).items
    await loadHistory()
  } catch (err) {
    toast(err.message, 'error')
  }
})

async function loadHistory() {
  try {
    history.value = (await api('/api/v1/medreview?limit=12', { token: state.token })).items
  } catch {
    history.value = []
  }
}

function useSample(s) {
  text.value = s.text
  title.value = s.title
}

async function submit() {
  if (!text.value.trim()) return toast('请先载入或粘贴病历内容', 'warn')
  running.value = true
  result.value = null
  try {
    result.value = await api('/api/v1/medreview/submit', { method: 'POST', body: { text: text.value, title: title.value }, token: state.token })
    state.lastReviewId = result.value.review_id
    toast(`质控完成：${result.value.report.overall_score} 分（${result.value.report.grade}）`, 'success')
    await loadHistory()
  } catch (err) {
    toast(`质控失败：${err.message}`, 'error')
  } finally {
    running.value = false
  }
}

async function onFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  running.value = true
  try {
    result.value = await upload('/api/v1/medreview/upload', file, state.token)
    toast('文件质控完成', 'success')
    await loadHistory()
  } catch (err) {
    toast(`解析失败：${err.message}`, 'error')
  } finally {
    running.value = false
    event.target.value = ''
  }
}

async function openReview(id) {
  try {
    const data = await api(`/api/v1/medreview/${id}`, { token: state.token })
    result.value = {
      review_id: data.review_id,
      report: {
        overall_score: data.overall_score,
        grade: data.grade,
        issue_count: data.issues.length,
        severity_count: data.issues.reduce((acc, i) => ({ ...acc, [i.severity]: (acc[i.severity] || 0) + 1 }), {}),
        dimension_scores: Object.fromEntries((data.dimension_results || []).map((d) => [d.dimension, d.score])),
        rule_pass_rate: data.rule_results.length ? data.rule_results.filter((r) => r.passed).length / data.rule_results.length : 1,
      },
      issues: data.issues.map((i) => ({ ...i, issue_id: i.issue_id.split(':').pop() })),
      structured_record: data.structured_record,
      rule_results: data.rule_results,
      dimension_results: data.dimension_results,
      cross_doc_results: data.cross_doc_results,
      elapsed_ms: data.elapsed_ms,
    }
  } catch (err) {
    toast(err.message, 'error')
  }
}

async function decide(issue, accepted) {
  try {
    await api(`/api/v1/medreview/${result.value.review_id}/issues/${issue.issue_id}`, {
      method: 'PATCH',
      body: { accepted },
      token: state.token,
    })
    issue.accepted = accepted
    toast(accepted ? '已采纳该问题' : '已驳回该问题', 'success')
  } catch (err) {
    toast(err.message, 'error')
  }
}
</script>

<template>
  <div class="stack">
    <div class="grid" style="grid-template-columns: minmax(320px, 0.78fr) minmax(0, 1.6fr); align-items: start">
      <!-- 输入区 -->
      <div class="stack">
        <div class="card">
          <div class="card-head">
            <div class="card-title"><span class="badge teal">MedReview</span> 病历质控</div>
          </div>
          <div class="card-body stack">
            <div class="field">
              <label>一键载入典型病历</label>
              <div class="stack" style="gap: 6px">
                <button v-for="s in samples" :key="s.id" class="btn sm multi" style="width: 100%" @click="useSample(s)">
                  <span class="grow">
                    <b style="font-size: 12.5px; display: block">{{ s.title }}</b>
                    <span class="tiny muted" style="font-weight: 400; display: block; margin-top: 3px">{{ s.description }}</span>
                  </span>
                </button>
              </div>
            </div>

            <div class="field">
              <label>病历文本（可粘贴真实病历，支持上传 PDF / DOCX）</label>
              <textarea v-model="text" class="textarea" rows="12" placeholder="【姓名】…&#10;【主诉】…&#10;【现病史】…" />
            </div>

            <div class="row" style="gap: 8px">
              <button class="btn primary grow" :disabled="running" @click="submit">
                <span v-if="running" class="spinner"></span>{{ running ? '质控分析中…' : '提交质控' }}
              </button>
              <label class="btn" style="cursor: pointer">
                上传文件
                <input type="file" accept=".pdf,.docx,.txt,.md" style="display: none" @change="onFile" />
              </label>
            </div>
            <div class="tiny muted">三重校验：规则核查 + 病历内涵评审 + 跨文档一致性比对</div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><div class="card-title">质控历史</div><span class="badge grey">{{ history.length }}</span></div>
          <div class="card-body tight" style="max-height: 240px; overflow-y: auto">
            <div v-if="!history.length" class="empty tiny">暂无记录</div>
            <div
              v-for="h in history"
              :key="h.review_id"
              class="row-between"
              style="padding: 7px 8px; border-radius: 7px; cursor: pointer"
              @click="openReview(h.review_id)"
            >
              <div class="grow">
                <div style="font-size: 12px; font-weight: 600">{{ h.patient_name || '未命名病历' }}</div>
                <div class="tiny muted mono">编号 {{ h.review_id }}</div>
              </div>
              <div style="text-align: right">
                <div class="mono" style="font-weight: 700">{{ h.overall_score }}</div>
                <div class="tiny muted">{{ h.issue_count }} 问题</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 结果区 -->
      <div class="stack">
        <div v-if="!result" class="card">
          <div class="card-body empty" style="padding: 80px 20px">
            <span class="icon">📋</span>
            <div style="font-weight: 650; color: var(--ink-2); margin-bottom: 6px">尚未提交质控</div>
            <div>选择左侧病历或粘贴病历文本后提交，即可看到质控评分、问题清单与逐条修改建议。</div>
          </div>
        </div>

        <template v-else>
          <div class="grid grid-4">
            <StatCard label="综合评分" :value="`${result.report.overall_score}`" :foot="result.report.grade" tone="teal" />
            <StatCard label="问题总数" :value="result.report.issue_count" :foot="`严重 ${result.report.severity_count.error || 0} · 警告 ${result.report.severity_count.warn || 0}`" tone="danger" />
            <StatCard label="规则通过率" :value="`${Math.round((result.report.rule_pass_rate || 0) * 100)}%`" foot="规则核查通过情况" />
            <StatCard label="质控耗时" :value="`${(result.elapsed_ms || 0).toFixed(0)}ms`" foot="从提交到出结果" tone="purple" />
          </div>

          <div class="grid grid-2">
            <div class="card">
              <div class="card-head"><div class="card-title">六维度评分</div><span class="card-sub">内涵评审</span></div>
              <div class="card-body"><ChartBox :option="radarOption" height="230px" /></div>
            </div>
            <div class="card">
              <div class="card-head"><div class="card-title">问题严重度分布</div></div>
              <div class="card-body"><ChartBox :option="issueOption" height="230px" /></div>
            </div>
          </div>

          <div class="card">
            <div class="tabs">
              <div class="tab" :class="{ active: tab === 'issues' }" @click="tab = 'issues'">问题清单（{{ result.issues.length }}）</div>
              <div class="tab" :class="{ active: tab === 'tracks' }" @click="tab = 'tracks'">质控明细</div>
              <div class="tab" :class="{ active: tab === 'record' }" @click="tab = 'record'">结构化病历</div>
            </div>

            <div v-if="tab === 'issues'" class="card-body">
              <div class="row wrap" style="gap: 6px; margin-bottom: 10px">
                <button class="chip" :style="filter === 'all' ? { borderColor: 'var(--brand)', color: 'var(--brand)' } : {}" @click="filter = 'all'">
                  全部 {{ result.issues.length }}
                </button>
                <button v-for="(v, k) in { error: '严重', warn: '警告', info: '提示' }" :key="k" class="chip"
                        :style="filter === k ? { borderColor: 'var(--brand)', color: 'var(--brand)' } : {}" @click="filter = k">
                  {{ v }} {{ result.issues.filter((i) => i.severity === k).length }}
                </button>
              </div>

              <div class="stack" style="gap: 10px">
                <div v-for="issue in filtered" :key="issue.issue_id" class="card" style="box-shadow: none">
                  <div class="card-body" style="padding: 12px 14px">
                    <div class="row-between" style="align-items: flex-start">
                      <div class="grow">
                        <div class="row wrap" style="gap: 6px">
                          <span class="badge" :class="SEVERITY[issue.severity].cls">{{ SEVERITY[issue.severity].label }}</span>
                          <span class="badge grey">{{ DIM_LABELS[issue.dimension] || issue.dimension }}</span>
                          <span v-if="issue.source_rule" class="badge purple mono">{{ issue.source_rule }}</span>
                          <span v-if="issue.accepted === true" class="badge green">已采纳</span>
                          <span v-if="issue.accepted === false" class="badge grey">已驳回</span>
                        </div>
                        <div style="font-weight: 650; margin-top: 7px; font-size: 13px">{{ issue.title }}</div>
                      </div>
                      <div class="row" style="gap: 6px">
                        <button class="btn sm" @click="decide(issue, true)">采纳</button>
                        <button class="btn sm ghost" @click="decide(issue, false)">驳回</button>
                      </div>
                    </div>
                    <div class="evidence" style="margin-top: 9px">
                      <b class="tiny" style="color: var(--ink-3)">证据原文 · {{ issue.location }}</b>
                      <div>{{ issue.evidence }}</div>
                    </div>
                    <div class="tiny" style="margin-top: 7px; color: var(--ink-2)">
                      <b style="color: var(--ink-3)">修改建议：</b>{{ issue.suggestion }}
                    </div>
                  </div>
                </div>
                <div v-if="!filtered.length" class="empty tiny">该严重度下没有问题</div>
              </div>
            </div>

            <div v-else-if="tab === 'tracks'" class="card-body stack">
              <div class="grid grid-3">
                <div class="card" style="box-shadow: none">
                  <div class="card-body">
                    <div class="row-between"><b>规则核查</b><span class="badge blue">确定性规则</span></div>
                    <div class="tiny muted" style="margin: 6px 0 8px">时效性 / 签名 / 必填项 / 格式规范</div>
                    <div class="stack" style="gap: 5px">
                      <div v-for="r in result.rule_results" :key="r.rule_id" class="row" style="gap: 7px; font-size: 12px">
                        <span :class="r.passed ? 'badge green' : 'badge red'">{{ r.passed ? '通过' : '不通过' }}</span>
                        <span class="mono tiny muted">{{ r.rule_id }}</span>
                        <span class="grow">{{ r.rule_name }}</span>
                      </div>
                    </div>
                  </div>
                </div>
                <div class="card" style="box-shadow: none">
                  <div class="card-body">
                    <div class="row-between"><b>内涵评审</b><span class="badge purple">六维度</span></div>
                    <div class="tiny muted" style="margin: 6px 0 8px">完整性 / 一致性 / 诊断依据 / 用药合理性 / 逻辑性 / 规范性</div>
                    <div class="stack" style="gap: 7px">
                      <div v-for="d in result.dimension_results" :key="d.dimension">
                        <div class="row-between tiny"><span>{{ DIM_LABELS[d.dimension] }}</span><b class="mono">{{ d.score }}</b></div>
                        <div class="progress" :class="d.score >= 9 ? 'ok' : d.score >= 7 ? 'warn' : 'danger'">
                          <span :style="{ width: `${d.score * 10}%` }"></span>
                        </div>
                        <div class="tiny muted" style="margin-top: 2px">{{ d.summary }}</div>
                      </div>
                    </div>
                  </div>
                </div>
                <div class="card" style="box-shadow: none">
                  <div class="card-body">
                    <div class="row-between"><b>跨文档一致性</b><span class="badge amber">一致性核对</span></div>
                    <div class="tiny muted" style="margin: 6px 0 8px">医嘱 ↔ 病程 ↔ 检验 三方一致性</div>
                    <div v-if="!(result.cross_doc_results || []).length" class="badge green">未发现不一致</div>
                    <div class="stack" style="gap: 8px">
                      <div v-for="c in result.cross_doc_results" :key="c.check_id" class="evidence">
                        <b class="tiny">{{ c.name }}</b>
                        <div class="tiny">{{ c.a_source }}：{{ c.a_value }}</div>
                        <div class="tiny">{{ c.b_source }}：{{ c.b_value }}</div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="card" style="box-shadow: none">
                <div class="card-head"><div class="card-title">质控规则表</div><span class="badge grey">{{ rules.length }} 条</span></div>
                <div class="card-body flush">
                  <table class="table">
                    <thead><tr><th>规则</th><th>名称</th><th>等级</th><th>权重</th><th>定位</th></tr></thead>
                    <tbody>
                      <tr v-for="r in rules" :key="r.rule_id">
                        <td class="mono">{{ r.rule_id }}</td>
                        <td>{{ r.rule_name }}</td>
                        <td><span class="badge" :class="SEVERITY[r.level]?.cls">{{ SEVERITY[r.level]?.label || r.level }}</span></td>
                        <td class="mono">{{ r.weight }}</td>
                        <td class="muted tiny">{{ r.location }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div v-else class="card-body">
              <div class="grid grid-2">
                <dl class="kv">
                  <dt>姓名</dt><dd>{{ result.structured_record.patient_name || '—' }}</dd>
                  <dt>性别 / 年龄</dt><dd>{{ result.structured_record.gender }} / {{ result.structured_record.age }}</dd>
                  <dt>科室</dt><dd>{{ result.structured_record.department || '—' }}</dd>
                  <dt>病历类型</dt><dd>{{ result.structured_record.record_type }}</dd>
                  <dt>入院时间</dt><dd class="mono">{{ result.structured_record.admit_time || '—' }}</dd>
                  <dt>记录时间</dt><dd class="mono">{{ result.structured_record.record_time || '—' }}</dd>
                  <dt>主诉</dt><dd>{{ result.structured_record.chief_complaint || '—' }}</dd>
                  <dt>初步诊断</dt><dd>{{ (result.structured_record.diagnosis || []).join('；') || '—' }}</dd>
                </dl>
                <dl class="kv">
                  <dt>签名</dt><dd>{{ result.structured_record.doctor_sign || '缺失' }} / {{ result.structured_record.resident_sign || '缺失' }}</dd>
                  <dt>医嘱条数</dt><dd class="mono">{{ (result.structured_record.orders || []).length }}</dd>
                  <dt>病程记录</dt><dd class="mono">{{ (result.structured_record.course_notes || []).length }} 条</dd>
                  <dt>字段完整</dt><dd>{{ (result.structured_record.sections_found || []).join('、') || '—' }}</dd>
                  <dt>字数</dt><dd class="mono">{{ result.structured_record.word_count }}</dd>
                </dl>
              </div>
              <div class="divider"></div>
              <div class="stack" style="gap: 8px">
                <div><b class="tiny muted">现病史</b><div style="font-size: 12.5px; line-height: 1.7">{{ result.structured_record.present_illness || '—' }}</div></div>
                <div><b class="tiny muted">医嘱</b><div class="code">{{ (result.structured_record.orders || []).join('\n') || '—' }}</div></div>
                <div><b class="tiny muted">病程记录</b><div class="code">{{ (result.structured_record.course_notes || []).join('\n\n') || '—' }}</div></div>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
