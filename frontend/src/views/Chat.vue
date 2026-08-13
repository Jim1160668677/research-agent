<template>
  <div class="chat-workspace">
    <aside class="conversation-panel">
      <button class="new-chat" @click="newConversation"><span>＋</span> 新建对话</button>
      <div class="history-heading"><span>最近对话</span><button @click="loadSessions" title="刷新">↻</button></div>
      <div v-if="sessionsLoading" class="history-skeleton"><i v-for="n in 4" :key="n"></i></div>
      <div v-else-if="sessions.length === 0" class="history-empty">对话会自动保存在此设备</div>
      <div v-else class="history-list">
        <button v-for="item in sessions" :key="item.session_id" class="history-item" :class="{ active: item.session_id === sessionId }" @click="openConversation(item.session_id)">
          <span class="history-icon">◫</span>
          <span class="history-copy"><b>{{ item.title }}</b><small>{{ formatTime(item.updated_at) }} · {{ item.message_count }} 条消息</small></span>
          <span class="delete-chat" title="删除" @click.stop="removeConversation(item.session_id)">×</span>
        </button>
      </div>
    </aside>

    <section class="conversation-main">
      <header class="conversation-header">
        <div>
          <h1>{{ sessionId ? currentSessionTitle : '新对话' }}</h1>
          <p><span class="live-dot"></span>科研助手已就绪</p>
        </div>
        <div class="model-badge">{{ providerLabel }}</div>
      </header>

      <div ref="messagesRef" class="messages" aria-live="polite">
        <div v-if="messages.length === 0" class="welcome-state">
          <div class="assistant-mark">RA</div>
          <p class="welcome-kicker">RESEARCH COPILOT</p>
          <h2>今天想解决什么科研问题？</h2>
          <p class="welcome-copy">我可以帮你检索文献、规划实验、查询生物数据库，或把复杂任务拆成可复用的分析流程。</p>
          <div class="prompt-grid">
            <button v-for="prompt in starterPrompts" :key="prompt.title" @click="choosePrompt(prompt.text)">
              <span>{{ prompt.icon }}</span><b>{{ prompt.title }}</b><small>{{ prompt.description }}</small><i>↗</i>
            </button>
          </div>
        </div>

        <article v-for="(message, index) in messages" :key="`${message.role}-${index}`" class="message" :class="message.role">
          <div class="message-avatar">{{ message.role === 'user' ? userInitial : 'RA' }}</div>
          <div class="message-body">
            <div class="message-meta"><strong>{{ message.role === 'user' ? '你' : '科研助手' }}</strong><span>{{ message.time || '' }}</span></div>
            <div class="message-content">{{ message.content }}</div>
            <div v-if="message.tools?.length" class="tool-list">
              <span v-for="tool in message.tools" :key="tool.name">已使用 · {{ tool.name }}</span>
            </div>
          </div>
        </article>

        <article v-if="sending" class="message assistant pending">
          <div class="message-avatar">RA</div>
          <div class="message-body">
            <div class="message-meta"><strong>科研助手</strong><span>正在分析</span></div>
            <div class="thinking"><i></i><i></i><i></i></div>
          </div>
        </article>
      </div>

      <footer class="composer-wrap">
        <div v-if="suggestions.length" class="suggestion-row">
          <button v-for="suggestion in suggestions" :key="suggestion.text" @click="choosePrompt(suggestion.text)">{{ suggestion.text }}</button>
        </div>
        <div class="composer" :class="{ focused: composerFocused }">
          <textarea ref="composerRef" v-model="input" rows="1" maxlength="12000" placeholder="输入科研问题，Enter 发送，Shift + Enter 换行" @focus="composerFocused = true" @blur="composerFocused = false" @keydown.enter.exact.prevent="send" @input="resizeComposer"></textarea>
          <div class="composer-bottom">
            <span>回答可能存在误差，请核验关键结论与来源</span>
            <button class="send-button" :disabled="!input.trim() || sending" @click="send" aria-label="发送消息">↑</button>
          </div>
        </div>
      </footer>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'
import { useRoute } from 'vue-router'
import { apiError, sessionState } from '../state/session'

