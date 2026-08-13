<template>
  <div class="market-container">
    <!-- 顶栏: 搜索 + 分类 + 排序 -->
    <div class="market-header">
      <h1>生物分析工具插件市场</h1>
      <p class="subtitle">分子对接 · 蛋白质结构 · 生信分析软件的一站式管理平台</p>
      <div class="toolbar">
        <input v-model="search" placeholder="搜索工具名称、描述、标签..." class="search-input" @input="fetchPlugins" />
        <select v-model="category" class="filter-select" @change="fetchPlugins">
          <option value="">全部分类</option>
          <option v-for="c in categories" :key="c.category" :value="c.category">
            {{ categoryLabel(c.category) }} ({{ c.count }})
          </option>
        </select>
        <select v-model="sort" class="filter-select" @change="fetchPlugins">
          <option value="newest">最新发布</option>
          <option value="rating">评分最高</option>
          <option value="downloads">下载最多</option>
          <option value="name">名称排序</option>
        </select>
        <select v-model="viewFilter" class="filter-select" @change="fetchPlugins">
          <option value="">全部工具</option>
          <option value="selected">已加入清单</option>
          <option value="installed">已安装</option>
          <option value="update">可更新</option>
        </select>
        <button class="btn-check btn" @click="checkUpdates" :disabled="checkingUpdates">
          {{ checkingUpdates ? '检测中...' : '检查更新' }}
        </button>
      </div>
      <div v-if="updateNotice.length" class="update-banner">
        <span>📦 {{ updateNotice.length }} 个工具有新版本可用</span>
        <button class="btn-link" @click="openFirstUpdate">立即升级</button>
      </div>
    </div>

    <section class="runtime-panel" aria-label="本机执行能力">
      <div class="runtime-head">
        <div>
          <h2>本机执行能力</h2>
          <p v-if="platform">{{ platform.host.system }} / {{ platform.host.architecture }} · Python {{ platform.host.python }}</p>
          <p v-else>正在检测本机运行环境…</p>
        </div>
        <button class="btn btn-check" @click="fetchPlatform(isAdmin)" :disabled="platformBusy">
          {{ platformBusy ? '检测中…' : (isAdmin ? '深度检测' : '重新检测') }}
        </button>
      </div>
      <div v-if="platform" class="backend-list">
        <span v-for="backend in platform.execution_backends" :key="backend.id" class="backend-chip">
          {{ backendLabel(backend.id) }}
        </span>
        <span v-if="!platform.execution_backends.length" class="muted">未发现可用执行后端</span>
      </div>
      <ul v-if="platform?.limitations?.length" class="limitations">
        <li v-for="item in platform.limitations" :key="item">{{ item }}</li>
      </ul>
      <div v-if="isAdmin" class="catalog-sync">
        <label for="bioconda-packages">Bioconda 目录同步（只导入元数据，不安装软件）</label>
        <div class="catalog-row">
          <input id="bioconda-packages" v-model="biocondaPackages" class="search-input" placeholder="fastqc, samtools, bwa" />
          <button class="btn btn-primary" @click="syncBioconda" :disabled="catalogBusy">
            {{ catalogBusy ? '同步中…' : '同步可信目录' }}
          </button>
        </div>
        <p v-if="catalogStatus" class="catalog-status">{{ catalogStatus }}</p>
      </div>
    </section>

    <!-- 工具卡片网格 -->
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="!plugins.length" class="empty">
      没有找到匹配的工具，试试其他关键词
    </div>
    <div v-else class="plugin-grid">
      <div v-for="plugin in plugins" :key="plugin.id" class="plugin-card" @click="openDetail(plugin)">
        <div class="card-top">
          <span class="plugin-icon">{{ iconFor(plugin) }}</span>
          <div class="card-meta">
            <h3>{{ plugin.name }} <span class="badge" v-if="plugin.update_available" title="有新版本">更新</span></h3>
            <p class="ver">{{ plugin.version }}<template v-if="plugin.update_available"> → {{ plugin.latest_version }}</template></p>
          </div>
          <div class="installed-flag" :class="'state-' + plugin.lifecycle_state">
            {{ lifecycleLabel(plugin.lifecycle_state) }}
          </div>
        </div>
        <p class="desc">{{ plugin.description }}</p>
        <div class="tags">
          <span v-for="tag in plugin.tags.slice(0, 3)" :key="tag" class="tag">{{ tag }}</span>
        </div>
        <div class="card-foot">
          <span class="rating">⭐ {{ plugin.rating_avg }} <em>({{ plugin.rating_count }})</em></span>
          <span class="downloads">⬇ {{ plugin.downloads }}</span>
          <button class="btn btn-detail" @click.stop="openDetail(plugin)">详情</button>
        </div>
      </div>
    </div>

    <!-- 详情弹窗 -->
    <div v-if="selected" class="modal-overlay" @click.self="selected = null">
      <div class="modal">
        <div class="modal-header">
          <div>
            <h2>{{ selected.name }} <span class="ver-big">v{{ selected.version }}</span></h2>
            <p class="cat"><strong>{{ categoryLabel(selected.category) }}</strong> · 作者 {{ selected.author }} · 许可证 {{ selected.license }}</p>
          </div>
          <button class="modal-close" @click="selected = null">✕</button>
        </div>

        <!-- 顶栏操作 -->
        <div class="modal-actions">
          <span class="lifecycle-pill">{{ lifecycleLabel(selected.lifecycle_state) }}</span>
          <button class="btn btn-primary" v-if="!selected.is_selected" @click="selectTool">＋ 加入工具清单</button>
          <button class="btn btn-primary" v-if="selected.is_selected && !selected.is_deployed" @click="deployTool(true)">⚡ 生成部署计划</button>
          <button class="btn" v-if="selected.is_deployed && isAdmin" @click="verifyInstall">🔍 验证隔离环境</button>
          <button class="btn btn-primary" v-if="selected.is_verified && !selected.is_enabled" @click="setEnabled(true)">启用</button>
          <button class="btn" v-if="selected.is_enabled" @click="setEnabled(false)">停用</button>
          <button class="btn btn-danger" v-if="selected.is_deployed && isAdmin" @click="removeDeployment">移除隔离环境</button>
          <button class="btn" v-if="selected.is_selected && !selected.is_deployed" @click="deselectTool">移出工具清单</button>
          <button v-if="selected.update_available && selected.is_selected" class="btn btn-warn" @click="upgrade">⬆ 切换到 {{ selected.latest_version }}</button>
          <a v-if="selected.homepage" :href="selected.homepage" target="_blank" class="btn btn-link-a">官网</a>
          <a v-if="selected.docs_url" :href="selected.docs_url" target="_blank" class="btn btn-link-a">文档</a>
          <a v-if="selected.support_email" :href="'mailto:' + selected.support_email" class="btn btn-link-a">✉ 技术支持</a>
        </div>
        <div v-if="note" class="note" :class="noteType">{{ note }}</div>

        <div v-if="planVisible && deployPlan" class="plan-box">
          <h3>部署计划 <span v-if="deployBusy">(执行中...)</span></h3>
          <div v-for="(step, i) in deployPlan.steps" :key="i" class="plan-step" :class="step.status">
            <span class="step-icon">{{ { run: '▶', download: '⬇', manual_hint: '📄', config: '⚙', abort: '⛔' }[step.action] || '•' }}</span>
            <div class="step-body">
              <p class="step-desc">{{ step.description }}</p>
              <code v-if="step.command">{{ step.command }}</code>
              <code v-if="step.url">{{ step.url }}</code>
              <p v-if="step.status === 'failed'" class="step-err">{{ step.output || '' }}</p>
            </div>
          </div>
          <div class="plan-foot">
            <span v-if="deployResult?.is_simulated" class="plan-sim">🔬 模拟模式: 展示执行步骤，不会真正改动系统</span>
            <button v-if="deployResult?.is_simulated && deployResult.ok && isAdmin" class="btn btn-primary" @click="deployTool(false)" :disabled="deployBusy">
              {{ deployBusy ? '部署中...' : '确认并执行安装' }}
            </button>
            <span v-else-if="deployResult?.is_simulated && deployResult.ok" class="muted">实际部署需要管理员权限</span>
          </div>
        </div>

        <!-- 信息区 -->
        <div class="modal-body">
          <section class="section">
            <h3>工具信息</h3>
            <div class="info-grid">
              <div><label>最新版本</label><span>{{ selected.latest_version }}</span></div>
              <div><label>安装方式</label><span>{{ methodLabel(selected.install_method) }}</span></div>
              <div><label>支持平台</label><span>{{ (selected.os_compatibility || []).join(' / ') || '未声明' }}</span></div>
              <div><label>下载次数</label><span>{{ selected.downloads }}</span></div>
              <div><label>目录来源</label><span>{{ selected.source_registry }} / {{ selected.trust_status }}</span></div>
              <div><label>Manifest</label><span class="digest" :title="selected.manifest_digest">v{{ selected.manifest_schema_version }} · {{ (selected.manifest_digest || '').slice(0, 12) }}</span></div>
            </div>
          </section>

          <section class="section">
            <h3>依赖关系 <button class="btn btn-mini" @click="resolveDeps">解析依赖</button></h3>
            <div v-if="depsResult" class="deps">
              <div v-if="depsResult.cycle" class="deps-warn">⚠ 存在循环依赖: {{ depsResult.cycle.join(' → ') }}</div>
              <div v-for="c in depsResult.conflicts" :key="c.dependency + c.required_by" class="deps-warn">⚠ {{ c.message }}</div>
              <p v-if="!depsResult.conflicts.length && !depsResult.cycle" class="deps-ok">✓ 无循环依赖，无版本冲突</p>
              <div class="deps-lists">
                <div class="deps-list">
                  <h4>需安装 ({{ depsResult.missing.length }})</h4>
                  <span v-for="m in depsResult.missing" :key="m.name" class="chip chip-missing">{{ m.name }} <em>{{ m.version || '' }}</em></span>
                  <p v-if="!depsResult.missing.length" class="muted">全部满足</p>
                </div>
                <div class="deps-list">
                  <h4>已满足 ({{ depsResult.satisfied.length }})</h4>
                  <span v-for="s in depsResult.satisfied" :key="s.name" class="chip chip-ok">{{ s.name }} <em>{{ s.version }}</em></span>
                </div>
              </div>
              <p v-if="depsResult.order.length" class="deps-order">安装顺序: <code>{{ depsResult.order.join(' → ') }}</code></p>
            </div>
            <div v-else class="muted">{{ selected.dependencies.length ? '点击解析依赖关系' : '无依赖，可直接使用' }}</div>
          </section>

          <section class="section">
            <h3>版本历史 <button class="btn btn-mini" @click="showVersions = !showVersions">{{ showVersions ? '收起' : '展开' }}</button></h3>
            <table v-if="showVersions && selected.versions?.length" class="ver-table">
              <thead><tr><th>版本</th><th>发布日期</th><th>大小</th><th>更新说明</th><th></th></tr></thead>
              <tbody>
                <tr v-for="v in selected.versions" :key="v.id">
                  <td>
                    <strong>{{ v.version }}</strong>
                    <span v-if="v.is_latest" class="badge badge-blue">最新</span>
                    <span v-if="v.version === selected.version" class="badge badge-green">当前</span>
                  </td>
                  <td>{{ v.release_date || '-' }}</td>
                  <td>{{ v.size_mb ? v.size_mb + ' MB' : '-' }}</td>
                  <td class="cl">{{ v.changelog || '-' }}</td>
                  <td><button class="btn btn-mini" v-if="v.version !== selected.version" @click="switchVersion(v.version)">切换</button></td>
                </tr>
              </tbody>
            </table>
            <div v-else-if="!showVersions" class="muted">共 {{ selected.versions?.length || 0 }} 个版本</div>
          </section>

          <section class="section">
            <h3>用户评价 <span class="rating-big">⭐ {{ detailRating.avg || '—' }} <em>({{ detailRating.count }} 条)</em></span></h3>
            <div class="rating-dist" v-if="detailRating.count">
              <div v-for="i in 5" :key="i" class="dist-row">
                <span class="dist-label">{{ i }}★</span>
                <div class="dist-bar"><div class="dist-fill" :style="{width: (detailRating.distribution[i] / detailRating.count * 100) + '%'}"></div></div>
                <span class="dist-num">{{ detailRating.distribution[i] }}</span>
              </div>
            </div>
            <div class="review-form">
              <select v-model="newRating">
                <option :value="5">★★★★★ 强烈推荐</option>
                <option :value="4">★★★★ 推荐</option>
                <option :value="3">★★★ 一般</option>
                <option :value="2">★★ 较差</option>
                <option :value="1">★ 差</option>
              </select>
              <input v-model="newComment" placeholder="分享你的使用体验..." class="review-input" />
              <button class="btn btn-primary" @click="submitReview">提交评价</button>
            </div>
            <div class="review-list">
              <div v-for="r in reviews" :key="r.id" class="review-item">
                <div class="review-head">
                  <span class="stars">{{ '★'.repeat(r.rating) }}<em v-if="r.rating < 5">{{ '☆'.repeat(5 - r.rating) }}</em></span>
                  <span v-if="r.is_verified" class="badge badge-green">已安装用户</span>
                  <span class="review-date">{{ (r.created_at || '').slice(0, 10) }}</span>
                </div>
                <p>{{ r.comment || '（无评论）' }}</p>
              </div>
              <p v-if="!reviews.length" class="muted">暂无评价，来抢沙发~</p>
            </div>
          </section>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import { sessionState } from '../state/session'

