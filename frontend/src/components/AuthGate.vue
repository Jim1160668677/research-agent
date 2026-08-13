<template>
  <main class="auth-shell">
    <section class="auth-hero" aria-label="Research Agent introduction">
      <div class="hero-mark">RA</div>
      <p class="eyebrow">RESEARCH AGENT</p>
      <h1>把科研问题变成<br><span>可执行的工作流</span></h1>
      <p class="hero-copy">在一个本地工作台中完成文献检索、数据查询、智能分析和工具编排。</p>
      <div class="capability-list">
        <div><b>01</b><span>智能对话与多智能体协作</span></div>
        <div><b>02</b><span>NCBI 数据与生物信息技能</span></div>
        <div><b>03</b><span>可复用工作流与插件生态</span></div>
      </div>
      <p class="local-note"><span></span>本地服务 · 数据存储在此设备</p>
    </section>

    <section class="auth-panel">
      <form class="auth-card" @submit.prevent="submit">
        <div class="auth-heading">
          <p class="step">{{ mode === 'setup' ? '首次启动' : mode === 'register' ? '创建账户' : '欢迎回来' }}</p>
          <h2>{{ title }}</h2>
          <p>{{ subtitle }}</p>
        </div>

        <div v-if="error" class="form-alert" role="alert">{{ error }}</div>

        <label class="field">
          <span>用户名</span>
          <input v-model.trim="form.username" autocomplete="username" minlength="3" maxlength="50" required placeholder="至少 3 个字符">
        </label>

        <label v-if="mode !== 'login'" class="field">
          <span>邮箱</span>
          <input v-model.trim="form.email" type="email" autocomplete="email" required placeholder="name@laboratory.org">
        </label>

        <label class="field">
          <span>密码</span>
          <div class="password-field">
            <input v-model="form.password" :type="showPassword ? 'text' : 'password'" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" minlength="8" required placeholder="至少 8 个字符">
            <button type="button" class="reveal" @click="showPassword = !showPassword" :aria-label="showPassword ? '隐藏密码' : '显示密码'">{{ showPassword ? '隐藏' : '显示' }}</button>
          </div>
        </label>

        <label v-if="mode !== 'login'" class="field">
          <span>确认密码</span>
          <input v-model="form.confirmPassword" type="password" autocomplete="new-password" minlength="8" required placeholder="再次输入密码">
        </label>

        <button class="primary-action" type="submit" :disabled="submitting">
          <span v-if="submitting" class="spinner"></span>
          {{ submitting ? '正在处理…' : submitLabel }}
        </button>

        <p v-if="mode === 'login' && registrationEnabled" class="switch-mode">
          还没有账户？<button type="button" @click="switchTo('register')">创建账户</button>
        </p>
        <p v-else-if="mode === 'register'" class="switch-mode">
          已有账户？<button type="button" @click="switchTo('login')">返回登录</button>
        </p>

        <p v-if="mode === 'setup'" class="setup-hint">此账户将成为本机管理员。后续可创建普通研究账户。</p>
      </form>
    </section>
  </main>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { apiError, registerUser, sessionState, setupOwner, signIn } from '../state/session'

const submitting = ref(false)
const showPassword = ref(false)
const error = ref('')
const form = reactive({ username: '', email: '', password: '', confirmPassword: '' })
const mode = computed(() => sessionState.mode)
const registrationEnabled = computed(() => sessionState.registrationEnabled)
const title = computed(() => ({
  setup: '创建本机管理员',
  register: '加入研究工作台',
  login: '登录研究工作台',
}[mode.value]))
const subtitle = computed(() => mode.value === 'setup'
  ? '完成一次设置即可开始使用。'
  : '继续你的对话、工具和分析流程。')
const submitLabel = computed(() => ({ setup: '完成设置', register: '创建并登录', login: '登录' }[mode.value]))

function switchTo(next) {
  error.value = ''
  form.password = ''
  form.confirmPassword = ''
  sessionState.mode = next
}

