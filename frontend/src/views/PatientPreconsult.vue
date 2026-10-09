<script setup>
import { computed, onMounted, nextTick, ref } from 'vue'
import { api } from '../api'
import { state, toast } from '../store'
import StageStepper from '../components/StageStepper.vue'

const stages = ref([])
const script = ref({ normal: [], red_flag: [], vague: [] })
const persona = ref({})
const messages = ref([])
const input = ref('')
const busy = ref(false)
const sessionId = ref('')
const patientId = ref('')
const stage = ref('')
const handover = ref(false)
const handoverReason = ref([])
const filledSlots = ref({})
const slotValues = ref({})
const quality = ref('')
const route = ref('')
const draft = ref(null)
const alert = ref(null)
const autoRunning = ref(false)
const scroller = ref(null)

const SLOT_LABELS = {
  patient_confirmed: '身份确认', chief_complaint: '主要症状', duration: '持续时间',
  onset: '起病时间', symptoms: '症状特点', aggravating_factors: '加重/缓解因素',
  past_disease: '既往病史', medication: '用药情况', allergy: '过敏史', patient_ack: '患者确认',
  age: '年龄', gender: '性别', patient_name: '姓名',
}

const progress = computed(() => {
  const index = stages.value.findIndex((s) => s.id === stage.value)
  if (stage.value === 'FINISHED') return 100
  return Math.round(((index + 1) / stages.value.length) * 100)
})

const stageLabel = computed(() => stages.value.find((s) => s.id === stage.value)?.label || (stage.value === 'FINISHED' ? '已完成' : '—'))

const QUALITY = {
  EXCELLENT: { label: '回答丰富', cls: 'green' },
  ADEQUATE: { label: '信息基本完整', cls: 'blue' },
  WEAK: { label: '信息过少', cls: 'amber' },
  NO_ANSWER: { label: '未答上来', cls: 'red' },
}

const HANDOVER_OPTIONS = {
  take_over: '医生接管',
  refer_emergency: '转急诊通道',
  continue: '继续自动问诊',
}

onMounted(async () => {
  try {
    stages.value = (await api('/api/v1/preconsult/stages')).stages
    const s = await api('/api/v1/library/preconsult-script')
    script.value = s.scripts
    persona.value = s.persona
  } catch (err) {
    toast(err.message, 'error')
  }
  await start()
})

async function scrollDown() {
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
}

function applyView(view) {
  stage.value = view.stage
  filledSlots.value = view.filled_slots || {}
  slotValues.value = view.slot_values || {}
  quality.value = view.quality || quality.value
  route.value = view.route || ''
  handover.value = !!view.handover
  handoverReason.value = view.handover_reason || []
  if (view.draft_record && Object.keys(view.draft_record).length) draft.value = view.draft_record
  if (view.session_id) sessionId.value = view.session_id
  if (view.patient_id) patientId.value = view.patient_id
  state.preconsult = { sessionId: sessionId.value, patientId: patientId.value, stage: stage.value, draft: draft.value }
}

async function start() {
  busy.value = true
  try {
    const view = await api('/api/v1/preconsult/start', { method: 'POST', body: { patient_name: persona.value.name || '张伟' }, token: state.token })
    messages.value = []
    applyView(view)
    messages.value.push({ role: 'bot', content: view.question, at: new Date().toLocaleTimeString() })
    await scrollDown()
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    busy.value = false
  }
}

async function send(text) {
  const answer = (text ?? input.value).trim()
  if (!answer || busy.value) return
  input.value = ''
  messages.value.push({ role: 'user', content: answer, at: new Date().toLocaleTimeString() })
  busy.value = true
  await scrollDown()
  try {
    const view = await api(`/api/v1/preconsult/${sessionId.value}/answer`, {
      method: 'POST',
      body: { text: answer },
      token: state.token,
    })
    if (view.interrupted) {
      alert.value = view.alert
      handover.value = true
      stage.value = view.stage
      state.pendingAlerts += 1
      messages.value.push({
        role: 'system',
        content: '⚠️ 您描述的症状需要医生尽快关注，我们已通知值班医生，请稍候。',
      })
      toast('已触发红旗告警并通知医生', 'warn')
    } else {
      applyView(view)
      messages.value.push({
        role: 'bot',
        content: view.question,
        at: new Date().toLocaleTimeString(),
        meta: view.quality ? QUALITY[view.quality] : null,
        route: view.route,
      })
      if (view.stage === 'FINISHED') toast('预问诊完成，已生成病历草稿', 'success')
    }
    await scrollDown()
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    busy.value = false
  }
}