const CATEGORY_LABELS = {
  docking: '分子对接', structure: '蛋白质结构', quality_control: '质控', preprocessing: '预处理',
  alignment: '比对', quantification: '定量', differential_expression: '差异表达',
  transcriptome: '转录组', runtime: '运行时环境', general: '通用',
}

export default {
  name: 'PluginMarket',
  setup() {
    const plugins = ref([])
    const categories = ref([])
    const search = ref('')
    const category = ref('')
    const sort = ref('newest')
    const viewFilter = ref('')
    const loading = ref(false)
    const checkingUpdates = ref(false)
    const updateNotice = ref([])

    const selected = ref(null)
    const detailRating = ref({})
    const reviews = ref([])
    const newRating = ref(5)
    const newComment = ref('')
    const depsResult = ref(null)
    const showVersions = ref(false)
    const note = ref('')
    const noteType = ref('ok')
    const deployPlan = ref(null)
    const planVisible = ref(false)
    const deployResult = ref(null)
    const deployBusy = ref(false)
    const platform = ref(null)
    const platformBusy = ref(false)
    const biocondaPackages = ref('fastqc, samtools, bwa, fastp, bowtie2')
    const catalogBusy = ref(false)
    const catalogStatus = ref('')
    const isAdmin = computed(() => sessionState.user?.role === 'admin')

    const LIFECYCLE_LABELS = {
      discovered: '可发现', selected: '已选择', deploying: '部署中', deployed: '已部署',
      verified: '已验证', enabled: '已启用', disabled: '已停用', error: '异常',
      deselected: '未选择', uninstalled: '已移除',
    }
    const lifecycleLabel = (state) => LIFECYCLE_LABELS[state] || state || '可发现'
    const backendLabel = (backend) => ({
      isolated_conda: 'Conda 隔离环境', python_venv: 'Python venv', wsl2: 'WSL2',
      container_docker: 'Docker', container_podman: 'Podman',
      container_apptainer: 'Apptainer', container_singularity: 'Singularity',
      nextflow: 'Nextflow', snakemake: 'Snakemake',
    }[backend] || backend)

    const categoryLabel = (c) => CATEGORY_LABELS[c] || c
    const iconFor = (p) => {
      if (p.category === 'docking') return '🔬'
      if (p.category === 'structure') return '🧊'
      if (p.category === 'runtime') return '⚙️'
      return '🧬'
    }
    const methodLabel = (m) => ({
      conda: 'Conda 自动安装', pip: 'pip 自动安装', binary: '下载安装包', manual: '手动安装引导',
    }[m?.method] || '手动安装引导')

    const fetchPlugins = async () => {
      loading.value = true
      try {
        const params = {}
        if (search.value) params.search = search.value
        if (category.value) params.category = category.value
        if (sort.value) params.sort = sort.value
        if (viewFilter.value === 'installed') params.installed_only = true
        if (viewFilter.value === 'update') params.update_available_only = true
        const res = await axios.get('/api/v1/plugins/', { params })
        plugins.value = viewFilter.value === 'selected'
          ? res.data.filter(item => item.is_selected)
          : res.data
      } finally {
        loading.value = false
      }
    }

    const fetchCategories = async () => {
      const res = await axios.get('/api/v1/plugins/categories')
      categories.value = res.data
    }

    const checkUpdates = async () => {
      checkingUpdates.value = true
      try {
        const res = await axios.get('/api/v1/plugins/updates')
        updateNotice.value = res.data.updates
        if (!updateNotice.value.length) setNote('所有已安装工具均为最新版本', 'ok')
      } finally {
        checkingUpdates.value = false
      }
    }

    const openFirstUpdate = async () => {
      if (!updateNotice.value.length) return
      const u = updateNotice.value[0]
      const all = await axios.get('/api/v1/plugins/')
      const p = all.data.find(x => x.id === u.plugin_id)
      if (p) {
        await openDetail(p)
        await upgrade()
      }
    }

    const setNote = (msg, type = 'ok') => {
      note.value = msg
      noteType.value = type
      setTimeout(() => { note.value = '' }, 6000)
    }

    const fetchPlatform = async (deep = false) => {
      platformBusy.value = true
      try {
        const res = await axios.get('/api/v1/plugins/platform/capabilities', { params: { deep } })
        platform.value = res.data
      } catch (e) {
        setNote('运行环境检测失败: ' + (e.response?.data?.detail || e.message), 'err')
      } finally {
        platformBusy.value = false
      }
    }

    const syncBioconda = async () => {
      const packages = biocondaPackages.value.split(',').map(item => item.trim().toLowerCase()).filter(Boolean)
      if (!packages.length) {
        catalogStatus.value = '请至少输入一个包名'
        return
      }
      catalogBusy.value = true
      catalogStatus.value = ''
      try {
        const res = await axios.post('/api/v1/plugins/catalogs/bioconda/sync', {
          packages,
          subdirs: ['linux-64', 'noarch'],
          allow_cached_on_error: true,
        })
        catalogStatus.value = `同步完成：新增 ${res.data.imported}，更新 ${res.data.updated}，未找到 ${res.data.missing.length}；缓存状态 ${res.data.cache_status}`
        await Promise.all([fetchPlugins(), fetchCategories()])
      } catch (e) {
        catalogStatus.value = '同步失败: ' + (e.response?.data?.detail || e.message)
      } finally {
        catalogBusy.value = false
      }
    }

    const openDetail = async (plugin) => {
      selected.value = null
      planVisible.value = false
      depsResult.value = null
      showVersions.value = false
      note.value = ''
      try {
        const res = await axios.get(`/api/v1/plugins/${plugin.id}`)
        selected.value = res.data
        detailRating.value = res.data.rating_summary || {}
        const rv = await axios.get(`/api/v1/plugins/${plugin.id}/reviews`)
        reviews.value = rv.data.reviews
      } catch (e) {
        setNote('加载详情失败: ' + (e.response?.data?.detail || e.message), 'err')
      }
    }

    const refreshDetail = async () => {
      if (!selected.value) return
      const res = await axios.get(`/api/v1/plugins/${selected.value.id}`)
      selected.value = res.data
      detailRating.value = res.data.rating_summary || {}
      const rv = await axios.get(`/api/v1/plugins/${selected.value.id}/reviews`)
      reviews.value = rv.data.reviews
      fetchPlugins()
    }

    const deployTool = async (simulate) => {
      if (!selected.value) return
      deployBusy.value = true
      try {
        const res = await axios.post(`/api/v1/plugins/${selected.value.id}/deploy`,
          { simulate: simulate })
        deployResult.value = res.data
        deployPlan.value = res.data
        planVisible.value = true
        if (res.data.ok) {
          if (simulate) {
            setNote('部署计划已生成，请查看执行步骤（模拟模式不会改动系统）', 'ok')
          } else {
            setNote('部署完成！' + (res.data.deployed_version ? ' 已安装 v' + res.data.deployed_version : ''), 'ok')
            await refreshDetail()
          }
        } else {
          setNote('部署未完成: ' + res.data.message, 'err')
        }
      } catch (e) {
        setNote('部署请求失败: ' + (e.response?.data?.detail || e.message), 'err')
      } finally {
        deployBusy.value = false
      }
    }

    const selectTool = async () => {
      if (!selected.value) return
      try {
        await axios.post('/api/v1/plugins/install', {
          plugin_id: selected.value.id,
          version: selected.value.version,
          config: {},
        })
        setNote('已加入工具清单；尚未部署软件', 'ok')
        await refreshDetail()
      } catch (e) {
        setNote('加入工具清单失败: ' + (e.response?.data?.detail || e.message), 'err')
      }
    }

    const setEnabled = async (enabled) => {
      if (!selected.value) return
      try {
        await axios.post(`/api/v1/plugins/${selected.value.id}/${enabled ? 'enable' : 'disable'}`)
        setNote(enabled ? '工具已启用' : '工具已停用', 'ok')
        await refreshDetail()
      } catch (e) {
        setNote('状态切换失败: ' + (e.response?.data?.detail || e.message), 'err')
      }
    }

    const verifyInstall = async () => {
      if (!selected.value) return
      try {
        const res = await axios.post(`/api/v1/plugins/${selected.value.id}/verify`)
        const v = res.data
        setNote(v.found ? `✓ 隔离环境验证通过: ${v.version || '未知版本'}` : `✗ 验证失败: ${v.reason || '未检测到隔离环境'}`, v.found ? 'ok' : 'err')
        await refreshDetail()
      } catch (e) {
        setNote('验证失败: ' + (e.response?.data?.detail || e.message), 'err')
      }
    }

    const upgrade = async () => {
      if (!selected.value) return
      try {
        const res = await axios.post(`/api/v1/plugins/${selected.value.id}/upgrade`)
        setNote(res.data.message, res.data.upgraded ? 'ok' : 'warn')
        await refreshDetail()
      } catch (e) {
        setNote('升级失败: ' + (e.response?.data?.detail || e.message), 'err')
      }
    }

    const switchVersion = async (version) => {
      if (!selected.value) return
      try {
        await axios.post(`/api/v1/plugins/${selected.value.id}/versions/${version}/switch`)
        setNote(`已切换至 v${version}`, 'ok')
        await refreshDetail()
      } catch (e) {
        setNote('切换失败: ' + (e.response?.data?.detail || e.message), 'err')
      }
    }

    const resolveDeps = async () => {
      if (!selected.value) return
      try {
        const res = await axios.get(`/api/v1/plugins/${selected.value.id}/dependencies`)
        depsResult.value = res.data
      } catch (e) {
        setNote('依赖解析失败: ' + (e.response?.data?.detail || e.message), 'err')
      }
    }

    const submitReview = async () => {
      if (!selected.value) return
      try {
        await axios.post(`/api/v1/plugins/${selected.value.id}/reviews`,
          { rating: newRating.value, comment: newComment.value })
        setNote('评价已提交，感谢反馈！', 'ok')
        newComment.value = ''
        await refreshDetail()
      } catch (e) {
        setNote('提交失败: ' + (e.response?.data?.detail || e.message), 'err')
      }
    }

    const deselectTool = async () => {
      if (!selected.value || !confirm(`确定将 ${selected.value.name} 移出工具清单？`)) return
      try {
        await axios.delete(`/api/v1/plugins/${selected.value.id}`)
        setNote('已移出工具清单；未改动本机软件', 'ok')
        await refreshDetail()
      } catch (e) {
        setNote('移出失败: ' + (e.response?.data?.detail || e.message), 'err')
      }
    }

    const removeDeployment = async () => {
      if (!selected.value || !confirm(`确定删除 ${selected.value.name} 的受管隔离环境？此操作不可撤销。`)) return
      try {
        const res = await axios.delete(`/api/v1/plugins/${selected.value.id}/deployment`)
        setNote(res.data.removed ? '隔离环境已删除' : '环境目录已不存在，状态已清理', 'ok')
        await refreshDetail()
      } catch (e) {
        setNote('环境移除失败: ' + (e.response?.data?.detail || e.message), 'err')
      }
    }

    onMounted(() => { fetchPlugins(); fetchCategories(); fetchPlatform(false) })

    return {
      plugins, categories, search, category, sort, viewFilter, loading,
      checkingUpdates, updateNotice, selected, detailRating, reviews,
      newRating, newComment, depsResult, showVersions, note, noteType,
      deployPlan, planVisible, deployResult, deployBusy,
      platform, platformBusy, biocondaPackages, catalogBusy, catalogStatus, isAdmin,
      categoryLabel, iconFor, methodLabel, fetchPlugins, fetchCategories,
      lifecycleLabel, backendLabel, fetchPlatform, syncBioconda,
      checkUpdates, openFirstUpdate, openDetail, selectTool, deployTool, verifyInstall,
      setEnabled, upgrade, switchVersion, resolveDeps, submitReview,
      deselectTool, removeDeployment,
    }
  }
}
</script>

