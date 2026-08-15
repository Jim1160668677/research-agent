<template>
  <div class="health-page">
    <section class="hero">
      <div><p>ENVIRONMENT CHECK</p><h1>环境体检向导</h1><span>逐项核对主机、WSL2、容器、Nextflow 与磁盘；失败项附中文修复指引。</span></div>
      <div class="hero-badge"><b>{{ overallText }}</b><small>{{ summaryText }}</small></div>
    </section>
    <div v-if="error" class="alert" role="alert"><span>{{ error }}</span><button @click="error=''">×</button></div>

    <div class="toolbar">
      <button :disabled="busy" @click="load(false)">{{ busy ? '检测中…' : '重新检测' }}</button>
      <button class="primary" :disabled="busy" @click="load(true)">{{ busy ? '深度检测中…' : '深度检测（验证版本与流程预检）' }}</button>
      <span class="hint">深度检测会启动 Nextflow 版本探测，可能需要数十秒</span>
    </div>

    <div class="cards">
      <article v-for="item in result.items" :key="item.id" class="card" :class="item.status">
        <header>
          <span class="icon">{{ statusIcon(item.status) }}</span>
          <div><h2>{{ item.title }}</h2><small>{{ statusLabel(item.status) }}</small></div>
        </header>
        <p class="detail">{{ item.detail }}</p>
        <p v-if="item.fix_hint" class="fix">修复指引：{{ item.fix_hint }}</p>
      </article>
    </div>

    <footer v-if="result.items" class="foot">
      <span>检测时间：{{ result.checked_at }} · 深度：{{ result.deep ? '是' : '否' }}</span>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import axios from 'axios'
import { apiError } from '../state/session'

const result = ref({ items: [], summary: {}, checked_at: '', deep: false })
const busy = ref(false)
const error = ref('')

const overallText = computed(() => {
  if (!result.value.items) return '待检测'
  const s = result.value.summary
  if (s.error) return '存在环境问题'
  if (s.missing) return '部分能力缺失'
  return '环境正常'
})
const summaryText = computed(() => {
  if (!result.value.items) return '点击上方按钮开始检测'
  const s = result.value.summary
  return `通过 ${s.ok} · 警告 ${s.warn} · 错误 ${s.error} · 缺失 ${s.missing}`
})
const statusLabel = (s) => ({ ok: '正常', warn: '警告', error: '错误', missing: '缺失' }[s] || s)
const statusIcon = (s) => ({ ok: '✓', warn: '△', error: '✗', missing: '○' }[s] || '?')

async function load(deep) {
  busy.value = true
  error.value = ''
  try {
    result.value = (await axios.get('/api/v1/system/health-check', { params: { deep } })).data
  } catch (e) {
    error.value = apiError(e, '环境体检失败')
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.health-page { max-width: 1120px; margin: auto; color: #263449; }
.hero { min-height: 132px; display: flex; align-items: center; justify-content: space-between; border-radius: 15px; padding: 24px 32px; color: #dbeafe; background: radial-gradient(circle at 82% 0, rgba(34,211,238,.16), transparent 32%), linear-gradient(120deg, #08172a, #163b61); }
.hero p, .toolbar .hint { margin: 0 0 5px; color: #60a5fa; font-size: 8px; font-weight: 800; letter-spacing: .16em; }
.hero h1 { margin: 0 0 7px; color: #fff; font-size: 24px; }
.hero span { color: #a8bad0; font-size: 11px; }
.hero-badge { display: grid; gap: 4px; border: 1px solid #ffffff24; border-radius: 11px; padding: 12px 16px; background: #ffffff0d; }
.hero-badge b { font-size: 12px; }
.hero-badge small { color: #8fa6bf; font-size: 9px; }
.alert { display: flex; justify-content: space-between; margin: 12px 0; border: 1px solid #fecaca; border-radius: 9px; padding: 10px; color: #b91c1c; background: #fff7f7; font-size: 10px; }
.alert button { border: 0; background: none; color: inherit; }
.toolbar { display: flex; align-items: center; gap: 10px; margin: 14px 0; }
.toolbar button { border: 1px solid #dbe4ee; border-radius: 8px; padding: 9px 15px; color: #475569; background: #fff; font-size: 11px; cursor: pointer; }
.toolbar button.primary { border-color: #2563eb; color: #fff; background: #2563eb; }
.toolbar button:disabled { opacity: .55; cursor: default; }
.toolbar .hint { margin: 0; color: #94a3b8; letter-spacing: 0; font-weight: 400; font-size: 9px; }
.cards { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.card { border: 1px solid #e2e8f0; border-radius: 12px; padding: 15px 17px; background: #fff; box-shadow: 0 3px 14px #0f172a08; }
.card header { display: flex; align-items: center; gap: 10px; }
.card header .icon { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 8px; font-weight: 800; }
.card.ok header .icon { color: #15803d; background: #f0fdf4; }
.card.warn header .icon { color: #b45309; background: #fffbeb; }
.card.error header .icon { color: #b91c1c; background: #fef2f2; }
.card.missing header .icon { color: #64748b; background: #f8fafc; }
.card h2 { margin: 0; font-size: 13px; }
.card header small { color: #94a3b8; font-size: 8px; }
.card .detail { margin: 10px 0 0; color: #475569; font-size: 10px; line-height: 1.6; }
.card .fix { margin: 8px 0 0; border-left: 3px solid #fbbf24; padding-left: 9px; color: #92400e; background: #fffbeb; border-radius: 0 6px 6px 0; font-size: 10px; line-height: 1.6; }
.foot { margin: 16px 0 8px; color: #94a3b8; font-size: 9px; text-align: right; }
@media (max-width: 900px) { .cards { grid-template-columns: 1fr; } }
</style>