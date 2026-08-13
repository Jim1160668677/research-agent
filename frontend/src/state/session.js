import { computed, reactive } from 'vue'
import axios from 'axios'

const TOKEN_KEY = 'research-agent.access-token'
const USER_KEY = 'research-agent.user'

export const sessionState = reactive({
  booting: true,
  initialized: null,
  registrationEnabled: false,
  user: null,
  mode: 'login',
  error: '',
  server: 'checking',
})

function storedToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || ''
  } catch (_) {
    return ''
  }
}

function persistSession(token, user) {
  sessionState.user = user
  sessionState.error = ''
  try {
    window.localStorage.setItem(TOKEN_KEY, token)
    window.localStorage.setItem(USER_KEY, JSON.stringify(user))
  } catch (_) {
    // A locked-down webview can reject storage; the in-memory session still works.
  }
}

export function clearSession(message = '') {
  sessionState.user = null
  sessionState.error = message
  try {
    window.localStorage.removeItem(TOKEN_KEY)
    window.localStorage.removeItem(USER_KEY)
  } catch (_) {}
}

export function apiError(error, fallback = '操作未完成，请稍后重试') {
  if (!error?.response) {
    return navigator.onLine === false ? '当前网络不可用' : '本地服务暂时不可用'
  }
  const body = error.response.data || {}
  if (Array.isArray(body.errors) && body.errors.length) {
    return body.errors.map(item => item.message).join('；')
  }
  return typeof body.detail === 'string' ? body.detail : fallback
}

axios.defaults.timeout = 45_000
axios.defaults.headers.common.Accept = 'application/json'

axios.interceptors.request.use(config => {
  const token = storedToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

axios.interceptors.response.use(
  response => {
    sessionState.server = 'online'
    return response
  },
  error => {
    if (!error.response) sessionState.server = 'offline'
    const path = error.config?.url || ''
    if (error.response?.status === 401 && !path.includes('/auth/login')) {
      clearSession('登录已过期，请重新登录')
      sessionState.mode = 'login'
    }
    return Promise.reject(error)
  },
)

export async function initializeSession() {
  sessionState.booting = true
  sessionState.error = ''
  try {
    const status = await axios.get('/api/v1/auth/status', { timeout: 10_000 })
    sessionState.initialized = Boolean(status.data.initialized)
    sessionState.registrationEnabled = Boolean(status.data.registration_enabled)
    sessionState.mode = sessionState.initialized ? 'login' : 'setup'

    if (storedToken()) {
      try {
        const me = await axios.get('/api/v1/auth/me')
        sessionState.user = me.data
      } catch (error) {
        if (error.response?.status !== 401) throw error
      }
    }
  } catch (error) {
    sessionState.server = 'offline'
    sessionState.error = apiError(error, '无法连接本地服务')
  } finally {
    sessionState.booting = false
  }
}

export async function signIn(username, password) {
  const response = await axios.post('/api/v1/auth/login', { username, password })
  persistSession(response.data.access_token, response.data.user)
  sessionState.initialized = true
  return response.data.user
}

export async function setupOwner(payload) {
  const response = await axios.post('/api/v1/auth/setup', payload)
  persistSession(response.data.access_token, response.data.user)
  sessionState.initialized = true
  return response.data.user
}

export async function registerUser(payload) {
  const response = await axios.post('/api/v1/auth/register', payload)
  persistSession(response.data.access_token, response.data.user)
  sessionState.initialized = true
  return response.data.user
}

export async function signOut() {
  try {
    await axios.post('/api/v1/auth/logout')
  } catch (_) {
    // Logging out remains deterministic even when the local API is restarting.
  }
  clearSession()
  sessionState.mode = 'login'
}

export async function checkHealth() {
  try {
    await axios.get('/health', { timeout: 4_000 })
    sessionState.server = 'online'
  } catch (_) {
    sessionState.server = 'offline'
  }
}

export const isAuthenticated = computed(() => Boolean(sessionState.user))