const sessions = ref([])
const sessionsLoading = ref(true)
const sessionId = ref(null)
const messages = ref([])
const input = ref('')
const sending = ref(false)
const suggestions = ref([])
const messagesRef = ref(null)
const composerRef = ref(null)
const composerFocused = ref(false)
const providerLabel = ref('自动选择模型')
const route = useRoute()
const starterPrompts = [
  { icon: '⌕', title: '检索研究证据', description: '围绕主题搜索 PubMed 文献', text: '请帮我检索并梳理 CRISPR 基因编辑的近期研究方向' },
  { icon: '⌁', title: '设计分析流程', description: '把研究目标拆成可执行步骤', text: '请为 RNA-seq 差异表达研究设计一个完整分析流程' },
  { icon: '◎', title: '查询生物数据', description: '定位 NCBI 序列与数据集', text: '如何在 NCBI 中系统查找一个基因的序列和相关测序数据？' },
  { icon: '△', title: '规划实验方案', description: '评估方法、对照与风险', text: '请帮我检查一个实验方案应包含哪些对照和统计假设' },
]

const userInitial = computed(() => (sessionState.user?.username || 'U').slice(0, 1).toUpperCase())
const currentSessionTitle = computed(() => sessions.value.find(item => item.session_id === sessionId.value)?.title || '科研对话')

