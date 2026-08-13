<template>
  <div class="dashboard-page">
    <section class="welcome-banner">
      <div>
        <p class="eyebrow">RESEARCH WORKSPACE</p>
        <h1>{{ greeting }}，{{ session.user?.username }}</h1>
        <p>从一个问题开始，让智能体帮你连接证据、数据和分析工具。</p>
        <div class="banner-actions">
          <router-link to="/research" class="primary-link">开始科研任务 <span>→</span></router-link>
          <router-link to="/workflows/new" class="secondary-link">创建工作流</router-link>
        </div>
      </div>
      <div class="orbit" aria-hidden="true"><i></i><i></i><i></i><b>RA</b></div>
    </section>

    <div v-if="error" class="error-banner" role="alert">
      <span>{{ error }}</span><button @click="loadOverview">重新加载</button>
    </div>

    <section class="metrics" aria-label="工作台统计">
      <article v-for="metric in metrics" :key="metric.label" class="metric-card">
        <div class="metric-icon" :class="metric.tone">{{ metric.icon }}</div>
        <div><strong>{{ loading ? '—' : metric.value }}</strong><span>{{ metric.label }}</span></div>
        <small>{{ metric.hint }}</small>
      </article>
    </section>

    <section class="dashboard-grid">
      <article class="panel activity-panel">
        <header class="panel-heading">
          <div><p>RECENT ACTIVITY</p><h2>最近活动</h2></div>
          <button @click="loadOverview">刷新</button>
        </header>
        <div v-if="loading" class="activity-loading"><i v-for="n in 4" :key="n"></i></div>
        <div v-else-if="activities.length === 0" class="empty-activity">
          <span>⌁</span><b>还没有活动记录</b><p>开始一次对话或运行工作流后，进度会出现在这里。</p>
        </div>
        <div v-else class="activity-list">
          <router-link v-for="(activity, index) in activities" :key="`${activity.type}-${index}`" :to="activity.target" class="activity-row">
            <span class="activity-symbol" :class="activity.type">{{ activity.type === 'workflow' ? '⌘' : activity.type === 'research' ? '⌁' : '◫' }}</span>
            <span class="activity-copy"><b>{{ activity.title }}</b><small>{{ activity.type === 'workflow' ? '工作流运行' : activity.type === 'research' ? '科研任务' : '智能对话' }} · {{ relativeTime(activity.time) }}</small></span>
            <span class="activity-status" :class="activity.status">{{ statusLabel(activity.status) }}</span>
            <i>›</i>
          </router-link>
        </div>
      </article>

      <aside class="right-column">
        <article class="panel readiness-panel">
          <header class="panel-heading compact"><div><p>GET STARTED</p><h2>工作台就绪度</h2></div><span>{{ readiness }}%</span></header>
          <div class="progress"><i :style="{ width: `${readiness}%` }"></i></div>
          <router-link to="/llm" class="check-row" :class="{ done: overview.models.configured > 0 }">
            <span>{{ overview.models.configured > 0 ? '✓' : '1' }}</span><div><b>配置 AI 模型</b><small>{{ overview.models.configured ? `已连接 ${overview.models.configured} 个提供商` : '启用完整智能回答' }}</small></div><i>›</i>
          </router-link>
          <router-link to="/plugins" class="check-row" :class="{ done: overview.counts.installed_plugins > 0 }">
            <span>{{ overview.counts.installed_plugins > 0 ? '✓' : '2' }}</span><div><b>安装研究工具</b><small>{{ overview.counts.installed_plugins ? `已安装 ${overview.counts.installed_plugins} 个工具` : '扩展本地分析能力' }}</small></div><i>›</i>
          </router-link>
          <router-link to="/chat" class="check-row" :class="{ done: overview.counts.conversations > 0 }">
            <span>{{ overview.counts.conversations > 0 ? '✓' : '3' }}</span><div><b>完成首次对话</b><small>验证你的研究工作流</small></div><i>›</i>
          </router-link>
        </article>

        <article class="panel quick-panel">
          <header class="panel-heading compact"><div><p>QUICK ACCESS</p><h2>快速入口</h2></div></header>
          <div class="quick-grid">
            <router-link to="/research"><span>⌁</span><b>科研工作台</b><small>计划与证据链</small></router-link>
            <router-link to="/ncbi"><span>◎</span><b>NCBI 查询</b><small>文献与序列</small></router-link>
            <router-link to="/skills"><span>✦</span><b>技能库</b><small>{{ overview.counts.skills }} 项能力</small></router-link>
          </div>
        </article>
      </aside>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { apiError, sessionState as session } from '../state/session'

