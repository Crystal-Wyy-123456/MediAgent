import { reactive, watch } from 'vue'

const STORAGE_KEY = 'mediagent.auth'

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

const saved = load()

export const state = reactive({
  token: saved?.token || '',
  user: saved?.user || null,
  tenantName: saved?.tenantName || '仁和医院',
  toasts: [],
  // 会话上下文：预问诊与质控分别维护，方便跨页面联调
  preconsult: { sessionId: '', patientId: '', stage: '', draft: null },
  lastReviewId: '',
  pendingAlerts: 0,
})

watch(
  () => [state.token, state.user, state.tenantName],
  () => {
    if (!state.token) {
      localStorage.removeItem(STORAGE_KEY)
      return
    }
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ token: state.token, user: state.user, tenantName: state.tenantName }),
    )
  },
)

export function setAuth(token, user, tenantName) {
  state.token = token
  state.user = user
  if (tenantName) state.tenantName = tenantName
}

export function logout() {
  state.token = ''
  state.user = null
}

let toastSeq = 0
export function toast(message, type = 'info', timeout = 3600) {
  const id = ++toastSeq
  state.toasts.push({ id, message, type })
  setTimeout(() => dismissToast(id), timeout)
  return id
}

export function dismissToast(id) {
  const index = state.toasts.findIndex((t) => t.id === id)
  if (index >= 0) state.toasts.splice(index, 1)
}

export const ROLE_LABELS = {
  doctor: '临床医生',
  qc_staff: '质控科医师',
  patient: '患者',
  admin: '系统管理员',
}

// 每个角色登录后进入的首页，同时用于越权访问时的回退
export const ROLE_HOME = {
  doctor: '/doctor',
  qc_staff: '/qc',
  patient: '/preconsult',
  admin: '/admin',
}