function formatTime(value) {
  if (!value) return '刚刚'
  const date = new Date(value)
  const today = new Date()
  if (date.toDateString() === today.toDateString()) return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

async function loadSessions() {
  sessionsLoading.value = true
  try {
    const response = await axios.get('/api/v1/agents/sessions')
    sessions.value = response.data.sessions || []
  } finally {
    sessionsLoading.value = false
  }
}

async function openConversation(id) {
  if (sending.value) return
  try {
    const response = await axios.get(`/api/v1/agents/sessions/${id}`)
    const conversation = response.data.session
    sessionId.value = conversation.session_id
    providerLabel.value = conversation.model || conversation.provider || '本地规则引擎'
    messages.value = (conversation.messages || []).map(item => ({ ...item }))
    suggestions.value = []
    await scrollToBottom()
  } catch (error) {
    messages.value = [{ role: 'error', content: apiError(error, '无法加载对话') }]
  }
}

function newConversation() {
  if (sending.value) return
  sessionId.value = null
  messages.value = []
  suggestions.value = []
  providerLabel.value = '自动选择模型'
  nextTick(() => composerRef.value?.focus())
}

async function removeConversation(id) {
  try {
    await axios.delete(`/api/v1/agents/sessions/${id}`)
    if (sessionId.value === id) newConversation()
    await loadSessions()
  } catch (error) {
    messages.value.push({ role: 'error', content: apiError(error, '删除对话失败') })
  }
}

function choosePrompt(text) {
  input.value = text
  nextTick(() => composerRef.value?.focus())
}

function resizeComposer() {
  const element = composerRef.value
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${Math.min(element.scrollHeight, 160)}px`
}

async function scrollToBottom() {
  await nextTick()
  if (messagesRef.value) messagesRef.value.scrollTop = messagesRef.value.scrollHeight
}

async function send() {
  const content = input.value.trim()
  if (!content || sending.value) return
  messages.value.push({ role: 'user', content, time: '刚刚' })
  input.value = ''
  suggestions.value = []
  sending.value = true
  resizeComposer()
  await scrollToBottom()
  try {
    const response = await axios.post('/api/v1/agents/chat', {
      content,
      session_id: sessionId.value,
    })
    sessionId.value = response.data.session_id
    const llm = response.data.metadata?.llm || {}
    providerLabel.value = llm.fallback ? '本地规则引擎' : (llm.model || 'AI 模型')
    messages.value.push({
      role: 'assistant',
      content: response.data.message,
      time: '刚刚',
      tools: response.data.tools_used || [],
    })
    suggestions.value = response.data.suggestions || []
    await loadSessions()
  } catch (error) {
    messages.value.push({ role: 'error', content: apiError(error, '处理请求时发生错误') })
  } finally {
    sending.value = false
    await scrollToBottom()
    composerRef.value?.focus()
  }
}

function focusComposer() { composerRef.value?.focus() }

onMounted(async () => {
  await loadSessions()
  if (typeof route.query.session === 'string') {
    await openConversation(route.query.session)
  } else if (typeof route.query.prompt === 'string') {
    input.value = route.query.prompt
    await nextTick()
    composerRef.value?.focus()
  }
  window.addEventListener('research-agent:focus-composer', focusComposer)
})
onBeforeUnmount(() => window.removeEventListener('research-agent:focus-composer', focusComposer))
</script>

<style scoped>
.chat-workspace { height: calc(100vh - 135px); min-height: 560px; display: grid; grid-template-columns: 232px minmax(0, 1fr); overflow: hidden; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; box-shadow: 0 5px 24px rgba(15,23,42,.04); }
.conversation-panel { min-width: 0; display: flex; flex-direction: column; padding: 14px 11px; border-right: 1px solid #e8edf3; background: #f8fafc; }
.new-chat { height: 39px; display: flex; align-items: center; justify-content: center; gap: 8px; border: 1px solid #cbd5e1; border-radius: 9px; color: #1e40af; background: #fff; font-size: 12px; font-weight: 700; cursor: pointer; }
.new-chat:hover { border-color: #93c5fd; background: #eff6ff; }
.new-chat span { font-size: 17px; font-weight: 400; }
.history-heading { display: flex; align-items: center; justify-content: space-between; margin: 21px 8px 8px; color: #94a3b8; font-size: 10px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
.history-heading button { border: 0; color: #94a3b8; background: transparent; cursor: pointer; }
.history-list { min-height: 0; overflow-y: auto; }
.history-item { width: 100%; min-height: 55px; display: flex; align-items: center; gap: 9px; border: 0; border-radius: 8px; padding: 8px; color: #475569; background: transparent; text-align: left; cursor: pointer; }
.history-item:hover, .history-item.active { background: #eaf1fb; }
.history-item.active { color: #1d4ed8; }
.history-icon { width: 20px; flex: 0 0 auto; text-align: center; color: #94a3b8; }
.history-copy { min-width: 0; flex: 1; display: grid; gap: 4px; }
.history-copy b { overflow: hidden; font-size: 11px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.history-copy small { color: #94a3b8; font-size: 9px; white-space: nowrap; }
.delete-chat { opacity: 0; padding: 3px; color: #94a3b8; font-size: 16px; }
.history-item:hover .delete-chat { opacity: 1; }
.delete-chat:hover { color: #dc2626; }
.history-empty { margin: 24px 13px; color: #94a3b8; font-size: 11px; line-height: 1.6; text-align: center; }
.history-skeleton { display: grid; gap: 9px; padding: 4px; }
.history-skeleton i { height: 49px; border-radius: 8px; background: linear-gradient(90deg, #edf2f7, #f8fafc, #edf2f7); background-size: 200% 100%; animation: shimmer 1.3s infinite; }
.conversation-main { min-width: 0; display: flex; flex-direction: column; }
.conversation-header { height: 66px; flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; padding: 0 21px; border-bottom: 1px solid #edf2f7; }
.conversation-header h1 { margin: 0 0 4px; color: #1e293b; font-size: 13px; }
.conversation-header p { display: flex; align-items: center; gap: 6px; margin: 0; color: #94a3b8; font-size: 10px; }
.live-dot { width: 6px; height: 6px; border-radius: 50%; background: #22c55e; }
.model-badge { border: 1px solid #dbe5f0; border-radius: 16px; padding: 5px 10px; color: #64748b; background: #f8fafc; font-size: 10px; }
.messages { flex: 1; min-height: 0; overflow-y: auto; scroll-behavior: smooth; }
.welcome-state { max-width: 720px; margin: 0 auto; padding: clamp(55px, 9vh, 100px) 28px 40px; text-align: center; }
.assistant-mark { width: 44px; height: 44px; display: grid; place-items: center; margin: 0 auto 17px; border-radius: 13px; color: #fff; background: linear-gradient(145deg, #2563eb, #0891b2); box-shadow: 0 10px 25px rgba(37,99,235,.18); font-size: 11px; font-weight: 800; }
.welcome-kicker { margin: 0 0 8px; color: #3b82f6; font-size: 9px; font-weight: 800; letter-spacing: .16em; }
.welcome-state h2 { margin: 0; color: #0f172a; font-size: 23px; letter-spacing: -.025em; }
.welcome-copy { max-width: 570px; margin: 13px auto 26px; color: #64748b; font-size: 12px; line-height: 1.75; }
.prompt-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; text-align: left; }
.prompt-grid button { position: relative; min-height: 82px; display: grid; grid-template-columns: 27px 1fr; grid-template-rows: auto auto; column-gap: 10px; border: 1px solid #e2e8f0; border-radius: 10px; padding: 13px; color: #475569; background: #fff; cursor: pointer; }
.prompt-grid button:hover { border-color: #bfdbfe; background: #f8fbff; transform: translateY(-1px); }
.prompt-grid button > span { grid-row: 1 / 3; width: 27px; height: 27px; display: grid; place-items: center; border-radius: 8px; color: #2563eb; background: #eff6ff; }
.prompt-grid b { align-self: end; color: #334155; font-size: 11px; }
.prompt-grid small { align-self: start; margin-top: 4px; color: #94a3b8; font-size: 9px; }
.prompt-grid i { position: absolute; right: 11px; top: 10px; color: #cbd5e1; font-style: normal; }
.message { display: grid; grid-template-columns: 35px minmax(0, 1fr); gap: 12px; max-width: 820px; margin: 0 auto; padding: 21px 34px; border-bottom: 1px solid #f1f5f9; }
.message.user { background: #fbfcfe; }
.message-avatar { width: 31px; height: 31px; display: grid; place-items: center; border-radius: 9px; color: #fff; background: linear-gradient(145deg, #2563eb, #0891b2); font-size: 9px; font-weight: 800; }
.message.user .message-avatar { color: #334155; background: #e2e8f0; }
.message.error .message-avatar { color: #b91c1c; background: #fee2e2; }
.message.error .message-avatar::after { content: '!'; }
.message.error .message-avatar { font-size: 0; }
.message-meta { display: flex; align-items: baseline; gap: 9px; margin: 1px 0 8px; }
.message-meta strong { color: #334155; font-size: 11px; }
.message-meta span { color: #a1afc0; font-size: 9px; }
.message-content { color: #364152; font-size: 12px; line-height: 1.78; white-space: pre-wrap; overflow-wrap: anywhere; }
.message.error .message-content { color: #b91c1c; }
.tool-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.tool-list span { border: 1px solid #dbeafe; border-radius: 13px; padding: 4px 8px; color: #1d4ed8; background: #eff6ff; font-size: 9px; }
.thinking { display: flex; gap: 4px; padding: 7px 0; }
.thinking i { width: 5px; height: 5px; border-radius: 50%; background: #60a5fa; animation: bounce 1s infinite alternate; }
.thinking i:nth-child(2) { animation-delay: .18s; }.thinking i:nth-child(3) { animation-delay: .36s; }
.composer-wrap { flex: 0 0 auto; padding: 8px 22px 17px; background: linear-gradient(transparent, #fff 22%); }
.suggestion-row { display: flex; gap: 6px; overflow-x: auto; max-width: 780px; margin: 0 auto 7px; }
.suggestion-row button { flex: 0 0 auto; border: 1px solid #dbeafe; border-radius: 16px; padding: 5px 10px; color: #1d4ed8; background: #eff6ff; font-size: 9px; cursor: pointer; }
.composer { max-width: 780px; margin: 0 auto; border: 1px solid #cbd5e1; border-radius: 12px; background: #fff; box-shadow: 0 8px 25px rgba(15,23,42,.07); transition: border-color .15s, box-shadow .15s; }
.composer.focused { border-color: #60a5fa; box-shadow: 0 0 0 3px rgba(59,130,246,.1), 0 10px 30px rgba(15,23,42,.08); }
.composer textarea { width: 100%; min-height: 42px; max-height: 160px; display: block; resize: none; overflow-y: auto; border: 0; outline: 0; padding: 12px 14px 4px; color: #273449; background: transparent; font-size: 12px; line-height: 1.55; }
.composer textarea::placeholder { color: #a8b4c3; }
.composer-bottom { min-height: 37px; display: flex; align-items: center; justify-content: space-between; padding: 3px 7px 7px 14px; }
.composer-bottom > span { color: #a3afbd; font-size: 8px; }
.send-button { width: 29px; height: 29px; border: 0; border-radius: 8px; color: #fff; background: #2563eb; cursor: pointer; font-size: 17px; line-height: 1; }
.send-button:disabled { color: #94a3b8; background: #e2e8f0; cursor: default; }
@keyframes shimmer { to { background-position: -200% 0; } }
@keyframes bounce { to { transform: translateY(-4px); opacity: .45; } }
@media (max-width: 980px) { .chat-workspace { grid-template-columns: 190px minmax(0, 1fr); } .prompt-grid { grid-template-columns: 1fr; } }
</style>