const loading = ref(true)
const error = ref('')
const overview = reactive({
  counts: { conversations: 0, installed_plugins: 0, workflows: 0, skills: 0, research_runs: 0 },
  models: { configured: 0, total: 3 },
  activities: [],
})
const greeting = computed(() => {
  const hour = new Date().getHours()
  return hour < 11 ? '早上好' : hour < 18 ? '下午好' : '晚上好'
})
const activities = computed(() => overview.activities || [])
const metrics = computed(() => [
  { label: '科研任务', value: overview.counts.research_runs, hint: '可审计研究运行', icon: '⌁', tone: 'green' },
  { label: '科研对话', value: overview.counts.conversations, hint: '已持久化会话', icon: '◫', tone: 'blue' },
  { label: '工作流', value: overview.counts.workflows, hint: '个人自动化流程', icon: '⌘', tone: 'violet' },
  { label: '已装工具', value: overview.counts.installed_plugins, hint: '当前账户可用', icon: '◇', tone: 'cyan' },
  { label: '可用技能', value: overview.counts.skills, hint: '内置标准化能力', icon: '✦', tone: 'amber' },
])
const readiness = computed(() => [
  overview.models.configured > 0,
  overview.counts.installed_plugins > 0,
  overview.counts.conversations > 0,
].filter(Boolean).length * 33 + (overview.counts.conversations > 0 ? 1 : 0))

async function loadOverview() {
  loading.value = true
  error.value = ''
  try {
    const response = await axios.get('/api/v1/system/overview')
    Object.assign(overview.counts, response.data.counts)
    Object.assign(overview.models, response.data.models)
    overview.activities = response.data.activities || []
  } catch (err) {
    error.value = apiError(err, '概览数据加载失败')
  } finally {
    loading.value = false
  }
}

function relativeTime(value) {
  if (!value) return '刚刚'
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000))
  if (seconds < 60) return '刚刚'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  return `${Math.floor(seconds / 86400)} 天前`
}
function statusLabel(status) { return ({ completed: '已完成', failed: '失败', running: '运行中', cancelled: '已取消' }[status] || '已记录') }

onMounted(loadOverview)
</script>

