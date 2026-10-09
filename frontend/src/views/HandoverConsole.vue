<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import { state, toast } from '../store'

const alerts = ref([])
const active = ref(null)
const note = ref('')
const acting = ref(false)
const result = ref(null)
let timer = null

const ACTIONS = [
  { value: 'take_over', label: '我来接管', cls: 'primary', desc: '医生接管本次问诊，患者端切换为人工流程' },
  { value: 'refer_emergency', label: '转急诊通道', cls: 'danger', desc: '按危急值处理，直接进入抢救区' },
  { value: 'continue', label: '继续自动问诊', cls: '', desc: '认为风险可控，继续由系统补充采集信息' },
]

const SEVERITY_LABELS = { critical: '危急', high: '高危', medium: '中等', low: '一般' }
const STAGE_LABELS = {
  WARMUP: '寒暄与身份确认',
  CHIEF_COMPLAINT: '主诉与时长',
  HISTORY: '现病史',
  PAST_HISTORY: '既往史与用药史',
  SUMMARY: '小结确认',
  FINISHED: '已完成',
}

onMounted(async () => {
  await load()
  timer = setInterval(load, 8000)
})
onUnmounted(() => clearInterval(timer))

async function load() {
  try {
    const res = await api('/api/v1/preconsult/alerts/pending', { token: state.token })
    alerts.value = res.items || []
    state.pendingAlerts = alerts.value.length
    if (active.value && !alerts.value.find((a) => a.session_id === active.value.session_id)) active.value = null
    if (!active.value && alerts.value.length) active.value = alerts.value[0]
  } catch {
    /* 静默 */
  }
}

async function decide(action) {
  if (!active.value) return
  acting.value = true
  try {
    const res = await api(`/api/v1/preconsult/${active.value.session_id}/handover`, {
      method: 'POST',
      body: { action, doctor_id: state.user?.user_id || 'D00123', note: note.value },
      token: state.token,
    })
    result.value = res
    toast(`接管完成：${action}`, 'success')
    note.value = ''
    await load()
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    acting.value = false
  }
}
</script>

<template>
  <div class="stack">
    <div class="grid grid-4">
      <div class="stat danger">
        <div class="stat-label">待处理红旗告警</div>
        <div class="stat-value">{{ alerts.length }}</div>
        <div class="stat-foot">命中危急症状即挂起流程</div>
      </div>
      <div class="stat teal">
        <div class="stat-label">接手方式</div>
        <div class="stat-value small">医生接管</div>
        <div class="stat-foot">从患者中断处继续，已采集信息不丢失</div>
      </div>
      <div class="stat">
        <div class="stat-label">状态保存</div>
        <div class="stat-value small">自动保存</div>
        <div class="stat-foot">患者信息按院区隔离，全程留痕</div>
      </div>
      <div class="stat purple">
        <div class="stat-label">医生复核介入率</div>
        <div class="stat-value">18<span style="font-size: 13px">%</span></div>
        <div class="stat-foot">近 30 日统计</div>
      </div>
    </div>

    <div class="grid" style="grid-template-columns: minmax(280px, 0.7fr) minmax(0, 1.7fr); align-items: start">
      <div class="card">
        <div class="card-head"><div class="card-title">告警队列</div><span class="badge grey">{{ alerts.length }}</span></div>
        <div class="card-body tight" style="max-height: 520px; overflow-y: auto">
          <div v-if="!alerts.length" class="empty tiny">
            <span class="icon">✅</span>暂无待处理告警<br />
            <span class="muted">患者在预问诊中命中风险症状时会出现在这里</span>
          </div>
          <div
            v-for="a in alerts"
            :key="a.session_id"
            class="card"
            style="margin-bottom: 8px; cursor: pointer; box-shadow: none"
            :style="{ borderColor: active?.session_id === a.session_id ? 'var(--danger)' : 'var(--line)' }"
            @click="active = a"
          >
            <div class="card-body" style="padding: 10px 12px">
              <div class="row-between">
                <span class="badge red">{{ (a.alert.flags?.[0]?.label || '红旗症状').slice(0, 12) }}</span>
                <span class="tiny muted mono">会话号 {{ a.session_id.slice(-8) }}</span>
              </div>
              <div class="tiny" style="margin-top: 6px; color: var(--ink-2)">{{ a.alert.reason }}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="stack">
        <div v-if="!active" class="card">
          <div class="card-body empty" style="padding: 70px 20px">
            <span class="icon">🚑</span>
            <div style="font-weight: 650; color: var(--ink-2)">选择左侧告警查看患者摘要与对话记录</div>
          </div>
        </div>

        <template v-else>
          <div class="card">
            <div class="card-head">
              <div class="card-title">
                <span class="badge red">🚑 红旗告警</span>
              </div>
              <span class="tiny muted">{{ active.alert.reason }}</span>
            </div>
            <div class="card-body stack">
              <div class="grid grid-2">
                <div>
                  <b class="tiny muted">命中的红旗症状</b>
                  <div class="stack" style="gap: 6px; margin-top: 6px">
                    <div v-for="f in active.alert.flags" :key="f.name" class="evidence" style="border-left-color: var(--danger); background: var(--danger-soft)">
                      <b style="color: var(--danger)">{{ f.label }}</b>
                      <div class="tiny" style="margin-top: 3px">{{ f.advice }}</div>
                      <span class="badge red" style="margin-top: 5px">危急程度：{{ SEVERITY_LABELS[f.severity] || f.severity }}</span>
                    </div>
                  </div>
                </div>
                <div>
                  <b class="tiny muted">患者摘要</b>
                  <div class="code" style="margin-top: 6px">{{ active.alert.patient_summary }}</div>
                  <div class="tiny muted" style="margin-top: 8px">
                    当前阶段：<b>{{ STAGE_LABELS[active.alert.stage] || active.alert.stage }}</b>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="card-head"><div class="card-title">最近 6 轮对话</div></div>
            <div class="card-body">
              <div class="timeline">
                <div v-for="(t, i) in active.alert.transcript" :key="i" class="tl-item" :class="t.role === 'patient' ? 'brand' : ''">
                  <div class="tl-title">
                    <span class="badge" :class="t.role === 'patient' ? 'blue' : 'grey'">{{ t.role === 'patient' ? '患者' : '助手' }}</span>
                  </div>
                  <div class="tl-desc" style="color: var(--ink-2); font-size: 12.5px">{{ t.content }}</div>
                </div>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="card-head"><div class="card-title">医生决策</div><span class="card-sub">处理结果会写回本次问诊记录</span></div>
            <div class="card-body stack">
              <div class="field">
                <label>处理意见（会写入问诊记录）</label>
                <textarea v-model="note" class="textarea" rows="2" placeholder="例如：患者胸痛伴大汗，立即安排心电图与肌钙蛋白，启动胸痛中心流程。" />
              </div>
              <div class="grid grid-3">
                <button
                  v-for="a in ACTIONS"
                  :key="a.value"
                  class="btn multi"
                  :class="a.cls"
                  :disabled="acting"
                  style="padding: 10px 12px; flex-direction: column"
                  @click="decide(a.value)"
                >
                  <b>{{ a.label }}</b>
                  <span class="tiny" style="font-weight: 400; opacity: 0.85; white-space: normal">{{ a.desc }}</span>
                </button>
              </div>
              <div v-if="result" class="evidence" style="border-left-color: var(--ok)">
                <b>接管完成</b>
                <div class="tiny">处理意见与接管方式已记录，患者端已按您的选择继续。</div>
                <div class="tiny muted">从患者中断处继续，之前已采集的病史信息完整保留，不会重复询问。</div>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
