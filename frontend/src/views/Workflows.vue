<template>
  <div class="workflows-container">
    <div class="header">
      <h1>工作流设计器</h1>
      <router-link to="/workflows/new" class="create-btn">+ 新建工作流</router-link>
    </div>
    
    <div class="workflow-list">
      <div v-for="wf in workflows" :key="wf.id" class="workflow-card">
        <div class="workflow-info">
          <h3>{{ wf.name }}</h3>
          <p class="description">{{ wf.description || '暂无描述' }}</p>
          <div class="meta">
            <span class="category">{{ wf.category }}</span>
            <span class="status" :class="wf.status">{{ wf.status }}</span>
          </div>
        </div>
        <div class="workflow-actions">
          <button @click="runWorkflow(wf)">执行</button>
          <router-link :to="`/workflows/${wf.id}`" class="secondary">编辑</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import axios from 'axios'

export default {
  name: 'Workflows',
  setup() {
    const workflows = ref([])
    
    const fetchWorkflows = async () => {
      try {
        const res = await axios.get('/api/v1/workflows/')
        workflows.value = res.data
      } catch (err) {
        console.error('Failed to fetch workflows', err)
      }
    }
    
    const runWorkflow = async (wf) => {
      try {
        const res = await axios.post('/api/v1/workflows/run', {
          workflow_id: wf.id,
          inputs: {}
        })
        alert(`工作流执行完成！运行ID: ${res.data.id}`)
      } catch (err) {
        alert('执行失败: ' + (err.response?.data?.detail || err.message))
      }
    }
    
    onMounted(fetchWorkflows)
    
    return { workflows, runWorkflow }
  }
}
</script>

<style scoped>
.workflows-container { max-width: 1200px; margin: 0 auto; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
.create-btn { padding: 10px 20px; background: #1976d2; color: white; text-decoration: none; border-radius: 8px; }
.workflow-list { display: grid; gap: 15px; }
.workflow-card { background: white; border-radius: 12px; padding: 20px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
.workflow-info h3 { margin-bottom: 5px; }
.description { color: #666; font-size: 14px; margin-bottom: 10px; }
.meta { display: flex; gap: 10px; }
.category { background: #e3f2fd; padding: 3px 10px; border-radius: 12px; font-size: 12px; color: #1976d2; }
.status { padding: 3px 10px; border-radius: 12px; font-size: 12px; }
.status.draft { background: #fff3e0; color: #e65100; }
.status.active { background: #e8f5e9; color: #2e7d32; }
.workflow-actions { display: flex; gap: 10px; }
.workflow-actions button { padding: 8px 16px; background: #1976d2; color: white; border: none; border-radius: 8px; cursor: pointer; text-decoration: none; }
.workflow-actions button.secondary { background: #f0f0f0; }
</style>
