<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { ROLE_HOME, setAuth, state, toast } from '../store'

const router = useRouter()
const roles = ref([
  { role: 'doctor', icon: '🩺', label: '临床医生', desc: '知识问答 · 高危患者接管', color: '#1a6fd4' },
  { role: 'qc_staff', icon: '📋', label: '质控科医师', desc: '病历内涵质控 · 诊疗联动', color: '#0d9b8a' },
  { role: 'patient', icon: '🧑', label: '患者', desc: '挂号前预问诊采集', color: '#6941c6' },
  { role: 'admin', icon: '📊', label: '系统管理员', desc: '运行指标 / 质量评测', color: '#c77700' },
])
const tenants = ref([])
const tenantId = ref('tnt_renhe')
const loading = ref('')
const backend = ref(null)

onMounted(async () => {
  try {
    backend.value = await api('/api/v1/health')
    const res = await api('/api/v1/auth/tenants')
    tenants.value = res.items || []
  } catch (err) {
    backend.value = null
  }
})

async function login(role) {
  loading.value = role
  try {
    const res = await api('/api/v1/auth/login', { method: 'POST', body: { role, tenant_id: tenantId.value } })
    const tenant = tenants.value.find((t) => t.tenant_id === tenantId.value)
    setAuth(res.token, res.user, tenant?.name)
    toast(`已进入「${res.user.title}」视图`, 'success')
    router.push(ROLE_HOME[role] || '/doctor')
  } catch (err) {
    toast(`登录失败：${err.message}`, 'error')
  } finally {
    loading.value = ''
  }
}
</script>

<template>
  <div
    style="
      height: 100%;
      display: grid;
      place-items: center;
      background: radial-gradient(1200px 500px at 20% -10%, #17365f 0%, #0d1a2b 55%, #08111d 100%);
      padding: 24px;
    "
  >
    <div style="width: min(1000px, 100%)">
      <div class="row" style="gap: 14px; margin-bottom: 22px">
        <div class="brand-mark" style="width: 46px; height: 46px; font-size: 19px">MA</div>
        <div>
          <h1 style="color: #fff; font-size: 22px">MediAgent 智能诊疗协作平台</h1>
          <div style="color: #8ea3bd; font-size: 13px; margin-top: 3px">
            医学知识问答 · 病历内涵质控 · 门诊预问诊 —— 一站式智能诊疗协作平台
          </div>
        </div>
      </div>

      <div class="card" style="background: rgba(255, 255, 255, 0.97)">
        <div class="card-head">
          <div class="card-title">选择登录身份 <span class="card-sub">一键登录，支持对接院内统一身份认证（SSO）</span></div>
          <span v-if="backend" class="badge green"><span class="dot"></span>服务在线 · {{ backend.llm_provider === 'local' ? '私有化模型' : backend.llm_provider }}</span>
          <span v-else class="badge red"><span class="dot"></span>服务未连接</span>
        </div>
        <div class="card-body">
          <div class="field" style="max-width: 320px; margin-bottom: 14px">
            <label>选择院区</label>
            <select v-model="tenantId" class="select">
              <option v-for="t in tenants" :key="t.tenant_id" :value="t.tenant_id">
                {{ t.name }}（{{ t.hospital_level }}）
              </option>
              <option v-if="!tenants.length" value="tnt_renhe">仁和医院</option>
            </select>
          </div>

          <div class="grid grid-4">
            <button
              v-for="r in roles"
              :key="r.role"
              class="card"
              style="text-align: left; padding: 15px; cursor: pointer; border-color: var(--line)"
              :disabled="!!loading"
              @click="login(r.role)"
            >
              <div style="font-size: 22px">{{ r.icon }}</div>
              <div style="font-weight: 700; margin-top: 6px">
                {{ r.label }}
                <span v-if="loading === r.role" class="spinner" style="margin-left: 6px"></span>
              </div>
              <div class="tiny muted" style="margin-top: 4px; line-height: 1.5">{{ r.desc }}</div>
              <div class="badge" :style="{ background: `${r.color}18`, color: r.color, marginTop: '10px' }">
                进入 →
              </div>
            </button>
          </div>

          <div class="divider"></div>
          <div class="row wrap" style="gap: 20px; font-size: 11.5px; color: var(--ink-3)">
            <span>院内知识库覆盖 <b class="mono">{{ backend?.kb?.departments?.length || 8 }}</b> 个临床科室</span>
            <span>每条结论<b>标注出处</b>，可追溯到章节与页码</span>
            <span>质控问题可<b>逐条采纳 / 驳回</b>，全程留痕</span>
            <span>风险症状<b>实时提醒</b>，医生一键接管</span>
          </div>
        </div>
      </div>

      <div class="tiny" style="color: #6d839e; margin-top: 14px; text-align: center">
        本系统由院内审核知识库与私有化部署模型提供支持，医学内容仅供临床参考，最终诊疗决策以最新权威指南及院内规范为准。
      </div>
    </div>
  </div>
</template>
