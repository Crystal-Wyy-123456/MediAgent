import { createRouter, createWebHistory } from 'vue-router'
import { ROLE_HOME, state } from './store'

const routes = [
  { path: '/', redirect: () => ROLE_HOME[state.user?.role] || '/login' },
  { path: '/login', name: 'login', component: () => import('./views/LoginView.vue'), meta: { public: true } },
  { path: '/doctor', name: 'doctor', component: () => import('./views/DoctorConsole.vue'), meta: { title: '医生工作站', roles: ['doctor'] } },
  { path: '/handover', name: 'handover', component: () => import('./views/HandoverConsole.vue'), meta: { title: '医生接管', roles: ['doctor'] } },
  { path: '/preconsult', name: 'preconsult', component: () => import('./views/PatientPreconsult.vue'), meta: { title: '在线预问诊', roles: ['patient'] } },
  { path: '/qc', name: 'qc', component: () => import('./views/QcDashboard.vue'), meta: { title: '病历质控', roles: ['qc_staff'] } },
  { path: '/pipeline', name: 'pipeline', component: () => import('./views/PipelineView.vue'), meta: { title: '诊疗联动', roles: ['qc_staff'] } },
  { path: '/admin', name: 'admin', component: () => import('./views/AdminConsole.vue'), meta: { title: '运营管理', roles: ['admin'] } },
  { path: '/:pathMatch(.*)*', redirect: () => ROLE_HOME[state.user?.role] || '/login' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

// 未登录 → 登录页；已登录但访问了不属于自己角色的页面 → 回到本角色首页
router.beforeEach((to) => {
  if (to.meta.public) return true
  const role = state.user?.role
  if (!state.token || !role) return { name: 'login' }
  const allowed = to.meta.roles
  if (allowed && !allowed.includes(role)) return ROLE_HOME[role] || { name: 'login' }
  return true
})

export default router
