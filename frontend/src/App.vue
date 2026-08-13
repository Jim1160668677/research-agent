<template>
  <div v-if="session.booting" class="boot-screen" role="status">
    <div class="boot-mark">RA</div>
    <div class="boot-line"><span></span></div>
    <p>正在准备科研工作台</p>
  </div>

  <div v-else-if="!session.user" class="gate-wrap">
    <AuthGate />
    <button v-if="session.server === 'offline'" class="retry-service" @click="initializeSession">
      本地服务未连接 · 点击重试
    </button>
  </div>

  <div v-else class="desktop-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-logo">RA</div>
        <div class="brand-text">
          <div class="brand-title">科研智能体</div>
          <div class="brand-sub">Research Agent</div>
        </div>
        <button class="collapse-button" @click="sidebarCollapsed = !sidebarCollapsed" :aria-label="sidebarCollapsed ? '展开导航' : '收起导航'">
          {{ sidebarCollapsed ? '›' : '‹' }}
        </button>
      </div>

      <nav class="nav" aria-label="主导航">
        <p class="nav-section">工作台</p>
        <router-link v-for="item in primaryNav" :key="item.path" :to="item.path" class="nav-item" active-class="active" :title="item.label">
          <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span>
          <span class="nav-label">{{ item.label }}</span>
        </router-link>
        <p class="nav-section tools-section">资源与工具</p>
        <router-link v-for="item in toolsNav" :key="item.path" :to="item.path" class="nav-item" active-class="active" :title="item.label">
          <span class="nav-icon" aria-hidden="true">{{ item.icon }}</span>
          <span class="nav-label">{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <div class="service-status" :class="session.server">
          <span class="status-dot"></span>
          <span class="nav-label">{{ session.server === 'online' ? '本地服务正常' : '服务重连中' }}</span>
        </div>
        <span class="version">v1.2</span>
      </div>
    </aside>

    <section class="main">
      <header class="topbar">
        <div class="topbar-leading">
          <p class="topbar-context">{{ currentSection }}</p>
          <div class="topbar-title">{{ currentTitle }}</div>
        </div>
        <div class="topbar-actions">
          <button class="command-button" @click="openChat" title="快速打开对话">
            <span>搜索或提问</span><kbd>Ctrl K</kbd>
          </button>
          <div class="user-menu">
            <button class="user-trigger" @click="userMenuOpen = !userMenuOpen" :aria-expanded="userMenuOpen">
              <span class="avatar">{{ userInitial }}</span>
              <span class="user-copy"><b>{{ session.user.username }}</b><small>{{ roleLabel }}</small></span>
              <span class="chevron">⌄</span>
            </button>
            <div v-if="userMenuOpen" class="user-popover">
              <div><strong>{{ session.user.username }}</strong><span>{{ session.user.email }}</span></div>
              <router-link to="/llm" @click="userMenuOpen = false">模型与密钥</router-link>
              <button @click="logout">退出登录</button>
            </div>
          </div>
        </div>
      </header>

      <main class="content" @click="userMenuOpen = false">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuthGate from './components/AuthGate.vue'
import { checkHealth, initializeSession, sessionState as session, signOut } from './state/session'

const route = useRoute()
const router = useRouter()
const sidebarCollapsed = ref(false)
const userMenuOpen = ref(false)
let healthTimer

const primaryNav = [
  { path: '/dashboard', label: '概览', icon: '⌂', section: '工作台' },
  { path: '/research', label: '科研工作台', icon: '⌁', section: '工作台' },
  { path: '/chat', label: '智能对话', icon: '◫', section: '工作台' },
  { path: '/workflows', label: '工作流', icon: '⌘', section: '工作台' },
  { path: '/pipelines', label: '生产流程', icon: '▶', section: '工作台' },
]
const toolsNav = computed(() => [
  { path: '/plugins', label: '插件市场', icon: '◇', section: '资源与工具' },
  { path: '/skills', label: '技能库', icon: '✦', section: '资源与工具' },
  { path: '/ncbi', label: 'NCBI 数据', icon: '◎', section: '资源与工具' },
  { path: '/llm', label: '模型设置', icon: '⚙', section: '系统' },
  ...(session.user?.role === 'admin'
    ? [{ path: '/security', label: '数据安全', icon: '◆', section: '系统' }]
    : []),
])
const navItems = computed(() => [...primaryNav, ...toolsNav.value])
const currentItem = computed(() => navItems.value.find(item => route.path.startsWith(item.path)))
const currentTitle = computed(() => currentItem.value?.label || '科研智能体')
const currentSection = computed(() => currentItem.value?.section || 'Research Agent')
const userInitial = computed(() => (session.user?.username || 'R').slice(0, 1).toUpperCase())
const roleLabel = computed(() => session.user?.role === 'admin' ? '管理员' : '研究员')

async function openChat() {
  await router.push('/chat')
  await nextTick()
  window.dispatchEvent(new CustomEvent('research-agent:focus-composer'))
}

async function logout() {
  userMenuOpen.value = false
  await signOut()
}

function handleShortcut(event) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    openChat()
  }
}

