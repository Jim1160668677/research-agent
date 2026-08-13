<template>
  <div class="skills-container">
    <div class="header">
      <h1>自动化技能组合</h1>
      <button @click="createNew" class="create-btn">+ 新建技能组合</button>
    </div>
    
    <div class="skill-categories">
      <button 
        v-for="cat in categories" 
        :key="cat" 
        :class="['cat-btn', { active: activeCategory === cat }]"
        @click="activeCategory = cat"
      >
        {{ cat }}
      </button>
    </div>
    
    <div class="skill-grid">
      <div v-for="skill in filteredSkills" :key="skill.name" class="skill-card">
        <div class="skill-header">
          <h3>{{ skill.name }}</h3>
          <span class="category">{{ skill.category }}</span>
        </div>
        <p class="description">{{ skill.description }}</p>
        <div class="params">
          <span v-for="(param, i) in Object.keys(skill.parameters || {})" :key="i" class="param">
            {{ param }}
          </span>
        </div>
        <div class="skill-actions">
          <button @click="useSkill(skill)">使用</button>
          <button class="secondary" @click="addToWorkflow(skill)">加入工作流</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import { useRouter } from 'vue-router'

export default {
  name: 'Skills',
  setup() {
    const router = useRouter()
    const skills = ref([])
    const activeCategory = ref('all')
    const categories = computed(() => ['all', ...new Set(skills.value.map(skill => skill.category))])
    
    const filteredSkills = computed(() => {
      if (activeCategory.value === 'all') return skills.value
      return skills.value.filter(s => s.category === activeCategory.value)
    })
    
    const fetchSkills = async () => {
      try {
        const res = await axios.get('/api/v1/skills/')
        skills.value = res.data
      } catch (err) {
        console.error('Failed to fetch skills', err)
      }
    }
    
    const useSkill = (skill) => {
      router.push({ path: '/chat', query: { prompt: `请使用 ${skill.name} 技能帮助我完成分析` } })
    }
    
    const addToWorkflow = (skill) => {
      // 导航到工作流设计器
      router.push({ path: '/workflows/new', query: { add_skill: skill.name } })
    }
    
    const createNew = () => {
      router.push('/workflows/new')
    }
    
    onMounted(fetchSkills)
    
    return { skills, activeCategory, categories, filteredSkills, useSkill, addToWorkflow, createNew }
  }
}
</script>

<style scoped>
.skills-container { max-width: 1200px; margin: 0 auto; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
.create-btn { padding: 10px 20px; background: #1976d2; color: white; border: none; border-radius: 8px; cursor: pointer; }
.skill-categories { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
.cat-btn { padding: 8px 16px; border: 1px solid #ddd; background: white; border-radius: 20px; cursor: pointer; }
.cat-btn.active { background: #1976d2; color: white; border-color: #1976d2; }
.skill-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
.skill-card { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
.skill-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.skill-header h3 { font-size: 16px; }
.category { font-size: 12px; color: #888; }
.description { color: #555; font-size: 14px; margin-bottom: 15px; min-height: 40px; }
.params { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 15px; }
.param { background: #e3f2fd; padding: 3px 8px; border-radius: 12px; font-size: 12px; color: #1976d2; }
.skill-actions { display: flex; gap: 10px; }
.skill-actions button { padding: 8px 16px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; }
.skill-actions button:first-child { background: #1976d2; color: white; }
.skill-actions button.secondary { background: #f0f0f0; }
</style>
