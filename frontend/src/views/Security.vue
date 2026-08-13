<template>
  <div class="security-page">
    <section class="security-hero">
      <div>
        <p>DATA PROTECTION</p>
        <h1>科研数据安全与完整性</h1>
        <span>检查原始材料静态加密覆盖率，并验证追加式审计哈希链。</span>
      </div>
      <button :disabled="loading" @click="loadStatus">{{ loading ? '验证中…' : '重新验证' }}</button>
    </section>

    <div v-if="error" class="alert" role="alert">{{ error }}</div>

    <section v-if="status" class="metrics">
      <article>
        <small>加密覆盖</small>
        <strong>{{ coverage }}%</strong>
        <span>当前账户 {{ status.artifacts.encrypted }} / {{ status.artifacts.total }} 个材料</span>
      </article>
      <article :class="{ warning: status.artifacts.legacy_plaintext > 0 }">
        <small>旧版明文</small>
        <strong>{{ status.artifacts.legacy_plaintext }}</strong>
        <span>{{ status.artifacts.legacy_plaintext ? '建议执行受控迁移' : '未发现明文材料' }}</span>
      </article>
      <article :class="status.audit_chain.valid ? 'healthy' : 'danger'">
        <small>审计链</small>
        <strong>{{ status.audit_chain.valid ? '通过' : '异常' }}</strong>
        <span>{{ status.audit_chain.chained_entries }} 条受保护事件</span>
      </article>
      <article>
        <small>全机加密覆盖</small>
        <strong>{{ globalCoverage }}%</strong>
        <span>{{ status.global_artifacts.encrypted }} / {{ status.global_artifacts.total }} 个材料</span>
      </article>
    </section>

    <section v-if="status" class="grid">
      <article class="panel">
        <header><div><p>ENCRYPTION AT REST</p><h2>材料存储</h2></div><b>{{ status.artifacts.encryption_format }}</b></header>
        <div class="body">
          <p>新上传材料使用 AES-256-GCM 认证加密。下载或分析前会同时验证密文摘要、认证标签和原始 SHA-256。</p>
          <div class="bar"><i :style="{ width: `${coverage}%` }"></i></div>
          <button
            v-if="status.artifacts.legacy_plaintext > 0"
            class="primary"
            :disabled="migrating"
            @click="migrateLegacy"
          >{{ migrating ? '正在迁移…' : `加密 ${status.artifacts.legacy_plaintext} 个旧材料` }}</button>
          <small v-else class="ok">✓ 当前所有科研材料均已静态加密</small>
          <p v-if="migrationMessage" class="message">{{ migrationMessage }}</p>
        </div>
      </article>

      <article class="panel">
        <header><div><p>TAMPER EVIDENCE</p><h2>审计完整性</h2></div><b :class="status.audit_chain.valid ? 'valid' : 'invalid'">{{ status.audit_chain.valid ? 'VALID' : 'INVALID' }}</b></header>
        <div class="body">
          <dl>
            <dt>链格式</dt><dd>{{ status.audit_chain.chain_version }}</dd>
            <dt>链头摘要</dt><dd class="hash">{{ status.audit_chain.head_hash || '尚无事件' }}</dd>
            <dt>异常数量</dt><dd>{{ status.audit_chain.issues.length }}</dd>
          </dl>
          <div v-if="status.audit_chain.issues.length" class="issues">
            <p v-for="item in status.audit_chain.issues" :key="item.id">事件 #{{ item.id }}：{{ item.reasons.join('、') }}</p>
          </div>
          <ul><li v-for="item in status.audit_chain.limitations" :key="item">{{ item }}</li></ul>
        </div>
      </article>
    </section>

    <div v-if="loading && !status" class="loading">正在验证本地安全状态…</div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'
import { apiError } from '../state/session'

const loading = ref(false)
const migrating = ref(false)
const error = ref('')
const migrationMessage = ref('')
const status = ref(null)
const coverage = computed(() => {
  const total = status.value?.artifacts?.total || 0
  return total ? Math.round(status.value.artifacts.encrypted / total * 100) : 100
})
const globalCoverage = computed(() => {
  const total = status.value?.global_artifacts?.total || 0
  return total ? Math.round(status.value.global_artifacts.encrypted / total * 100) : 100
})

