<template>
  <div class="pipelines-page">
    <section class="hero">
      <div>
        <p>PINNED PRODUCTION PIPELINES</p>
        <h1>可审计的生物信息学生产流程</h1>
        <span>固定发布版本、受控参数、执行前预检、进程树取消与 Nextflow 报告溯源。</span>
      </div>
      <div class="health" :class="capabilities.available ? 'ready' : 'missing'">
        <b>{{ capabilities.available ? 'Nextflow 已发现' : '当前不可执行' }}</b>
        <small>{{ capabilities.available ? capabilities.executable : '仍可创建和审阅执行计划' }}</small>
        <button @click="probe">重新检测</button>
      </div>
    </section>

    <div v-if="error" class="alert" role="alert">
      <span>{{ error }}</span><button @click="error = ''">×</button>
    </div>

    <section class="policy panel">
      <div><b>执行安全策略</b><span>仅管理员可启动；未知流程、版本、参数和制品类型默认拒绝。</span></div>
      <div><b>可复现记录</b><span>保存输入哈希、固定 revision、参数、trace、timeline、DAG 与日志摘要。</span></div>
      <div><b>运行边界</b><span>工作目录按用户隔离；最长 7 天；应用退出或取消时终止完整进程树。</span></div>
    </section>

    <div class="layout">
      <section class="panel builder">
        <header>
          <div><p>EXECUTION PLAN</p><h2>配置流程</h2></div>
          <span>{{ selected?.revision || '—' }}</span>
        </header>

        <div class="catalog">
          <button
            v-for="item in catalog"
            :key="item.id"
            :class="{ active: item.id === form.pipeline_id }"
            @click="choose(item)"
          >
            <b>{{ item.title }}</b><small>{{ item.description }}</small><i>v{{ item.revision }}</i>
          </button>
        </div>

        <div v-if="selected" class="form-grid">
          <label>执行环境
            <select v-model="form.profile"><option v-for="item in selected.profiles" :key="item" :value="item">{{ item }}</option></select>
          </label>
          <label>最长运行（小时）<input v-model.number="hours" type="number" min="1" max="168"></label>
          <label class="wide">样本表（必需）
            <select v-model="form.artifact_bindings.input">
              <option value="">请选择 CSV 制品</option>
              <option v-for="item in sampleSheets" :key="item.id" :value="item.id">{{ item.name }}</option>
            </select>
          </label>
          <label v-for="(rule, name) in optionalArtifacts" :key="name">{{ artifactLabel(name) }}
            <select v-model="form.artifact_bindings[name]">
              <option value="">不绑定</option>
              <option v-for="item in matchingArtifacts(rule)" :key="item.id" :value="item.id">{{ item.name }}</option>
            </select>
          </label>
          <label v-for="(rule, name) in selected.parameters" :key="name">{{ parameterLabel(name) }}
            <select v-if="rule.type === 'enum'" v-model="form.parameters[name]">
              <option value="">使用流程默认值</option><option v-for="value in rule.values" :key="value" :value="value">{{ value }}</option>
            </select>
            <select v-else-if="rule.type === 'boolean'" v-model="form.parameters[name]">
              <option value="">使用流程默认值</option><option :value="true">是</option><option :value="false">否</option>
            </select>
            <input v-else-if="rule.type === 'integer'" v-model.number="form.parameters[name]" type="number" :min="rule.minimum" :max="rule.maximum" placeholder="使用默认值">
            <input v-else v-model="form.parameters[name]" :placeholder="rule.type === 'memory' ? '例如 16 GB' : '使用流程默认值'">
          </label>
        </div>

        <div class="upload-row">
          <span>上传 CSV / FASTA / GTF / BED（单文件 ≤ 25 MiB）</span>
          <label><input type="file" accept=".csv,.fa,.fasta,.fna,.gtf,.gff,.gff3,.bed,.interval_list" @change="upload">{{ uploading ? '校验中…' : '上传制品' }}</label>
        </div>
        <div class="controls">
          <label><input v-model="form.network_allowed" type="checkbox">允许拉取固定流程与容器</label>
          <button :disabled="busy || !canPlan" @click="create(false)">保存并审阅计划</button>
          <button class="primary" :disabled="busy || !canPlan || !isAdmin" @click="create(true)">预检并启动</button>
        </div>
        <p v-if="!isAdmin" class="notice">当前角色可查看目录和本人记录；启动外部计算需要管理员权限。</p>
      </section>

      <aside class="panel history">
        <header><div><p>RUN HISTORY</p><h2>最近运行</h2></div><button @click="loadRuns">刷新</button></header>
        <button v-for="run in runs" :key="run.id" class="run" :class="{ active: active?.id === run.id }" @click="selectRun(run.id)">
          <i :class="run.status"></i><div><b>{{ run.pipeline_id }}</b><small>{{ statusLabel(run.status) }} · {{ run.profile }} · {{ timeLabel(run.created_at) }}</small></div><span>v{{ run.revision }}</span>
        </button>
        <div v-if="!runs.length" class="empty">尚无生产流程记录</div>
      </aside>
    </div>

    <section v-if="active" class="panel detail">
      <header>
        <div><p>PIPELINE RUN · {{ active.id.slice(0, 8) }}</p><h2>{{ active.pipeline_id }} <small>v{{ active.revision }}</small></h2></div>
        <div class="run-actions">
          <b :class="active.status">{{ statusLabel(active.status) }}</b>
          <button v-if="active.status === 'planned' && isAdmin" @click="act('start')">启动</button>
          <button v-if="['queued', 'running'].includes(active.status) && isAdmin" class="danger" @click="act('cancel')">取消</button>
          <button v-if="['failed', 'cancelled', 'interrupted'].includes(active.status) && isAdmin" @click="act('resume')">从缓存恢复</button>
        </div>
      </header>
      <div v-if="active.error" class="run-error">{{ active.error }}</div>
      <div class="facts">
        <span><b>Backend</b>{{ active.backend }}</span><span><b>Profile</b>{{ active.profile }}</span>
        <span><b>Exit</b>{{ active.exit_code ?? '—' }}</span><span><b>Resume</b>{{ active.resume_count }}</span>
        <span><b>Timeout</b>{{ Math.round(active.timeout_seconds / 3600) }} h</span>
      </div>
      <div class="detail-grid">
        <section><h3>脱敏执行参数</h3><code v-for="(arg, index) in active.plan?.argv || []" :key="index">{{ arg }}</code></section>
        <section><h3>任务追踪摘要</h3><div class="statuses"><span v-for="(count, key) in active.result?.task_summary?.statuses || {}" :key="key"><b>{{ count }}</b>{{ key }}</span></div><p v-if="!active.result?.task_summary?.tasks">执行完成后显示 Nextflow trace 汇总。</p></section>
        <section class="wide">
          <h3>报告与结果制品</h3>
          <div class="reports">
            <button v-for="(item, index) in active.result?.artifacts || []" :key="item.relative_path" @click="download(index, item)">
              <b>{{ item.kind }} · {{ item.name }}</b><small>{{ sizeLabel(item.size_bytes) }} · {{ item.sha256 ? `SHA-256 ${item.sha256.slice(0, 12)}…` : '未哈希（超出本次预算）' }}</small>
            </button>
            <p v-if="!active.result?.artifacts?.length">尚未生成报告、日志或结果文件。</p>
          </div>
        </section>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { apiError, sessionState } from '../state/session'

