<template>
  <div class="designer-container">
    <div class="header">
      <h1>工作流设计器</h1>
      <div class="header-actions">
        <input v-model="workflowName" placeholder="工作流名称" class="name-input" />
        <button @click="saveWorkflow" class="save-btn">保存</button>
        <button @click="runWorkflow" class="run-btn" :disabled="!savedId">执行</button>
      </div>
    </div>

    <div class="designer-layout">
      <!-- 左侧：可用节点 -->
      <div class="node-palette">
        <h3>技能节点</h3>
        <div v-for="skill in skills" :key="skill.name" class="palette-item" draggable="true" @dragstart="dragStart(skill.name)">
          <span class="item-icon">🎯</span>
          <div>
            <div class="item-name">{{ skill.name }}</div>
            <div class="item-desc">{{ skill.description }}</div>
          </div>
        </div>
        <h3 class="mt">数据节点</h3>
        <div class="palette-item" draggable="true" @dragstart="dragStart('__input__')">
          <span class="item-icon">📥</span>
          <div>
            <div class="item-name">输入节点</div>
            <div class="item-desc">定义工作流输入参数</div>
          </div>
        </div>
        <div class="palette-item" draggable="true" @dragstart="dragStart('__output__')">
          <span class="item-icon">📤</span>
          <div>
            <div class="item-name">输出节点</div>
            <div class="item-desc">定义工作流输出</div>
          </div>
        </div>
      </div>

      <!-- 中间：画布 -->
      <div class="canvas" @dragover.prevent @drop="dropNode">
        <div v-if="nodes.length === 0" class="empty-hint">
          从左侧拖拽技能节点到画布，创建分析流程
        </div>
        <div v-for="(node, idx) in nodes" :key="node.id" class="canvas-node">
          <div class="node-header">
            <span class="node-icon">{{ node.icon }}</span>
            <span class="node-name">{{ node.label }}</span>
            <button class="delete-btn" @click="removeNode(idx)">✕</button>
          </div>
          <div class="node-params">
            <div v-for="(param, pname) in node.parameters" :key="pname" class="param-row">
              <label>{{ pname }}</label>
              <input v-model="param.value" :placeholder="String(param.default || '')" />
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：连接配置 -->
      <div class="config-panel">
        <h3>连接配置</h3>
        <div class="config-row">
          <label>从</label>
          <select v-model="edgeSource">
            <option v-for="n in nodes" :key="n.id" :value="n.id">{{ n.label }}</option>
          </select>
        </div>
        <div class="config-row">
          <label>到</label>
          <select v-model="edgeTarget">
            <option v-for="n in nodes" :key="n.id" :value="n.id">{{ n.label }}</option>
          </select>
        </div>
        <button @click="addEdge" class="add-edge-btn" :disabled="!edgeSource || !edgeTarget">添加连接</button>

        <h3 class="mt">已有连接</h3>
        <div v-for="(edge, idx) in edges" :key="idx" class="edge-item">
          <span>{{ edge.source }} → {{ edge.target }}</span>
          <button @click="removeEdge(idx)">✕</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { useRoute } from 'vue-router'

let nodeCounter = 0

