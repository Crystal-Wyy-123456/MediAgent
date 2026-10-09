<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { state, toast } from '../store'

const mode = ref('session')
const sessionId = ref('')
const text = ref('')
const running = ref(false)
const result = ref(null)
const topology = ref(null)
const records = ref([])
const preconsultHistory = ref([])

const steps = computed(() => result.value?.structured?.steps || [])
const gates = computed(() => result.value?.structured?.gates || [])
const aborted = computed(() => !!result.value?.structured?.aborted)

const GATE_LABELS = { gate_red_flag: '风险症状校验', gate_completeness: '病史完整度校验' }
const ABORT_REASONS = {
  RED_FLAG_HANDOVER: '命中风险症状，已转医生接管',
  INSUFFICIENT_INFO: '病史信息不完整，需人工补充',
}
const PASSED_FIELDS = ['患者基本信息', '主诉', '现病史', '既往史', '用药史', '过敏史', '症状完整度']

onMounted(async () => {
  try {
    topology.value = await api('/api/v1/pipeline/topology')
    const res = await api('/api/v1/medreview?limit=20', { token: state.token })
    records.value = res.items || []
  } catch {
    /* 忽略 */
  }
  sessionId.value = state.preconsult.sessionId || ''
  if (!sessionId.value) {
    try {
      const res = await api('/api/v1/library/pipeline-input')
      text.value = res.record_text || ''
    } catch {
      /* 忽略 */
    }
  }
})

async function run() {
  running.value = true
  result.value = null
  try {
    result.value = await api('/api/v1/pipeline/preconsult-review', {
      method: 'POST',
      body: { session_id: mode.value === 'session' ? sessionId.value : '', text: mode.value === 'text' ? text.value : '' },
      token: state.token,
    })
    toast(result.value.success ? '联动执行完成' : '联动未执行', result.value.success ? 'success' : 'warn')
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    running.value = false
  }
}

function fillSample() {
  mode.value = 'text'
  api('/api/v1/library/pipeline-input').then((res) => {
    text.value = res.record_text
  })
}
</script>

