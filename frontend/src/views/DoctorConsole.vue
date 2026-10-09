<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, stream } from '../api'
import { state, toast } from '../store'
import StatCard from '../components/StatCard.vue'

const question = ref('')
const messages = ref([])
const chips = ref([])
const streaming = ref(false)
const tab = ref('evidence')
const sessionId = ref(`sess_doctor_${Math.random().toString(36).slice(2, 10)}`)
const controller = ref(null)
const health = ref(null)

const link = reactive({
  route: null,
  citations: [],
  done: null,
})

const lastAnswer = computed(() => [...messages.value].reverse().find((m) => m.role === 'assistant'))

onMounted(async () => {
  try {
    const res = await api('/api/v1/library/questions')
    chips.value = res.items
  } catch {
    chips.value = []
  }
  try {
    health.value = await api('/api/v1/health')
  } catch {
    health.value = null
  }
})

function resetLink() {
  link.route = null
  link.citations = []
  link.done = null
}

async function send(text) {
  const query = (text ?? question.value).trim()
  if (!query || streaming.value) return
  question.value = ''
  resetLink()
  messages.value.push({ role: 'user', content: query, at: new Date().toLocaleTimeString() })
  const bot = reactive({ role: 'assistant', content: '', at: new Date().toLocaleTimeString(), streaming: true, citations: [], route: null, fallback: false, error: '' })
  messages.value.push(bot)
  streaming.value = true

  const push = () => {
    messages.value = [...messages.value]
  }

  try {
    controller.value = new AbortController()
    await stream(
      '/api/v1/chat/stream',
      { query, session_id: sessionId.value },
      state.token,
      ({ event, data }) => {
        if (event === 'route') {
          link.route = data
          bot.route = data
          if (data.chips?.length) chips.value = data.chips.map((q) => ({ query: q, hint: '推荐追问' }))
        } else if (event === 'node') {
          /* 处理环节仅内部使用，不对外展示 */
        } else if (event === 'tool_call') {
          /* 工具调用仅内部使用，不对外展示 */
        } else if (event === 'citation') {
          link.citations.push(data)
          bot.citations = [...link.citations]
        } else if (event === 'interrupt') {
          bot.content += `\n\n⚠️ 已触发红旗告警：${(data.flags || []).map((f) => f.label).join('、')}`
        } else if (event === 'delta') {
          bot.content += data.text || ''
        } else if (event === 'error') {
          bot.error = data.message
          bot.content += `\n\n[错误] ${data.message}`
        } else if (event === 'done') {
          link.done = data
          bot.fallback = data.fallback_used
          if (data.content) bot.content = data.content
          if (data.citations?.length) {
            link.citations = data.citations
            bot.citations = data.citations
          }
        }
        push()
      },
      controller.value.signal,
    )
  } catch (err) {
    if (err.name !== 'AbortError') {
      bot.error = err.message
      toast(`请求失败：${err.message}`, 'error')
    }
  } finally {
    bot.streaming = false
    streaming.value = false
    push()
  }
}

function stop() {
  controller.value?.abort()
  streaming.value = false
}
</script>