async function loadStatus() {
  loading.value = true
  error.value = ''
  try {
    status.value = (await axios.get('/api/v1/system/security-integrity')).data
  } catch (err) {
    error.value = apiError(err, '安全状态验证失败')
  } finally {
    loading.value = false
  }
}

async function migrateLegacy() {
  if (!window.confirm('将当前账户的旧版明文科研材料转换为认证加密格式。继续吗？')) return
  migrating.value = true
  error.value = ''
  migrationMessage.value = ''
  try {
    const result = (await axios.post('/api/v1/research/artifacts/migrate-encryption', { artifact_ids: [] }, { timeout: 120_000 })).data
    migrationMessage.value = `已迁移 ${result.migrated.length} 个；失败 ${result.failed.length} 个；明文清理警告 ${result.plaintext_cleanup_warnings.length} 个。`
    await loadStatus()
  } catch (err) {
    error.value = apiError(err, '旧材料迁移失败')
  } finally {
    migrating.value = false
  }
}

onMounted(loadStatus)
</script>

<style scoped>
.security-page{max-width:1180px;margin:auto;color:#263449}.security-hero{min-height:150px;display:flex;align-items:center;justify-content:space-between;border-radius:15px;padding:28px 36px;color:#dbeafe;background:radial-gradient(circle at 82% 0,rgba(16,185,129,.18),transparent 31%),linear-gradient(120deg,#08172a,#174150)}.security-hero p,.panel header p{margin:0 0 5px;color:#5eead4;font-size:9px;font-weight:800;letter-spacing:.16em}.security-hero h1{margin:0 0 8px;color:#fff;font-size:25px}.security-hero span{color:#a8bad0;font-size:11px}.security-hero button{border:1px solid #ffffff30;border-radius:8px;padding:9px 14px;color:#e6fffb;background:#ffffff0d;cursor:pointer}.security-hero button:disabled{opacity:.5}.alert{margin-top:14px;border:1px solid #fecaca;border-radius:9px;padding:11px;color:#b91c1c;background:#fff7f7}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin:15px 0}.metrics article{min-height:105px;display:grid;gap:5px;border:1px solid #e2e8f0;border-radius:11px;padding:16px;background:#fff}.metrics article.healthy{border-color:#bbf7d0}.metrics article.warning{border-color:#fde68a;background:#fffdf5}.metrics article.danger{border-color:#fecaca;background:#fff7f7}.metrics small{color:#64748b;font-size:9px}.metrics strong{font-size:24px}.metrics span{color:#94a3b8;font-size:9px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.panel{overflow:hidden;border:1px solid #e2e8f0;border-radius:12px;background:#fff}.panel header{min-height:67px;display:flex;align-items:center;justify-content:space-between;padding:0 19px;border-bottom:1px solid #edf2f7}.panel h2{margin:0;font-size:14px}.panel header>b{max-width:160px;overflow:hidden;color:#475569;font-size:8px;text-overflow:ellipsis}.panel header>b.valid{color:#15803d}.panel header>b.invalid{color:#b91c1c}.body{padding:18px}.body>p{margin:0 0 15px;color:#64748b;font-size:10px;line-height:1.7}.bar{height:7px;overflow:hidden;border-radius:7px;background:#e2e8f0}.bar i{display:block;height:100%;background:linear-gradient(90deg,#2563eb,#10b981)}.primary{margin-top:15px;border:0;border-radius:7px;padding:8px 12px;color:#fff;background:#2563eb;cursor:pointer}.primary:disabled{opacity:.5}.ok{display:block;margin-top:15px;color:#15803d}.message{margin-top:12px!important;color:#334155!important}.body dl{display:grid;grid-template-columns:100px 1fr;margin:0}.body dt,.body dd{margin:0;border-bottom:1px solid #edf2f7;padding:8px;font-size:9px}.body dt{color:#64748b}.hash{overflow:hidden;font-family:ui-monospace,monospace;text-overflow:ellipsis;white-space:nowrap}.body ul{margin:15px 0 0;padding-left:17px;color:#64748b;font-size:9px;line-height:1.7}.issues{margin-top:12px;border:1px solid #fecaca;border-radius:7px;padding:8px;color:#b91c1c;background:#fff7f7}.issues p{margin:3px;font-size:9px}.loading{min-height:240px;display:grid;place-items:center;color:#64748b}@media(max-width:900px){.metrics,.grid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.metrics,.grid{grid-template-columns:1fr}.security-hero{align-items:flex-start;gap:20px;flex-direction:column}}
</style>