onMounted(async () => {
  await initializeSession()
  await checkHealth()
  healthTimer = window.setInterval(checkHealth, 20_000)
  window.addEventListener('keydown', handleShortcut)
})

onBeforeUnmount(() => {
  window.clearInterval(healthTimer)
  window.removeEventListener('keydown', handleShortcut)
})
</script>

<style>
:root { color-scheme: light; font-family: Inter, "Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif; color: #172033; background: #f5f7fb; font-synthesis: none; }
* { box-sizing: border-box; }
html, body, #app { width: 100%; height: 100%; margin: 0; }
body { overflow: hidden; -webkit-font-smoothing: antialiased; }
button, input, textarea, select { font: inherit; }
button, a { -webkit-tap-highlight-color: transparent; }
button:focus-visible, a:focus-visible, input:focus-visible, textarea:focus-visible, select:focus-visible { outline: 3px solid rgba(37,99,235,.2); outline-offset: 2px; }
.boot-screen { height: 100%; display: grid; place-content: center; justify-items: center; gap: 18px; color: #64748b; background: #f8fafc; }
.boot-mark { width: 58px; height: 58px; display: grid; place-items: center; border-radius: 16px; color: white; background: linear-gradient(145deg, #2563eb, #0891b2); font-weight: 800; box-shadow: 0 15px 40px rgba(37,99,235,.2); }
.boot-screen p { margin: 0; font-size: 13px; }
.boot-line { width: 130px; height: 3px; overflow: hidden; border-radius: 3px; background: #e2e8f0; }
.boot-line span { display: block; width: 45%; height: 100%; background: #2563eb; animation: boot 1.1s ease-in-out infinite alternate; }
@keyframes boot { from { transform: translateX(-20%); } to { transform: translateX(145%); } }
.gate-wrap { height: 100%; position: relative; overflow: auto; }
.retry-service { position: fixed; right: 18px; bottom: 18px; z-index: 10; border: 1px solid #fecaca; border-radius: 10px; padding: 10px 14px; color: #991b1b; background: #fff; box-shadow: 0 8px 25px rgba(15,23,42,.1); cursor: pointer; }
.desktop-shell { display: flex; width: 100%; height: 100%; background: #f5f7fb; }
.sidebar { position: relative; z-index: 5; width: 232px; display: flex; flex-direction: column; flex: 0 0 auto; color: #cbd5e1; background: #0b1627; border-right: 1px solid rgba(148,163,184,.1); transition: width .18s ease; }
.brand { height: 76px; display: flex; align-items: center; gap: 11px; padding: 0 16px; border-bottom: 1px solid rgba(148,163,184,.1); }
.brand-logo { width: 39px; height: 39px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 11px; color: white; background: linear-gradient(145deg, #2563eb, #0891b2); font-size: 13px; font-weight: 800; box-shadow: 0 8px 24px rgba(37,99,235,.25); }
.brand-text { min-width: 0; }
.brand-title { color: #f8fafc; font-size: 14px; font-weight: 700; white-space: nowrap; }
.brand-sub { margin-top: 2px; color: #64748b; font-size: 10px; letter-spacing: .04em; white-space: nowrap; }
.collapse-button { width: 25px; height: 25px; margin-left: auto; border: 1px solid rgba(148,163,184,.16); border-radius: 7px; color: #94a3b8; background: rgba(255,255,255,.03); cursor: pointer; }
.nav { flex: 1; overflow-y: auto; padding: 17px 11px; }
.nav-section { margin: 0 10px 8px; color: #53637a; font-size: 10px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; white-space: nowrap; }
.tools-section { margin-top: 24px; }
.nav-item { height: 41px; display: flex; align-items: center; gap: 12px; margin-bottom: 3px; padding: 0 11px; border-radius: 8px; color: #9aabc0; text-decoration: none; font-size: 13px; font-weight: 560; transition: color .15s, background .15s; }
.nav-item:hover { color: #f1f5f9; background: rgba(148,163,184,.08); }
.nav-item.active { color: #e0f2fe; background: linear-gradient(90deg, rgba(37,99,235,.29), rgba(37,99,235,.1)); box-shadow: inset 2px 0 #3b82f6; }
.nav-icon { width: 20px; flex: 0 0 auto; text-align: center; color: #7f98b7; font-size: 16px; }
.nav-item.active .nav-icon { color: #60a5fa; }
.sidebar-footer { min-height: 57px; display: flex; align-items: center; gap: 8px; padding: 0 18px; border-top: 1px solid rgba(148,163,184,.1); color: #71839a; font-size: 11px; }
.service-status { min-width: 0; display: flex; align-items: center; gap: 8px; }
.status-dot { width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%; background: #f59e0b; box-shadow: 0 0 0 3px rgba(245,158,11,.1); }
.service-status.online .status-dot { background: #34d399; box-shadow: 0 0 0 3px rgba(52,211,153,.1); }
.version { margin-left: auto; color: #53637a; }
.sidebar-collapsed .sidebar { width: 72px; }
.sidebar-collapsed .brand { padding: 0 16px; }
.sidebar-collapsed .brand-text, .sidebar-collapsed .nav-label, .sidebar-collapsed .nav-section, .sidebar-collapsed .version { display: none; }
.sidebar-collapsed .collapse-button { position: absolute; right: -12px; top: 26px; background: #122036; }
.sidebar-collapsed .nav-item { justify-content: center; padding: 0; }
.sidebar-collapsed .sidebar-footer { justify-content: center; padding: 0; }
.main { min-width: 0; flex: 1; display: flex; flex-direction: column; }
.topbar { height: 76px; flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; padding: 0 25px 0 28px; border-bottom: 1px solid #e2e8f0; background: rgba(255,255,255,.92); backdrop-filter: blur(15px); }
.topbar-context { margin: 0 0 3px; color: #94a3b8; font-size: 10px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
.topbar-title { color: #0f172a; font-size: 17px; font-weight: 720; letter-spacing: -.015em; }
.topbar-actions { display: flex; align-items: center; gap: 13px; }
.command-button { width: 190px; height: 35px; display: flex; align-items: center; justify-content: space-between; border: 1px solid #dbe2ea; border-radius: 9px; padding: 0 8px 0 12px; color: #94a3b8; background: #f8fafc; cursor: pointer; font-size: 12px; }
.command-button:hover { border-color: #bfdbfe; background: #fff; }
kbd { border: 1px solid #dbe2ea; border-bottom-width: 2px; border-radius: 5px; padding: 2px 6px; color: #64748b; background: #fff; font: 600 10px/1.35 ui-monospace, monospace; }
.user-menu { position: relative; }
.user-trigger { height: 43px; display: flex; align-items: center; gap: 9px; border: 0; padding: 4px 7px; border-radius: 9px; color: #334155; background: transparent; cursor: pointer; text-align: left; }
.user-trigger:hover { background: #f1f5f9; }
.avatar { width: 33px; height: 33px; display: grid; place-items: center; border-radius: 9px; color: #1d4ed8; background: #dbeafe; font-size: 12px; font-weight: 800; }
.user-copy { display: grid; gap: 1px; min-width: 72px; }
.user-copy b { font-size: 12px; }
.user-copy small { color: #94a3b8; font-size: 10px; }
.chevron { color: #94a3b8; font-size: 12px; }
.user-popover { position: absolute; right: 0; top: 50px; z-index: 20; width: 210px; overflow: hidden; border: 1px solid #e2e8f0; border-radius: 11px; background: white; box-shadow: 0 18px 45px rgba(15,23,42,.14); }
.user-popover > div { display: grid; gap: 3px; padding: 14px; border-bottom: 1px solid #edf2f7; }
.user-popover strong { color: #0f172a; font-size: 13px; }
.user-popover span { overflow: hidden; color: #94a3b8; font-size: 11px; text-overflow: ellipsis; }
.user-popover a, .user-popover button { width: 100%; display: block; border: 0; padding: 10px 14px; color: #475569; background: white; text-align: left; text-decoration: none; font-size: 12px; cursor: pointer; }
.user-popover a:hover, .user-popover button:hover { background: #f8fafc; color: #1d4ed8; }
.content { flex: 1; min-height: 0; overflow: auto; padding: 25px 28px 34px; }
.page-enter-active, .page-leave-active { transition: opacity .14s ease, transform .14s ease; }
.page-enter-from { opacity: 0; transform: translateY(3px); }
.page-leave-to { opacity: 0; }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { border: 3px solid transparent; border-radius: 10px; background: #cbd5e1; background-clip: padding-box; }
@media (max-width: 860px) { .sidebar { width: 72px; } .brand-text, .nav-label, .nav-section, .version, .collapse-button { display: none; } .nav-item { justify-content: center; padding: 0; } .sidebar-footer { justify-content: center; padding: 0; } .command-button { width: 42px; justify-content: center; } .command-button span { display: none; } .user-copy { display: none; } .content { padding: 20px; } }
</style>
