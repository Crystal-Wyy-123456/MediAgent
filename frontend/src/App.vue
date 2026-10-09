<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { state, logout, ROLE_LABELS } from './store'
import { api } from './api'
import ToastHost from './components/ToastHost.vue'

const route = useRoute()
const router = useRouter()
const health = ref(null)

// 每个角色只看到自己业务范围内的入口
const NAV_GROUPS = [
  { group: '临床端', roles: ['doctor'], items: [
    { name: 'doctor', path: '/doctor', label: '医生工作站', icon: '🩺' },
    { name: 'handover', path: '/handover', label: '医生接管', icon: '🚑', badge: 'alerts' },
  ] },
  { group: '患者端', roles: ['patient'], items: [
    { name: 'preconsult', path: '/preconsult', label: '在线预问诊', icon: '💬' },
  ] },
  { group: '质控端', roles: ['qc_staff'], items: [
    { name: 'qc', path: '/qc', label: '病历质控', icon: '📋' },
    { name: 'pipeline', path: '/pipeline', label: '诊疗联动', icon: '🔗' },
  ] },
  { group: '管理端', roles: ['admin'], items: [
    { name: 'admin', path: '/admin', label: '运营管理', icon: '📊' },
  ] },
]

const showShell = computed(() => route.name !== 'login')
const pageTitle = computed(() => route.meta.title || 'MediAgent')
const initials = computed(() => (state.user?.name || '医').slice(0, 1))
const userRole = computed(() => state.user?.role || '')
const navItems = computed(() => NAV_GROUPS.filter((g) => g.roles.includes(userRole.value)))
const isPatient = computed(() => userRole.value === 'patient')

async function refreshAlerts() {
  if (!state.token || userRole.value !== 'doctor') return
  try {
    const res = await api('/api/v1/preconsult/alerts/pending', { token: state.token })
    state.pendingAlerts = res.total || 0
  } catch {
    /* 静默 */
  }
}

// 院区名称一律以服务端为准，避免本地缓存里残留旧名称或编码异常
async function syncTenantName() {
  const tenantId = state.user?.tenant_id
  if (!tenantId) return
  try {
    const res = await api('/api/v1/auth/tenants')
    const hit = (res.items || []).find((t) => t.tenant_id === tenantId)
    if (hit?.name) state.tenantName = hit.name
  } catch {
    /* 静默 */
  }
}

onMounted(async () => {
  try {
    health.value = await api('/api/v1/health')
  } catch {
    /* 后端未启动时不影响登录页 */
  }
  await syncTenantName()
  refreshAlerts()
  setInterval(refreshAlerts, 15000)
})

function doLogout() {
  logout()
  router.push('/login')
}
</script>

<template>
  <div v-if="showShell" class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">MA</div>
        <div>
          <div class="brand-name">MediAgent</div>
          <div class="brand-sub">智能诊疗协作平台</div>
        </div>
      </div>

      <template v-for="group in navItems" :key="group.group">
        <div class="nav-label">{{ group.group }}</div>
        <router-link
          v-for="item in group.items"
          :key="item.name"
          :to="item.path"
          class="nav-item"
          :class="{ active: route.name === item.name }"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
          <span v-if="item.badge === 'alerts' && state.pendingAlerts" class="nav-badge">{{ state.pendingAlerts }}</span>
        </router-link>
      </template>

      <div class="sidebar-foot">
        <div class="row-between">
          <span>{{ state.tenantName }}</span>
          <span class="dot" :class="health ? 'ok' : ''" :style="{ color: health ? '#12b76a' : '#f04438' }"></span>
        </div>
        <div v-if="!isPatient" style="margin-top: 4px">{{ health ? '系统运行正常' : '服务未连接' }}</div>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div>
          <h1>{{ pageTitle }}</h1>
          <div class="crumb">MediAgent / {{ pageTitle }}</div>
        </div>
        <div class="grow"></div>
        <span class="badge blue">{{ state.user?.title || '待登录' }}</span>
        <div class="row" style="gap: 8px">
          <div class="avatar">{{ initials }}</div>
          <div style="line-height: 1.25">
            <div style="font-size: 12.5px; font-weight: 600">{{ state.user?.name || '未登录' }}</div>
            <div class="tiny muted">{{ ROLE_LABELS[state.user?.role] || '未登录' }}</div>
          </div>
        </div>
        <button class="btn sm ghost" @click="doLogout">退出</button>
      </header>

      <main class="content">
        <router-view />
      </main>
    </div>
  </div>

  <router-view v-else />
  <ToastHost />
</template>