const catalog = ref([]), artifacts = ref([]), runs = ref([]), active = ref(null)
const capabilities = reactive({ available: false, executable: '' })
const error = ref(''), busy = ref(false), uploading = ref(false), hours = ref(24)
const form = reactive({ pipeline_id: '', revision: '', profile: 'docker', parameters: {}, artifact_bindings: { input: '' }, network_allowed: true })
let pollTimer

const isAdmin = computed(() => sessionState.user?.role === 'admin')
const selected = computed(() => catalog.value.find(item => item.id === form.pipeline_id))
const sampleSheets = computed(() => artifacts.value.filter(item => item.name.toLowerCase().endsWith('.csv')))
const optionalArtifacts = computed(() => Object.fromEntries(Object.entries(selected.value?.artifact_parameters || {}).filter(([name]) => name !== 'input')))
const canPlan = computed(() => form.pipeline_id && (form.parameters.test_profile === true || form.artifact_bindings.input) && hours.value >= 1 && hours.value <= 168)

function choose(item) {
  form.pipeline_id = item.id; form.revision = item.revision
  form.profile = item.profiles.includes(form.profile) ? form.profile : item.profiles[0]
  form.parameters = { genome: 'GRCh38' }; form.artifact_bindings = { input: '' }
  for (const [name, rule] of Object.entries(item.artifact_parameters)) if (!rule.required) form.artifact_bindings[name] = ''
}
const suffix = name => `.${name.toLowerCase().split('.').pop()}`
const matchingArtifacts = rule => artifacts.value.filter(item => rule.suffixes.includes(suffix(item.name)))
const clean = object => Object.fromEntries(Object.entries(object).filter(([, value]) => value !== '' && value !== null && value !== undefined))
const effectiveParameters = () => form.parameters.test_profile === true
  ? clean({ test_profile: true, max_cpus: form.parameters.max_cpus, max_memory: form.parameters.max_memory })
  : clean(form.parameters)
