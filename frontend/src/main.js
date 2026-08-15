import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'

import Chat from './views/Chat.vue'
import Plugins from './views/Plugins.vue'
import Skills from './views/Skills.vue'
import Workflows from './views/Workflows.vue'
import WorkflowDesigner from './views/WorkflowDesigner.vue'
import NCBI from './views/NCBI.vue'
import Dashboard from './views/Dashboard.vue'
import LLMConfig from './views/LLMConfig.vue'
import ResearchWorkspace from './views/ResearchWorkspace.vue'
import Pipelines from './views/Pipelines.vue'
import Security from './views/Security.vue'
import HealthCheck from './views/HealthCheck.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/dashboard', component: Dashboard },
    { path: '/chat', component: Chat },
    { path: '/research', component: ResearchWorkspace },
    { path: '/pipelines', component: Pipelines },
    { path: '/plugins', component: Plugins },
    { path: '/skills', component: Skills },
    { path: '/workflows', component: Workflows },
    { path: '/workflows/new', component: WorkflowDesigner },
    { path: '/workflows/:id', component: WorkflowDesigner },
    { path: '/ncbi', component: NCBI },
    { path: '/health', component: HealthCheck },
    { path: '/llm', component: LLMConfig },
    { path: '/security', component: Security },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ]
})

const app = createApp(App)
app.use(router)
app.mount('#app')