export default {
  name: 'WorkflowDesigner',
  setup() {
    const route = useRoute()
    const skills = ref([])
    const nodes = ref([])
    const edges = ref([])
    const workflowName = ref('')
    const savedId = ref(null)
    const edgeSource = ref('')
    const edgeTarget = ref('')

    const fetchSkills = async () => {
      try {
        const res = await axios.get('/api/v1/skills/')
        skills.value = res.data
      } catch (e) {
        console.error(e)
      }
    }

    const loadWorkflow = async () => {
      if (!route.params.id) return
      const res = await axios.get(`/api/v1/workflows/${route.params.id}`)
      const workflow = res.data
      workflowName.value = workflow.name
      savedId.value = workflow.id
      edges.value = (workflow.definition?.edges || []).map(edge => ({ ...edge }))
      nodes.value = (workflow.definition?.nodes || []).map(node => {
        const parameters = Object.fromEntries(
          Object.entries(node.config?.parameters || {}).map(([key, value]) => [
            key, { value, default: value, required: false },
          ]),
        )
        return {
          id: node.name,
          label: node.skill_name || (node.node_type === 'input' ? '输入' : node.node_type === 'output' ? '输出' : node.name),
          icon: node.node_type === 'input' ? '📥' : node.node_type === 'output' ? '📤' : '🎯',
          skill: node.skill_name || null,
          parameters,
          nodeType: node.node_type || 'skill',
        }
      })
    }

    const dragStart = (name) => {
      window._dragSkill = name
    }

    const dropNode = () => {
      const name = window._dragSkill
      if (!name) return
      nodeCounter += 1
      if (name === '__input__') {
        nodes.value.push({
          id: `input_${nodeCounter}`,
          label: '输入',
          icon: '📥',
          skill: null,
          parameters: {},
          nodeType: 'input',
        })
      } else if (name === '__output__') {
        nodes.value.push({
          id: `output_${nodeCounter}`,
          label: '输出',
          icon: '📤',
          skill: null,
          parameters: {},
          nodeType: 'output',
        })
      } else {
        const skill = skills.value.find(s => s.name === name)
        if (!skill) return
        const params = {}
        for (const [pname, pdef] of Object.entries(skill.parameters || {})) {
          params[pname] = { value: pdef.default, default: pdef.default, required: pdef.required }
        }
        nodes.value.push({
          id: `node_${nodeCounter}`,
          label: name,
          icon: '🎯',
          skill: name,
          parameters: params,
          nodeType: 'skill',
        })
      }
      window._dragSkill = null
    }

    const removeNode = (idx) => {
      const node = nodes.value[idx]
      nodes.value.splice(idx, 1)
      edges.value = edges.value.filter(e => e.source !== node.id && e.target !== node.id)
    }

    const addEdge = () => {
      if (edgeSource.value === edgeTarget.value) return
      edges.value.push({ source: edgeSource.value, target: edgeTarget.value })
      edgeSource.value = ''
      edgeTarget.value = ''
    }

    const removeEdge = (idx) => {
      edges.value.splice(idx, 1)
    }

    const buildDefinition = () => {
      return {
        nodes: nodes.value.map(n => ({
          name: n.id,
          node_type: n.nodeType,
          skill_name: n.skill,
          config: {
            parameters: Object.fromEntries(
              Object.entries(n.parameters).map(([k, v]) => [k, v.value])
            ),
          },
        })),
        edges: edges.value.map(e => ({ source: e.source, target: e.target })),
      }
    }

    const saveWorkflow = async () => {
      if (!workflowName.value) {
        alert('请输入工作流名称')
        return
      }
      if (nodes.value.length === 0) {
        alert('请先添加至少一个节点')
        return
      }
      try {
        const payload = {
          name: workflowName.value,
          category: 'custom',
          definition: buildDefinition(),
          is_public: false,
        }
        const res = savedId.value
          ? await axios.put(`/api/v1/workflows/${savedId.value}`, {
              name: payload.name,
              definition: payload.definition,
            })
          : await axios.post('/api/v1/workflows/', payload)
        savedId.value = res.data.id
        alert(`工作流已保存 (ID: ${savedId.value})`)
      } catch (e) {
        alert('保存失败: ' + (e.response?.data?.detail || e.message))
      }
    }

    const runWorkflow = async () => {
      try {
        const res = await axios.post('/api/v1/workflows/run', {
          workflow_id: savedId.value,
          inputs: {},
        })
        alert(`执行完成! 状态: ${res.data.status}`)
      } catch (e) {
        alert('执行失败: ' + (e.response?.data?.detail || e.message))
      }
    }

    onMounted(async () => {
      await fetchSkills()
      await loadWorkflow()
      if (!route.params.id && typeof route.query.add_skill === 'string') {
        window._dragSkill = route.query.add_skill
        dropNode()
      }
    })

    return {
      skills, nodes, edges, workflowName, savedId,
      edgeSource, edgeTarget,
      dragStart, dropNode, removeNode, addEdge, removeEdge,
      saveWorkflow, runWorkflow,
    }
  }
}
</script>

<style scoped>
.designer-container { max-width: 1400px; margin: 0 auto; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.header-actions { display: flex; gap: 10px; align-items: center; }
.name-input { padding: 8px 12px; border: 1px solid #ddd; border-radius: 8px; width: 200px; }
.save-btn { padding: 8px 20px; background: #1976d2; color: white; border: none; border-radius: 8px; cursor: pointer; }
.run-btn { padding: 8px 20px; background: #2e7d32; color: white; border: none; border-radius: 8px; cursor: pointer; }
.run-btn:disabled { background: #ccc; }
.designer-layout { display: grid; grid-template-columns: 240px 1fr 260px; gap: 15px; min-height: 600px; }
.node-palette { background: white; border-radius: 12px; padding: 15px; }
.node-palette h3 { margin-bottom: 10px; font-size: 14px; }
.node-palette h3.mt { margin-top: 20px; }
.palette-item { display: flex; gap: 8px; padding: 10px; background: #f5f7fa; border-radius: 8px; margin-bottom: 8px; cursor: grab; }
.palette-item:hover { background: #e3f2fd; }
.item-name { font-size: 13px; font-weight: 600; }
.item-desc { font-size: 11px; color: #888; }
.canvas { background: white; border-radius: 12px; padding: 20px; min-height: 600px; border: 2px dashed #ddd; }
.empty-hint { color: #aaa; text-align: center; margin-top: 200px; }
.canvas-node { background: #f8f9fa; border: 1px solid #e0e0e0; border-radius: 10px; padding: 12px; margin-bottom: 12px; }
.node-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.node-icon { font-size: 16px; }
.node-name { font-weight: 600; font-size: 14px; flex: 1; }
.delete-btn { border: none; background: none; color: #999; cursor: pointer; }
.param-row { display: flex; gap: 8px; align-items: center; margin-bottom: 5px; }
.param-row label { font-size: 12px; width: 80px; color: #666; }
.param-row input { flex: 1; padding: 5px 8px; border: 1px solid #ddd; border-radius: 6px; font-size: 12px; }
.config-panel { background: white; border-radius: 12px; padding: 15px; }
.config-panel h3 { margin-bottom: 10px; font-size: 14px; }
.config-panel h3.mt { margin-top: 20px; }
.config-row { margin-bottom: 8px; }
.config-row label { font-size: 12px; color: #666; display: block; margin-bottom: 4px; }
.config-row select { width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 6px; }
.add-edge-btn { width: 100%; padding: 8px; background: #1976d2; color: white; border: none; border-radius: 6px; cursor: pointer; }
.add-edge-btn:disabled { background: #ccc; }
.edge-item { display: flex; justify-content: space-between; align-items: center; padding: 6px 8px; background: #f5f7fa; border-radius: 6px; margin-bottom: 5px; font-size: 12px; }
.edge-item button { border: none; background: none; color: #999; cursor: pointer; }
</style>