const payload = (execute = false) => ({ pipeline_id: form.pipeline_id, revision: form.revision, profile: form.profile, parameters: effectiveParameters(), artifact_bindings: form.parameters.test_profile === true ? {} : clean(form.artifact_bindings), network_allowed: form.network_allowed, timeout_seconds: Math.round(hours.value * 3600), execute })

async function load() {
  const [cat, files] = await Promise.all([axios.get('/api/v1/pipelines/catalog'), axios.get('/api/v1/research/artifacts')])
  catalog.value = cat.data.pipelines || []; artifacts.value = files.data.artifacts || []
  if (!selected.value && catalog.value[0]) choose(catalog.value[0])
}
async function probe() { try { Object.assign(capabilities, (await axios.get('/api/v1/pipelines/capabilities', { params: { deep: isAdmin.value } })).data) } catch (exc) { error.value = apiError(exc, '运行环境检测失败') } }
async function create(execute) {
  busy.value = true; error.value = ''
  try {
    const result = (await axios.post('/api/v1/pipelines/runs', payload(execute), { timeout: 60000 })).data
    active.value = result; await loadRuns()
    if (result.preflight && !result.preflight.ready) error.value = `计划已保存；执行预检未通过：${result.preflight.issues.join('；')}`
    poll()
  } catch (exc) { error.value = apiError(exc, '流程计划创建失败') } finally { busy.value = false }
}
async function upload(event) {
  const file = event.target.files?.[0]; event.target.value = ''
  if (!file) return
  uploading.value = true
  try {
    const data = new FormData(); data.append('file', file)
    const item = (await axios.post('/api/v1/research/artifacts', data, { timeout: 90000 })).data
    artifacts.value.unshift(item); if (item.name.toLowerCase().endsWith('.csv')) form.artifact_bindings.input = item.id
  } catch (exc) { error.value = apiError(exc, '制品上传失败') } finally { uploading.value = false }
}
async function loadRuns() { try { runs.value = (await axios.get('/api/v1/pipelines/runs')).data.runs || [] } catch (exc) { error.value = apiError(exc, '运行记录加载失败') } }
async function selectRun(id) { try { active.value = (await axios.get(`/api/v1/pipelines/runs/${id}`)).data; poll() } catch (exc) { error.value = apiError(exc, '运行详情加载失败') } }
async function act(action) {
  try { await axios.post(`/api/v1/pipelines/runs/${active.value.id}/${action}`, {}, { timeout: 60000 }); await selectRun(active.value.id); await loadRuns() }
  catch (exc) { const detail = exc.response?.data?.detail; error.value = typeof detail === 'object' ? (detail.issues || [detail.message]).join('；') : apiError(exc, '运行操作失败') }
}
async function download(index, item) {
  try {
    const response = await axios.get(`/api/v1/pipelines/runs/${active.value.id}/artifacts/${index}`, { responseType: 'blob', timeout: 90000 })
    const url = URL.createObjectURL(response.data); const link = document.createElement('a')
    link.href = url; link.download = item.name || 'pipeline-artifact'; link.click(); URL.revokeObjectURL(url)
  } catch (exc) { error.value = apiError(exc, '制品下载失败') }
}
function poll() {
  clearInterval(pollTimer)
  if (!active.value || !['queued', 'running', 'cancelling'].includes(active.value.status)) return
  pollTimer = setInterval(async () => {
    try { active.value = (await axios.get(`/api/v1/pipelines/runs/${active.value.id}`)).data; await loadRuns(); if (!['queued', 'running', 'cancelling'].includes(active.value.status)) clearInterval(pollTimer) } catch (_) {}
  }, 1800)
}
const statusLabel = value => ({ planned: '已规划', queued: '排队中', running: '运行中', cancelling: '取消中', completed: '已完成', failed: '失败', cancelled: '已取消', interrupted: '被中断' }[value] || value)
const parameterLabel = value => ({ test_profile: 'nf-core 官方小型验收数据', genome: '参考基因组', aligner: '比对器', skip_trimming: '跳过剪切', save_reference: '保存参考文件', max_cpus: 'CPU 上限', max_memory: '内存上限', wes: '外显子组模式', tools: '变异检测器', step: '起始步骤' }[value] || value)
const artifactLabel = value => ({ fasta: '参考 FASTA', gtf: '注释 GTF', intervals: '区间 BED' }[value] || value)
const timeLabel = value => value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''
const sizeLabel = value => value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KiB` : `${(value / 1048576).toFixed(1)} MiB`

onMounted(async () => { try { await Promise.all([load(), loadRuns(), probe()]); if (runs.value[0]) await selectRun(runs.value[0].id) } catch (exc) { error.value = apiError(exc, '生产流程页面加载失败') } })
onBeforeUnmount(() => clearInterval(pollTimer))
</script>

<style scoped>
.pipelines-page{max-width:1320px;margin:auto;color:#263449}.hero{min-height:140px;display:flex;align-items:center;justify-content:space-between;border-radius:15px;padding:26px 34px;color:#dbeafe;background:radial-gradient(circle at 78% 0,#22d3ee26,transparent 32%),linear-gradient(120deg,#071526,#163b61)}p{margin:0}.hero p,.panel header p{margin-bottom:5px;color:#60a5fa;font-size:9px;font-weight:800;letter-spacing:.15em}.hero h1{margin:0 0 8px;color:white;font-size:24px}.hero span{color:#a8bad0;font-size:11px}.health{min-width:190px;display:grid;gap:4px;border:1px solid #ffffff24;border-radius:11px;padding:13px 15px;background:#ffffff0d}.health b{font-size:11px}.health small{color:#91a6bf;font-size:8px}.health.ready b{color:#86efac}.health.missing b{color:#fde68a}.health button{justify-self:start;border:0;padding:4px 0;color:#93c5fd;background:none;font-size:8px}.alert{display:flex;justify-content:space-between;margin:12px 0;border:1px solid #fecaca;border-radius:9px;padding:10px 12px;color:#b91c1c;background:#fff7f7;font-size:10px}.alert button{border:0;color:inherit;background:none}.panel{border:1px solid #e2e8f0;border-radius:12px;background:white;box-shadow:0 3px 14px #0f172a08}.policy{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin-top:14px;overflow:hidden;background:#e2e8f0}.policy div{display:grid;gap:3px;padding:12px 16px;background:#fff}.policy b{font-size:9px}.policy span{color:#64748b;font-size:8px}.layout{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:14px;margin-top:14px}.builder{padding:19px}.builder>header,.history>header,.detail>header{display:flex;align-items:center;justify-content:space-between}.panel h2{margin:0;font-size:15px}.builder>header>span{border-radius:10px;padding:4px 8px;color:#1d4ed8;background:#eff6ff;font-size:8px}.catalog{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:13px}.catalog button{position:relative;display:grid;gap:5px;border:1px solid #e2e8f0;border-radius:9px;padding:12px;background:#fff;text-align:left}.catalog button.active{border-color:#60a5fa;background:#f7fbff;box-shadow:0 0 0 2px #dbeafe}.catalog b{font-size:10px}.catalog small{max-width:80%;color:#64748b;font-size:8px;line-height:1.45}.catalog i{position:absolute;right:9px;top:10px;color:#2563eb;font-size:7px;font-style:normal}.form-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:15px}.form-grid label{display:grid;gap:5px;color:#475569;font-size:8px;font-weight:700}.form-grid .wide{grid-column:span 2}.form-grid input,.form-grid select{width:100%;height:34px;border:1px solid #dbe4ee;border-radius:7px;padding:0 9px;color:#334155;background:#fbfdff;font-size:9px}.upload-row{display:flex;align-items:center;justify-content:space-between;margin-top:15px;border:1px dashed #cbd5e1;border-radius:8px;padding:9px 11px;color:#64748b;font-size:8px}.upload-row label{border:1px solid #bfdbfe;border-radius:6px;padding:6px 9px;color:#1d4ed8;background:#eff6ff}.upload-row input{display:none}.controls{display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:15px}.controls label{margin-right:auto;font-size:8px}.controls button,.run-actions button{height:33px;border:1px solid #dbe4ee;border-radius:7px;padding:0 12px;background:white;font-size:8px;font-weight:700}.controls .primary{border:0;color:white;background:#2563eb}.controls button:disabled{opacity:.45}.notice{margin-top:8px;color:#a16207;font-size:8px}.history{align-self:start;overflow:hidden}.history>header{height:61px;padding:0 14px;border-bottom:1px solid #edf2f7}.history>header button{border:0;color:#64748b;background:none;font-size:8px}.run{width:100%;min-height:57px;display:grid;grid-template-columns:8px 1fr auto;align-items:center;gap:9px;border:0;padding:8px 13px;background:white;text-align:left}.run:hover,.run.active{background:#f5f8fc}.run i{width:7px;height:7px;border-radius:50%;background:#cbd5e1}.run i.running,.run i.queued{background:#3b82f6;box-shadow:0 0 0 3px #dbeafe}.run i.completed{background:#22c55e}.run i.failed,.run i.interrupted{background:#ef4444}.run div{min-width:0;display:grid}.run b{font-size:9px}.run small{overflow:hidden;color:#94a3b8;font-size:7px;text-overflow:ellipsis;white-space:nowrap}.run>span{color:#64748b;font-size:7px}.empty{padding:55px 20px;color:#94a3b8;text-align:center;font-size:9px}.detail{margin-top:14px;overflow:hidden}.detail>header{min-height:75px;padding:14px 18px;border-bottom:1px solid #edf2f7}.detail h2 small{color:#64748b;font-size:9px}.run-actions{display:flex;align-items:center;gap:7px}.run-actions>b{border-radius:10px;padding:4px 8px;color:#1d4ed8;background:#eff6ff;font-size:8px}.run-actions>b.completed{color:#15803d;background:#f0fdf4}.run-actions>b.failed,.run-actions>b.interrupted{color:#b91c1c;background:#fef2f2}.run-actions .danger{color:#b91c1c;border-color:#fecaca}.run-error{margin:12px 18px 0;border:1px solid #fecaca;border-radius:7px;padding:9px;color:#b91c1c;background:#fff7f7;font-size:8px}.facts{display:grid;grid-template-columns:repeat(5,1fr);border-bottom:1px solid #edf2f7;background:#fafcff}.facts span{display:grid;gap:3px;border-right:1px solid #edf2f7;padding:10px 18px;font-size:9px}.facts b{color:#94a3b8;font-size:7px}.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:15px}.detail-grid section{border:1px solid #e5eaf1;border-radius:8px;padding:11px}.detail-grid section.wide{grid-column:1/3}.detail-grid h3{margin:0 0 9px;font-size:9px}.detail-grid code{display:block;overflow:hidden;padding:3px 6px;color:#334155;background:#f8fafc;font-size:7px;text-overflow:ellipsis;white-space:nowrap}.detail-grid p{color:#94a3b8;font-size:8px}.statuses,.reports{display:flex;flex-wrap:wrap;gap:7px}.statuses span,.reports button{display:grid;border:1px solid #e2e8f0;border-radius:6px;padding:7px 9px;color:#64748b;background:white;font-size:7px;text-align:left}.reports button:hover{border-color:#93c5fd;background:#f8fbff}.statuses b{color:#0f172a;font-size:13px}.reports b{font-size:8px}.reports small{margin-top:2px;color:#94a3b8;font-size:7px}@media(max-width:1050px){.layout{grid-template-columns:1fr}.history{display:none}.form-grid{grid-template-columns:repeat(2,1fr)}.policy{grid-template-columns:1fr}.facts{grid-template-columns:repeat(3,1fr)}}
</style>