<template>
  <div class="stack">
    <div class="grid" style="grid-template-columns: minmax(320px, 0.8fr) minmax(0, 1.55fr); align-items: start">
      <div class="stack">
        <div class="card">
          <div class="card-head"><div class="card-title"><span class="badge purple">联动</span> 诊疗联动</div></div>
          <div class="card-body stack">
            <div class="tabs">
              <div class="tab" :class="{ active: mode === 'session' }" @click="mode = 'session'">已完成预问诊的会话</div>
              <div class="tab" :class="{ active: mode === 'text' }" @click="mode = 'text'">直接给病历文本</div>
            </div>

            <template v-if="mode === 'session'">
              <div class="field">
                <label>预问诊会话号</label>
                <input v-model="sessionId" class="input mono" placeholder="sess_xxxxxxxxxxxx" />
              </div>
              <div class="tiny muted">
                系统会直接读取该会话已采集完成的病史信息，<b>不会重复询问患者</b>。
                会话号可在患者完成预问诊后获取。
              </div>
            </template>
            <template v-else>
              <div class="field">
                <label>病历文本（直接作为质控输入）</label>
                <textarea v-model="text" class="textarea" rows="12" />
              </div>
              <button class="btn sm" @click="fillSample">载入典型病历</button>
            </template>

            <button class="btn primary block" :disabled="running" @click="run">
              <span v-if="running" class="spinner"></span>{{ running ? '联动执行中…' : '开始联动' }}
            </button>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><div class="card-title">信息传递</div></div>
          <div class="card-body">
            <div class="tiny muted" style="line-height: 1.75">预问诊采集到的病史信息会自动带入病历质控环节，包括：</div>
            <div class="row wrap" style="gap: 6px; margin-top: 8px">
              <span v-for="f in PASSED_FIELDS" :key="f" class="badge grey">{{ f }}</span>
            </div>
            <div class="divider"></div>
            <div class="tiny muted">质控结果（评分与问题清单）会回写到本次就诊记录，医生可随时查阅。</div>
          </div>
        </div>
      </div>

      <div class="stack">
        <div class="card">
          <div class="card-head">
            <div class="card-title">联动流程</div>
            <span v-if="topology" class="card-sub">{{ topology.items[0]?.description }}</span>
          </div>
          <div class="card-body">
            <div class="row wrap" style="gap: 10px">
              <div class="chip" style="cursor: default; border-style: solid; border-color: var(--brand); background: var(--brand-soft); color: var(--brand-dark)">
                ① 患者病史信息
              </div>
              <span class="muted">→</span>
              <div class="chip" style="cursor: default; border-style: solid" :style="steps[0]?.success ? { borderColor: 'var(--ok)', background: 'var(--ok-soft)', color: 'var(--ok)' } : {}">
                ② 预问诊采集
              </div>
              <span class="muted">→</span>
              <div class="chip" style="cursor: default; border-style: solid; border-color: var(--warn); background: var(--warn-soft); color: var(--warn)">
                ③ 风险与完整度校验
              </div>
              <span class="muted">→</span>
              <div class="chip" style="cursor: default; border-style: solid; border-color: var(--purple); background: var(--purple-soft); color: var(--purple)">
                ④ 信息传递
              </div>
              <span class="muted">→</span>
              <div class="chip" style="cursor: default; border-style: solid" :style="steps[1]?.success ? { borderColor: 'var(--ok)', background: 'var(--ok-soft)', color: 'var(--ok)' } : {}">
                ⑤ 病历质控
              </div>
            </div>
          </div>
        </div>

        <div v-if="!result" class="card">
          <div class="card-body empty" style="padding: 70px 20px">
            <span class="icon">🔗</span>
            <div style="font-weight: 650; color: var(--ink-2); margin-bottom: 6px">运行一次预问诊 → 病历质控联动</div>
            <div>若患者命中风险症状，或病史信息不完整，流程会自动中止并提醒医生，<br />不会带着风险继续进入质控环节。</div>
          </div>
        </div>

        <template v-else>
          <div class="grid grid-4">
            <div class="stat" :class="result.success ? 'teal' : 'danger'">
              <div class="stat-label">执行状态</div>
              <div class="stat-value small">{{ aborted ? '校验中止' : result.success ? '联动完成' : '失败' }}</div>
              <div class="stat-foot">预问诊 → 病历质控</div>
            </div>
            <div class="stat"><div class="stat-label">执行步骤</div><div class="stat-value">{{ steps.length }}</div><div class="stat-foot">预问诊 → 病历质控</div></div>
            <div class="stat purple">
              <div class="stat-label">传递信息</div>
              <div class="stat-value">{{ Object.keys(result.structured?.context || {}).length }}</div>
              <div class="stat-foot">已带入质控环节</div>
            </div>
            <div class="stat"><div class="stat-label">总耗时</div><div class="stat-value small">{{ (result.latency_ms || 0).toFixed(0) }}ms</div><div class="stat-foot">从开始到出结果</div></div>
          </div>

          <div class="card">
            <div class="card-head"><div class="card-title">步骤结果</div></div>
            <div class="card-body">
              <div class="timeline">
                <div v-for="(s, i) in steps" :key="i" class="tl-item" :class="s.success ? 'ok' : 'danger'">
                  <div class="tl-title">
                    <span class="badge" :class="s.success ? 'green' : 'red'">{{ s.success ? '成功' : '失败' }}</span>
                    <b>{{ s.label }}</b>
                    <span class="tiny muted">{{ (s.elapsed_ms || 0).toFixed(0) }}ms</span>
                  </div>
                  <div class="tl-desc">{{ s.summary }}</div>
                </div>
              </div>
              <div class="divider"></div>
              <div class="row wrap" style="gap: 8px">
                <span v-for="(g, i) in gates" :key="i" class="badge" :class="g.aborted ? 'red' : 'green'">
                  {{ GATE_LABELS[g.gate] || g.gate }} · {{ g.aborted ? '已中止' : '通过' }}
                </span>
              </div>
            </div>
          </div>

          <div v-if="aborted" class="card" style="border-color: #f7cfcb">
            <div class="card-body evidence" style="border-left-color: var(--danger); background: var(--danger-soft)">
              <b>联动已中止：{{ ABORT_REASONS[result.structured.reason] || result.structured.reason }}</b>
              <div class="tiny" style="margin-top: 4px">{{ result.structured.detail }}</div>
              <div class="tiny muted" style="margin-top: 6px">病历质控环节未执行，避免用不完整或带风险的信息继续质控。</div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