<style scoped>
.market-container { max-width: 1200px; margin: 0 auto; }
.market-header { margin-bottom: 24px; }
.market-header h1 { font-size: 26px; margin-bottom: 4px; }
.subtitle { color: #888; margin-bottom: 16px; }
.toolbar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.search-input { padding: 9px 14px; border: 1px solid #ddd; border-radius: 8px; width: 260px; font-size: 14px; }
.filter-select { padding: 9px; border: 1px solid #ddd; border-radius: 8px; background: white; }
.btn { padding: 9px 16px; border: none; border-radius: 8px; cursor: pointer; font-size: 13px; }
.btn-check { background: #fff; border: 1px solid #1976d2; color: #1976d2; }
.btn-check:disabled { opacity: .5; }
.btn-primary { background: #1976d2; color: white; }
.btn-success { background: #d32f2f; color: white; }
.btn-danger { background: #fff1f0; color: #b42318; border: 1px solid #fecdca; }
.btn:disabled { cursor: not-allowed; opacity: .55; }
.btn-warn { background: #f57c00; color: white; }
.btn-link-a { background: #f5f7fa; color: #1976d2; text-decoration: none; }
.btn-mini { background: #f0f0f0; padding: 4px 10px; font-size: 12px; border-radius: 6px; border: none; cursor: pointer; }
.btn-detail { background: #1976d2; color: white; padding: 6px 14px; font-size: 12px; }
.update-banner { margin-top: 12px; padding: 10px 14px; background: #fff3e0; border-radius: 8px; color: #e65100; display: flex; justify-content: space-between; align-items: center; }
.btn-link { background: none; border: none; color: #e65100; text-decoration: underline; cursor: pointer; }

.runtime-panel { background: linear-gradient(135deg, #f7fbff, #f4f7fb); border: 1px solid #d7e6f5; border-radius: 12px; padding: 16px; margin-bottom: 20px; }
.runtime-head { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
.runtime-head h2 { font-size: 16px; margin: 0 0 3px; }
.runtime-head p { color: #667085; font-size: 12px; margin: 0; }
.backend-list { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 12px; }
.backend-chip { background: #e8f3ff; color: #175cd3; border: 1px solid #b2ddff; border-radius: 999px; padding: 4px 10px; font-size: 12px; }
.limitations { margin: 10px 0 0; padding-left: 20px; color: #9a6700; font-size: 12px; line-height: 1.6; }
.catalog-sync { border-top: 1px solid #d7e6f5; margin-top: 12px; padding-top: 12px; }
.catalog-sync label { display: block; font-size: 12px; color: #475467; font-weight: 600; margin-bottom: 7px; }
.catalog-row { display: flex; gap: 8px; align-items: center; }
.catalog-row .search-input { flex: 1; width: auto; }
.catalog-status { color: #475467; font-size: 12px; margin: 8px 0 0; }

.plugin-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 16px; }
.plugin-card { background: white; border-radius: 12px; padding: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); cursor: pointer; transition: transform .15s; border: 1px solid #eee; }
.plugin-card:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0,0,0,0.12); }
.card-top { display: flex; align-items: flex-start; gap: 10px; }
.plugin-icon { font-size: 30px; }
.card-meta { flex: 1; }
.card-meta h3 { margin: 0 0 2px; font-size: 16px; }
.ver { color: #999; font-size: 12px; margin: 0; }
.badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; background: #f57c00; color: white; vertical-align: middle; }
.badge-blue { background: #1976d2; }
.badge-green { background: #388e3c; }
.installed-flag { color: #388e3c; font-size: 12px; font-weight: 600; }
.installed-flag.state-discovered, .installed-flag.state-deselected, .installed-flag.state-uninstalled { color: #667085; }
.installed-flag.state-selected { color: #175cd3; }
.installed-flag.state-deploying { color: #b54708; }
.installed-flag.state-error { color: #b42318; }
.desc { color: #555; font-size: 13px; line-height: 1.5; margin: 10px 0; min-height: 38px; }
.tags { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 10px; }
.tag { background: #f0f0f0; padding: 2px 8px; border-radius: 10px; font-size: 11px; color: #555; }
.card-foot { display: flex; align-items: center; gap: 12px; border-top: 1px solid #f0f0f0; padding-top: 10px; }
.rating { color: #f57c00; font-size: 13px; }
.rating em, .downloads { color: #999; font-style: normal; font-size: 12px; }
.downloads { margin-left: auto; }
.loading, .empty { text-align: center; color: #999; padding: 60px 0; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.45); display: flex; justify-content: center; align-items: flex-start; padding: 30px 16px; z-index: 100; overflow-y: auto; }
.modal { background: white; border-radius: 14px; width: 860px; max-width: 100%; padding: 24px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
.modal-header { display: flex; justify-content: space-between; align-items: flex-start; }
.modal-header h2 { margin: 0 0 4px; font-size: 22px; }
.ver-big { color: #1976d2; font-size: 14px; }
.cat { color: #777; font-size: 13px; margin: 0; }
.modal-close { background: none; border: none; font-size: 20px; cursor: pointer; color: #999; }
.modal-actions { display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0 4px; }
.lifecycle-pill { display: inline-flex; align-items: center; background: #eef4ff; color: #3538cd; border-radius: 999px; padding: 7px 11px; font-size: 12px; font-weight: 600; }
.digest { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; }
.note { padding: 10px 14px; border-radius: 8px; margin: 10px 0; font-size: 13px; }
.note.ok { background: #e8f5e9; color: #2e7d32; }
.note.err { background: #fdecea; color: #c62828; }
.note.warn { background: #fff8e1; color: #f57c00; }

.plan-box { background: #f8f9fa; border: 1px solid #e0e0e0; border-radius: 10px; padding: 14px 16px; margin: 12px 0; }
.plan-box h3 { margin: 0 0 10px; font-size: 14px; }
.plan-step { display: flex; gap: 10px; align-items: flex-start; padding: 6px 0; }
.step-icon { font-size: 14px; }
.step-desc { margin: 0; font-size: 13px; }
.step-body code { display: block; background: #263238; color: #aed581; padding: 4px 8px; border-radius: 4px; font-size: 12px; margin-top: 4px; }
.step-err { color: #c62828; margin: 4px 0 0; font-size: 12px; }
.plan-foot { margin-top: 8px; display: flex; align-items: center; gap: 12px; }
.plan-sim { color: #5c6bc0; font-size: 12px; }

.modal-body { margin-top: 8px; }
.section { margin-bottom: 22px; padding-bottom: 16px; border-bottom: 1px solid #f0f0f0; }
.section h3 { font-size: 15px; margin: 0 0 10px; display: flex; align-items: center; gap: 10px; }
.info-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }
.info-grid div { background: #f8f9fa; padding: 8px 12px; border-radius: 8px; }
.info-grid label { display: block; font-size: 11px; color: #999; margin-bottom: 2px; }
.muted { color: #aaa; font-size: 13px; }
.deps-warn { background: #fff3e0; color: #e65100; padding: 8px 12px; border-radius: 8px; font-size: 13px; margin-bottom: 6px; }
.deps-ok { color: #388e3c; font-size: 13px; }
.deps-lists { display: flex; gap: 24px; margin: 10px 0; }
.deps-list { flex: 1; }
.deps-list h4 { font-size: 12px; color: #666; margin: 0 0 6px; }
.chip { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; margin: 0 6px 6px 0; }
.chip em { font-style: normal; opacity: .7; }
.chip-missing { background: #fdecea; color: #c62828; }
.chip-ok { background: #e8f5e9; color: #2e7d32; }
.deps-order { font-size: 13px; color: #555; }
.deps-order code { background: #f0f0f0; padding: 2px 6px; border-radius: 4px; }

.ver-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.ver-table th { text-align: left; color: #999; font-weight: 500; padding: 6px 8px; border-bottom: 1px solid #eee; }
.ver-table td { padding: 8px; border-bottom: 1px solid #f5f5f5; }
.ver-table .cl { max-width: 320px; color: #666; }

.rating-big { color: #f57c00; font-size: 14px; }
.rating-big em { color: #999; font-style: normal; font-size: 12px; }
.rating-dist { max-width: 320px; margin: 8px 0; }
.dist-row { display: flex; align-items: center; gap: 8px; font-size: 12px; margin: 3px 0; }
.dist-label { width: 24px; color: #999; }
.dist-bar { flex: 1; height: 8px; background: #f0f0f0; border-radius: 4px; overflow: hidden; }
.dist-fill { height: 100%; background: #f57c00; border-radius: 4px; }
.dist-num { width: 20px; color: #999; }
.review-form { display: flex; gap: 8px; margin: 10px 0; }
.review-form select { padding: 8px; border: 1px solid #ddd; border-radius: 8px; background: white; }
.review-input { flex: 1; padding: 8px 12px; border: 1px solid #ddd; border-radius: 8px; }
.review-item { padding: 10px 0; border-bottom: 1px solid #f5f5f5; }
.review-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.stars { color: #f57c00; }
.stars em { color: #e0e0e0; font-style: normal; }
.review-date { margin-left: auto; color: #aaa; font-size: 12px; }
.review-item p { margin: 0; color: #444; font-size: 13px; }

@media (max-width: 700px) {
  .runtime-head, .catalog-row { align-items: stretch; flex-direction: column; }
  .search-input { width: 100%; box-sizing: border-box; }
  .modal { padding: 18px; }
  .deps-lists, .review-form { flex-direction: column; }
}
</style>