<template>
  <div class="grid" style="grid-template-columns: minmax(0, 1.5fr) minmax(350px, 0.92fr); align-items: start">
    <!-- 对话区 -->
    <div class="card" style="display: flex; flex-direction: column; height: calc(100vh - 132px)">
      <div class="card-head">
        <div class="card-title">
          <span class="badge blue">MedQA</span> 医学知识问答
          <span class="card-sub">基于院内知识库作答 · 每条结论附出处 · 依据不足时不作判断</span>
        </div>
        <div class="row" style="gap: 6px">
          <span class="badge grey mono">会话号 {{ sessionId.slice(-8) }}</span>
          <button class="btn sm ghost" :disabled="streaming" @click="messages = []; resetLink()">清空</button>
        </div>
      </div>

      <div class="chat-scroll grow">
        <div v-if="!messages.length" class="empty" style="margin: auto">
          <span class="icon">🩺</span>
          <div style="font-weight: 650; color: var(--ink-2); margin-bottom: 6px">向知识库提问</div>
          <div>答案中的每条结论都会带出指南名称、章节与页码，便于逐条核对。</div>
          <div class="row wrap" style="justify-content: center; gap: 8px; margin-top: 16px; max-width: 560px">
            <button v-for="c in chips" :key="c.query" class="chip" @click="send(c.query)">{{ c.query }}</button>
          </div>
        </div>

        <template v-for="(m, i) in messages" :key="i">
          <div class="bubble" :class="m.role === 'user' ? 'user' : 'bot'">
            <template v-if="m.role === 'assistant'">
              <div v-if="m.streaming" class="row wrap" style="gap: 6px; margin-bottom: 6px">
                <span class="badge grey"><span class="spinner"></span> 正在整理</span>
              </div>
              <div>{{ m.content }}<span v-if="m.streaming" class="pulse">▍</span></div>
              <div v-if="m.citations?.length" class="stack" style="margin-top: 10px; gap: 6px">
                <div v-for="c in m.citations" :key="c.index" class="citation">
                  <div class="src">[{{ c.index }}] 《{{ c.source }}》</div>
                  <div class="tiny muted">{{ c.chapter }} · {{ c.section || '' }} · 第 {{ c.page }} 页</div>
                  <div class="snip">{{ c.snippet }}</div>
                </div>
              </div>
              <div class="bubble-meta">
                <span>{{ m.at }}</span>
              </div>
            </template>
            <template v-else>{{ m.content }}</template>
          </div>
        </template>
      </div>

      <div style="border-top: 1px solid var(--line); padding: 12px 14px">
        <div class="row wrap" style="gap: 6px; margin-bottom: 8px">
          <button v-for="c in chips.slice(0, 4)" :key="c.query" class="chip" :disabled="streaming" @click="send(c.query)">
            {{ c.query }}
          </button>
        </div>
        <div class="row" style="gap: 8px">
          <input
            v-model="question"
            class="input"
            placeholder="输入医学问题，例如：二甲双胍的禁忌症有哪些？"
            @keyup.enter="send()"
          />
          <button class="btn primary" :disabled="streaming || !question.trim()" @click="send()">发送</button>
          <button v-if="streaming" class="btn danger" @click="stop">停止</button>
        </div>
      </div>
    </div>

    <!-- 侧栏：回答依据与知识库 -->
    <div class="stack">
      <div class="grid grid-2">
        <StatCard label="引用文献" :value="link.citations.length || '—'" foot="每条结论均可追溯" />
        <StatCard
          label="参考条目"
          :value="(link.done?.structured?.docs || []).length || '—'"
          tone="teal"
          foot="来自院内知识库"
        />
      </div>

      <div class="card">
        <div class="tabs">
          <div class="tab" :class="{ active: tab === 'evidence' }" @click="tab = 'evidence'">回答依据</div>
          <div class="tab" :class="{ active: tab === 'kb' }" @click="tab = 'kb'">知识库概况</div>
        </div>

        <div v-if="tab === 'evidence'" class="card-body" style="max-height: 460px; overflow-y: auto">
          <div class="stack" style="gap: 8px">
            <div v-for="(d, i) in link.done?.structured?.docs || []" :key="d.chunk_id || i" class="stack" style="gap: 4px">
              <div class="row-between">
                <span style="font-size: 12.5px; font-weight: 600">《{{ d.source }}》</span>
              </div>
              <div class="tiny muted">{{ d.chapter }} · {{ d.section }} · 第 {{ d.page }} 页</div>
              <div class="tiny" style="color: var(--ink-2); line-height: 1.65">{{ d.text }}</div>
            </div>
            <div v-if="!(link.done?.structured?.docs || []).length" class="empty">
              <span class="icon">📚</span>提问后，这里会列出本次回答所依据的知识条目
            </div>
          </div>
        </div>

        <div v-else class="card-body">
          <dl class="kv">
            <dt>收录文献</dt><dd class="mono">{{ health?.kb?.documents ?? '—' }}</dd>
            <dt>知识条目</dt><dd class="mono">{{ health?.kb?.chunks ?? '—' }}</dd>
            <dt>覆盖科室</dt><dd>{{ (health?.kb?.departments || []).join('、') || '—' }}</dd>
          </dl>
          <div class="divider"></div>
          <div class="tiny muted">{{ health?.kb?.notice || '' }}</div>
        </div>
      </div>
    </div>
  </div>
</template>