async function autoRun(kind = 'normal', delay = 700) {
  if (autoRunning.value) return
  autoRunning.value = true
  if (kind !== 'normal') await start()
  for (const text of script.value[kind] || []) {
    await send(text)
    await new Promise((r) => setTimeout(r, delay))
    if (handover.value) break
  }
  autoRunning.value = false
}
</script>

<template>
  <div class="grid" style="grid-template-columns: minmax(0, 1.35fr) minmax(330px, 0.95fr); align-items: start">
    <div class="card" style="display: flex; flex-direction: column; height: calc(100vh - 132px)">
      <div class="card-head">
        <div class="card-title">
          <span class="badge purple">PreConsult</span> 门诊预问诊
          <span class="card-sub">分阶段采集病史 · 症状异常实时提醒医生</span>
        </div>
        <div class="row" style="gap: 6px">
          <button class="btn sm" :disabled="autoRunning || busy" @click="autoRun('normal')">自动问诊</button>
          <button class="btn sm" :disabled="autoRunning || busy" @click="autoRun('red_flag')">触发红旗</button>
          <button class="btn sm ghost" :disabled="busy" @click="start">重新开始</button>
        </div>
      </div>

      <div style="padding: 12px 16px; border-bottom: 1px solid var(--line)">
        <StageStepper :stages="stages" :current="stage" :handover="handover" />
        <div class="row" style="gap: 10px; margin-top: 10px">
          <div class="progress grow" :class="progress >= 100 ? 'ok' : ''"><span :style="{ width: `${progress}%` }"></span></div>
          <span class="tiny muted mono">{{ progress }}%</span>
        </div>
      </div>

      <div ref="scroller" class="chat-scroll grow">
        <div v-for="(m, i) in messages" :key="i" class="bubble" :class="m.role === 'user' ? 'user' : m.role === 'system' ? 'system' : 'bot'">
          {{ m.content }}
        </div>
        <div v-if="busy" class="bubble bot"><span class="spinner"></span> 正在分析…</div>
      </div>

      <div style="border-top: 1px solid var(--line); padding: 12px 14px">
        <div class="row wrap" style="gap: 6px; margin-bottom: 8px">
          <button
            v-for="text in (script[handover ? 'red_flag' : 'normal'] || []).slice(0, 3)"
            :key="text"
            class="chip"
            :disabled="busy"
            @click="send(text)"
          >
            {{ text.slice(0, 18) }}…
          </button>
        </div>
        <div class="row" style="gap: 8px">
          <input v-model="input" class="input" placeholder="以患者身份回答…" :disabled="handover" @keyup.enter="send()" />
          <button class="btn primary" :disabled="busy || handover || !input.trim()" @click="send()">发送</button>
        </div>
        <div v-if="handover" class="tiny" style="color: var(--danger); margin-top: 6px">
          本次问诊已转交值班医生，请稍候，医生会尽快查看您的情况。
        </div>
      </div>
    </div>

    <div class="stack">
      <div class="card">
        <div class="card-head">
          <div class="card-title">阶段状态</div>
          <span class="badge blue">{{ stageLabel }}</span>
        </div>
        <div class="card-body stack" style="gap: 8px">
          <div v-for="s in stages" :key="s.id" class="row" style="gap: 9px; align-items: flex-start">
            <span
              class="badge"
              :class="stage === s.id ? 'blue' : stages.findIndex((x) => x.id === stage) > stages.findIndex((x) => x.id === s.id) ? 'green' : 'grey'"
              style="min-width: 74px; justify-content: center"
            >
              {{ stage === s.id ? '进行中' : stages.findIndex((x) => x.id === stage) > stages.findIndex((x) => x.id === s.id) ? '已完成' : '待采集' }}
            </span>
            <div class="grow">
              <div style="font-size: 12.5px; font-weight: 600">{{ s.label }}</div>
              <div class="tiny muted">需采集：{{ s.slot_labels.join('、') }}</div>
              <div class="row wrap" style="gap: 4px; margin-top: 5px">
                <span v-for="slot in s.required_slots" :key="slot" class="badge"
                      :class="(filledSlots[s.id] || []).includes(slot) ? 'green' : 'grey'">
                  {{ SLOT_LABELS[slot] || slot }}
                </span>
              </div>
            </div>
          </div>
          <div class="divider"></div>
          <div class="tiny muted">系统会逐项确认以上信息，采集完整后自动生成病历草稿供医生复核。</div>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><div class="card-title">已采集信息</div><span class="badge grey">{{ Object.keys(slotValues).length }} 项</span></div>
        <div class="card-body">
          <div v-if="!Object.keys(slotValues).length" class="empty tiny">尚未采集到信息</div>
          <dl v-else class="kv">
            <template v-for="(v, k) in slotValues" :key="k">
              <dt>{{ SLOT_LABELS[k] || k }}</dt>
              <dd>{{ v === true ? '已确认' : v }}</dd>
            </template>
          </dl>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <div class="card-title">病历草稿</div>
          <span v-if="draft" class="badge teal">完整度 {{ draft.completeness_score }}%</span>
        </div>
        <div class="card-body">
          <div v-if="!draft" class="empty tiny">完成五个阶段后自动生成病历草稿，提交给接诊医生</div>
          <template v-else>
            <dl class="kv">
              <dt>主诉</dt><dd>{{ draft.chief_complaint || '—' }}</dd>
              <dt>现病史</dt><dd>{{ draft.history_of_present_illness || '—' }}</dd>
              <dt>既往史</dt><dd>{{ draft.past_history || '—' }}</dd>
              <dt>用药史</dt><dd>{{ draft.medication_history || '—' }}</dd>
              <dt>过敏史</dt><dd>{{ draft.allergy_history || '—' }}</dd>
            </dl>
            <div class="divider"></div>
            <div class="tiny muted">病历草稿已同步给接诊医生，可直接用于后续质控。</div>
          </template>
        </div>
      </div>
    </div>

    <!-- 红旗告警弹窗 -->
    <Transition name="fade">
      <div v-if="alert" class="overlay" @click.self="alert = null">
        <div class="modal">
          <div class="modal-head">
            <div class="row" style="gap: 8px">
              <span class="badge red">🚑 红旗告警</span>
              <b>命中危急症状，流程已挂起</b>
            </div>
          </div>
          <div class="modal-body stack">
            <div class="evidence" style="border-left-color: var(--danger); background: var(--danger-soft)">
              <b>{{ alert.reason }}</b>
              <div class="stack" style="gap: 6px; margin-top: 8px">
                <div v-for="f in alert.flags" :key="f.name">
                  <b style="color: var(--danger)">{{ f.label }}</b>
                  <div class="tiny">{{ f.advice }}</div>
                </div>
              </div>
            </div>
            <div>
              <b class="tiny muted">患者摘要</b>
              <div class="code" style="margin-top: 4px">{{ alert.patient_summary }}</div>
            </div>
            <div>
              <b class="tiny muted">最近对话（供医生快速判断）</b>
              <div class="stack" style="gap: 5px; margin-top: 6px">
                <div v-for="(t, i) in alert.transcript" :key="i" class="row" style="gap: 8px; align-items: flex-start">
                  <span class="badge" :class="t.role === 'patient' ? 'blue' : 'grey'">{{ t.role === 'patient' ? '患者' : '助手' }}</span>
                  <span class="tiny grow">{{ t.content }}</span>
                </div>
              </div>
            </div>
            <div class="tiny muted">
              可处理方式：{{ (alert.options || []).map((o) => HANDOVER_OPTIONS[o] || o).join(' / ') }}
            </div>
          </div>
          <div class="modal-foot">
            <button class="btn primary" @click="alert = null">我知道了</button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>