<style scoped>
.dashboard-page { max-width: 1260px; margin: 0 auto; }
.welcome-banner { position: relative; min-height: 205px; display: flex; align-items: center; justify-content: space-between; overflow: hidden; border-radius: 15px; padding: 31px 42px; color: #dbeafe; background: radial-gradient(circle at 78% 15%, rgba(56,189,248,.18), transparent 25%), linear-gradient(120deg, #0c1b30, #14335a 72%, #164e63); box-shadow: 0 12px 35px rgba(15,23,42,.1); }
.welcome-banner::after { content: ''; position: absolute; right: 12%; bottom: -100px; width: 250px; height: 250px; border: 1px solid rgba(125,211,252,.1); border-radius: 50%; box-shadow: 0 0 0 45px rgba(125,211,252,.025), 0 0 0 90px rgba(125,211,252,.018); }
.eyebrow { margin: 0 0 7px; color: #60a5fa; font-size: 9px; font-weight: 800; letter-spacing: .18em; }
.welcome-banner h1 { margin: 0; color: #fff; font-size: 27px; letter-spacing: -.035em; }
.welcome-banner > div > p:not(.eyebrow) { margin: 9px 0 19px; color: #a8bad0; font-size: 12px; }
.banner-actions { display: flex; gap: 9px; }
.banner-actions a { min-height: 35px; display: inline-flex; align-items: center; gap: 18px; border-radius: 8px; padding: 0 14px; text-decoration: none; font-size: 11px; font-weight: 700; }
.primary-link { color: #0f2d4f; background: #e0f2fe; }.primary-link:hover { background: #fff; }
.secondary-link { border: 1px solid rgba(191,219,254,.24); color: #dbeafe; background: rgba(255,255,255,.05); }.secondary-link:hover { background: rgba(255,255,255,.1); }
.orbit { position: relative; z-index: 1; width: 160px; height: 160px; margin-right: 7%; display: grid; place-items: center; border: 1px solid rgba(125,211,252,.13); border-radius: 50%; }
.orbit::before, .orbit::after { content: ''; position: absolute; border: 1px solid rgba(125,211,252,.1); border-radius: 50%; }.orbit::before { inset: 19px; }.orbit::after { inset: 42px; }
.orbit b { width: 49px; height: 49px; display: grid; place-items: center; border-radius: 50%; color: #fff; background: linear-gradient(145deg, #2563eb, #0891b2); box-shadow: 0 0 35px rgba(56,189,248,.3); font-size: 12px; }
.orbit i { position: absolute; width: 6px; height: 6px; border-radius: 50%; background: #7dd3fc; box-shadow: 0 0 8px #38bdf8; }.orbit i:nth-child(1) { top: 17px; left: 50%; }.orbit i:nth-child(2) { right: 23px; bottom: 29px; }.orbit i:nth-child(3) { left: 35px; bottom: 42px; }
.error-banner { display: flex; justify-content: space-between; margin-top: 14px; border: 1px solid #fecaca; border-radius: 9px; padding: 10px 13px; color: #b91c1c; background: #fff7f7; font-size: 11px; }.error-banner button { border: 0; color: #b91c1c; background: transparent; font-weight: 700; cursor: pointer; }
.metrics { display: grid; grid-template-columns: repeat(5, 1fr); gap: 13px; margin: 15px 0; }
.metric-card { min-height: 88px; display: grid; grid-template-columns: 40px 1fr; grid-template-rows: auto auto; column-gap: 11px; align-items: center; border: 1px solid #e2e8f0; border-radius: 11px; padding: 14px; background: #fff; box-shadow: 0 3px 12px rgba(15,23,42,.025); }
.metric-icon { grid-row: 1 / 3; width: 38px; height: 38px; display: grid; place-items: center; border-radius: 10px; font-size: 17px; }.metric-icon.green { color: #15803d; background: #f0fdf4; }.metric-icon.blue { color: #2563eb; background: #eff6ff; }.metric-icon.violet { color: #7c3aed; background: #f5f3ff; }.metric-icon.cyan { color: #0891b2; background: #ecfeff; }.metric-icon.amber { color: #d97706; background: #fffbeb; }
.metric-card > div:nth-child(2) { display: flex; align-items: baseline; gap: 7px; }.metric-card strong { color: #0f172a; font-size: 21px; line-height: 1; }.metric-card span { color: #64748b; font-size: 10px; font-weight: 650; }.metric-card small { grid-column: 2; align-self: start; color: #a1afc0; font-size: 8px; }
.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(285px, .8fr); gap: 15px; }
.right-column { display: grid; gap: 15px; align-content: start; }
.panel { border: 1px solid #e2e8f0; border-radius: 12px; background: #fff; box-shadow: 0 3px 12px rgba(15,23,42,.025); }
.panel-heading { min-height: 66px; display: flex; align-items: center; justify-content: space-between; padding: 0 19px; border-bottom: 1px solid #edf2f7; }.panel-heading p { margin: 0 0 4px; color: #94a3b8; font-size: 8px; font-weight: 800; letter-spacing: .13em; }.panel-heading h2 { margin: 0; color: #273449; font-size: 13px; }.panel-heading button { border: 0; color: #64748b; background: transparent; font-size: 10px; cursor: pointer; }.panel-heading.compact { min-height: 57px; }.panel-heading > span { color: #2563eb; font-size: 13px; font-weight: 800; }
.activity-list { padding: 3px 14px 12px; }
.activity-row { min-height: 60px; display: grid; grid-template-columns: 35px 1fr auto 12px; align-items: center; gap: 10px; border-bottom: 1px solid #f1f5f9; color: inherit; text-decoration: none; }.activity-row:last-child { border: 0; }.activity-row:hover { background: #fafcff; }
.activity-symbol { width: 31px; height: 31px; display: grid; place-items: center; border-radius: 8px; color: #2563eb; background: #eff6ff; }.activity-symbol.workflow { color: #7c3aed; background: #f5f3ff; }
.activity-copy { min-width: 0; display: grid; gap: 4px; }.activity-copy b { overflow: hidden; color: #334155; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.activity-copy small { color: #a1afc0; font-size: 8px; }
.activity-status { border-radius: 10px; padding: 3px 7px; color: #15803d; background: #f0fdf4; font-size: 8px; }.activity-status.failed { color: #b91c1c; background: #fef2f2; }.activity-status.running { color: #1d4ed8; background: #eff6ff; }
.activity-row > i { color: #cbd5e1; font-style: normal; }
.empty-activity { min-height: 245px; display: grid; place-content: center; justify-items: center; color: #94a3b8; text-align: center; }.empty-activity > span { width: 40px; height: 40px; display: grid; place-items: center; margin-bottom: 11px; border-radius: 11px; background: #f1f5f9; font-size: 19px; }.empty-activity b { color: #64748b; font-size: 11px; }.empty-activity p { max-width: 290px; margin: 7px 0; font-size: 9px; line-height: 1.6; }
.activity-loading { display: grid; gap: 9px; padding: 14px; }.activity-loading i { height: 49px; border-radius: 8px; background: #f1f5f9; }
.progress { height: 4px; margin: 15px 18px 9px; overflow: hidden; border-radius: 5px; background: #eaf0f7; }.progress i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #2563eb, #06b6d4); transition: width .3s; }
.check-row { min-height: 52px; display: grid; grid-template-columns: 27px 1fr 10px; align-items: center; gap: 9px; margin: 0 13px; border-bottom: 1px solid #f1f5f9; color: inherit; text-decoration: none; }.check-row:last-child { border: 0; margin-bottom: 10px; }.check-row > span { width: 24px; height: 24px; display: grid; place-items: center; border: 1px solid #cbd5e1; border-radius: 50%; color: #64748b; font-size: 9px; font-weight: 700; }.check-row.done > span { border-color: #bbf7d0; color: #15803d; background: #f0fdf4; }.check-row div { display: grid; gap: 3px; }.check-row b { color: #475569; font-size: 10px; }.check-row small { color: #a1afc0; font-size: 8px; }.check-row > i { color: #cbd5e1; font-style: normal; }
.quick-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; padding: 12px; }.quick-grid a { display: grid; grid-template-columns: 28px 1fr; column-gap: 8px; border: 1px solid #edf2f7; border-radius: 8px; padding: 10px; color: inherit; text-decoration: none; }.quick-grid a:hover { border-color: #bfdbfe; background: #f8fbff; }.quick-grid span { grid-row: 1 / 3; width: 27px; height: 27px; display: grid; place-items: center; border-radius: 7px; color: #2563eb; background: #eff6ff; }.quick-grid b { color: #475569; font-size: 9px; }.quick-grid small { margin-top: 2px; color: #a1afc0; font-size: 7px; }
@media (max-width: 1080px) { .orbit { display: none; }.metrics { grid-template-columns: repeat(2, 1fr); }.dashboard-grid { grid-template-columns: 1fr; } }
</style>