async function submit() {
  error.value = ''
  if (mode.value !== 'login' && form.password !== form.confirmPassword) {
    error.value = '两次输入的密码不一致'
    return
  }
  submitting.value = true
  try {
    if (mode.value === 'setup') {
      await setupOwner({ username: form.username, email: form.email, password: form.password })
    } else if (mode.value === 'register') {
      await registerUser({ username: form.username, email: form.email, password: form.password })
    } else {
      await signIn(form.username, form.password)
    }
  } catch (err) {
    error.value = apiError(err, '登录失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.auth-shell { min-height: 100vh; display: grid; grid-template-columns: minmax(430px, 1.05fr) minmax(480px, .95fr); background: #f8fafc; }
.auth-hero { position: relative; overflow: hidden; display: flex; flex-direction: column; justify-content: center; padding: clamp(52px, 7vw, 108px); color: #e2e8f0; background: radial-gradient(circle at 82% 16%, rgba(37,99,235,.28), transparent 30%), linear-gradient(145deg, #07111f, #10233b 62%, #0c1728); }
.auth-hero::after { content: ''; position: absolute; width: 430px; height: 430px; right: -180px; bottom: -210px; border: 1px solid rgba(96,165,250,.2); border-radius: 50%; box-shadow: 0 0 0 70px rgba(96,165,250,.04), 0 0 0 140px rgba(96,165,250,.03); }
.hero-mark { width: 54px; height: 54px; display: grid; place-items: center; margin-bottom: 36px; border: 1px solid rgba(147,197,253,.36); border-radius: 15px; color: #fff; font-weight: 750; letter-spacing: -.04em; background: linear-gradient(145deg, #2563eb, #0891b2); box-shadow: 0 18px 50px rgba(37,99,235,.28); }
.eyebrow { margin: 0 0 18px; color: #60a5fa; font-size: 12px; font-weight: 750; letter-spacing: .22em; }
h1 { margin: 0; max-width: 650px; font-size: clamp(39px, 4.5vw, 66px); line-height: 1.12; letter-spacing: -.055em; color: #f8fafc; }
h1 span { color: #7dd3fc; }
.hero-copy { max-width: 560px; margin: 28px 0 42px; color: #9fb0c6; font-size: 17px; line-height: 1.8; }
.capability-list { display: grid; gap: 16px; max-width: 510px; }
.capability-list div { display: flex; align-items: center; gap: 18px; padding-bottom: 16px; border-bottom: 1px solid rgba(148,163,184,.14); color: #cbd5e1; }
.capability-list b { color: #60a5fa; font: 700 11px/1 ui-monospace, monospace; letter-spacing: .12em; }
.local-note { display: flex; align-items: center; gap: 9px; margin: 38px 0 0; color: #71839a; font-size: 12px; }
.local-note span { width: 7px; height: 7px; border-radius: 50%; background: #34d399; box-shadow: 0 0 0 4px rgba(52,211,153,.1); }
.auth-panel { display: grid; place-items: center; padding: 48px clamp(36px, 6vw, 90px); }
.auth-card { width: min(100%, 430px); }
.auth-heading { margin-bottom: 32px; }
.auth-heading .step { margin: 0 0 8px; color: #2563eb; font-size: 12px; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; }
.auth-heading h2 { margin: 0 0 9px; color: #0f172a; font-size: 30px; letter-spacing: -.035em; }
.auth-heading > p:last-child { margin: 0; color: #64748b; line-height: 1.6; }
.form-alert { margin-bottom: 18px; padding: 11px 13px; border: 1px solid #fecaca; border-radius: 10px; color: #b91c1c; background: #fff7f7; font-size: 13px; line-height: 1.5; }
.field { display: grid; gap: 8px; margin-bottom: 18px; color: #334155; font-size: 13px; font-weight: 650; }
.field input { width: 100%; height: 46px; padding: 0 13px; border: 1px solid #cbd5e1; border-radius: 10px; outline: none; color: #0f172a; background: #fff; font: inherit; font-weight: 450; transition: border-color .15s, box-shadow .15s; }
.field input:focus { border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59,130,246,.13); }
.password-field { position: relative; }
.password-field input { padding-right: 62px; }
.reveal { position: absolute; top: 50%; right: 8px; transform: translateY(-50%); border: 0; padding: 6px; color: #64748b; background: transparent; cursor: pointer; font-size: 12px; }
.primary-action { width: 100%; height: 48px; display: flex; align-items: center; justify-content: center; gap: 9px; margin-top: 8px; border: 0; border-radius: 10px; color: #fff; background: #2563eb; box-shadow: 0 10px 25px rgba(37,99,235,.2); font-weight: 700; cursor: pointer; }
.primary-action:hover:not(:disabled) { background: #1d4ed8; }
.primary-action:disabled { opacity: .65; cursor: wait; }
.spinner { width: 16px; height: 16px; border: 2px solid rgba(255,255,255,.45); border-top-color: white; border-radius: 50%; animation: spin .75s linear infinite; }
.switch-mode, .setup-hint { margin: 22px 0 0; text-align: center; color: #64748b; font-size: 13px; }
.switch-mode button { border: 0; padding: 0 3px; color: #2563eb; background: transparent; font-weight: 700; cursor: pointer; }
.setup-hint { padding: 12px; border-radius: 8px; background: #eef6ff; color: #475569; line-height: 1.55; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .auth-shell { grid-template-columns: 1fr; } .auth-hero { display: none; } .auth-panel { min-height: 100vh; } }
</style>
