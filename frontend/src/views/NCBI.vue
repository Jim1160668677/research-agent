<template>
  <div class="ncbi-container">
    <h1>NCBI数据库查询</h1>
    
    <div class="tabs">
      <button :class="['tab', { active: activeTab === 'pubmed' }]" @click="activeTab = 'pubmed'">PubMed</button>
      <button :class="['tab', { active: activeTab === 'sra' }]" @click="activeTab = 'sra'">SRA</button>
      <button :class="['tab', { active: activeTab === 'genbank' }]" @click="activeTab = 'genbank'">GenBank</button>
      <button :class="['tab', { active: activeTab === 'blast' }]" @click="activeTab = 'blast'">BLAST</button>
    </div>
    
    <div class="search-panel">
      <!-- PubMed -->
      <div v-if="activeTab === 'pubmed'" class="panel">
        <h2>搜索PubMed文献</h2>
        <div class="input-group">
          <input v-model="query" placeholder="输入搜索关键词..." />
          <button @click="searchPubMed">搜索</button>
        </div>
        <div v-if="results.length > 0" class="results">
          <div v-for="r in results" :key="r.pmid" class="result-item">
            <h4>{{ r.title || '无标题' }}</h4>
            <p class="abstract">{{ r.abstract || '暂无摘要' }}</p>
            <span class="pmid">PMID: {{ r.pmid }}</span>
          </div>
        </div>
      </div>
      
      <!-- SRA -->
      <div v-if="activeTab === 'sra'" class="panel">
        <h2>搜索SRA数据</h2>
        <div class="input-group">
          <input v-model="query" placeholder="输入搜索关键词..." />
          <select v-model="organism">
            <option value="">所有物种</option>
            <option value="Homo sapiens">人类</option>
            <option value="Mus musculus">小鼠</option>
            <option value="Rattus norvegicus">大鼠</option>
          </select>
          <button @click="searchSRA">搜索</button>
        </div>
        <div v-if="results.length > 0" class="results">
          <div v-for="r in results" :key="r.sra_id" class="result-item">
            <h4>{{ r.sra_id }}</h4>
            <p>{{ r.description || '暂无描述' }}</p>
          </div>
        </div>
      </div>
      
      <!-- GenBank -->
      <div v-if="activeTab === 'genbank'" class="panel">
        <h2>获取GenBank序列</h2>
        <div class="input-group">
          <input v-model="accession" placeholder="输入 accession (如: NM_001301714)" />
          <button @click="fetchGenBank">获取</button>
        </div>
        <div v-if="result" class="result-detail">
          <pre>{{ result }}</pre>
        </div>
      </div>
      
      <!-- BLAST -->
      <div v-if="activeTab === 'blast'" class="panel">
        <h2>BLAST序列比对</h2>
        <div class="input-group">
          <textarea v-model="sequence" placeholder="输入序列..." rows="4"></textarea>
          <select v-model="database">
            <option value="nt">nt (核苷酸)</option>
            <option value="nr">nr (蛋白质)</option>
            <option value="refseq_rna">RefSeq RNA</option>
          </select>
          <button @click="runBlast">BLAST</button>
        </div>
        <div v-if="blastResult" class="blast-results">
          <pre>{{ blastResult }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref } from 'vue'
import axios from 'axios'

export default {
  name: 'NCBI',
  setup() {
    const activeTab = ref('pubmed')
    const query = ref('')
    const organism = ref('')
    const accession = ref('')
    const sequence = ref('')
    const database = ref('nt')
    const results = ref([])
    const result = ref(null)
    const blastResult = ref(null)
    
    const searchPubMed = async () => {
      try {
        const res = await axios.get('/api/v1/ncbi/pubmed', { params: { query: query.value, max_results: 10 } })
        results.value = res.data.results
      } catch (err) {
        alert('搜索失败')
      }
    }
    
    const searchSRA = async () => {
      try {
        const params = { query: query.value, max_results: 10 }
        if (organism.value) params.organism = organism.value
        const res = await axios.get('/api/v1/ncbi/sra', { params })
        results.value = res.data.results
      } catch (err) {
        alert('搜索失败')
      }
    }
    
    const fetchGenBank = async () => {
      try {
        const res = await axios.get(`/api/v1/ncbi/genbank/${accession.value}`)
        result.value = res.data
      } catch (err) {
        alert('获取失败')
      }
    }
    
    const runBlast = async () => {
      try {
        const res = await axios.post('/api/v1/ncbi/blast', {
          query_sequence: sequence.value,
          database: database.value,
          max_results: 10
        })
        blastResult.value = JSON.stringify(res.data, null, 2)
      } catch (err) {
        alert('BLAST失败')
      }
    }
    
    return { activeTab, query, organism, accession, sequence, database, results, result, blastResult, searchPubMed, searchSRA, fetchGenBank, runBlast }
  }
}
</script>

<style scoped>
.ncbi-container { max-width: 900px; margin: 0 auto; }
.tabs { display: flex; gap: 10px; margin-bottom: 30px; }
.tab { padding: 10px 20px; border: 1px solid #ddd; background: white; border-radius: 8px; cursor: pointer; }
.tab.active { background: #1976d2; color: white; border-color: #1976d2; }
.search-panel { background: white; border-radius: 12px; padding: 30px; }
.input-group { display: flex; gap: 10px; margin-bottom: 20px; }
.input-group input, .input-group textarea { flex: 1; padding: 12px; border: 1px solid #ddd; border-radius: 8px; }
.input-group select { padding: 12px; border: 1px solid #ddd; border-radius: 8px; }
.input-group button { padding: 12px 24px; background: #1976d2; color: white; border: none; border-radius: 8px; cursor: pointer; }
.results { display: grid; gap: 15px; }
.result-item { padding: 15px; background: #f5f5f5; border-radius: 8px; }
.result-item h4 { margin-bottom: 8px; }
.abstract { color: #555; font-size: 14px; margin-bottom: 8px; }
.pmid { font-size: 12px; color: #888; }
.result-detail pre { background: #f5f5f5; padding: 15px; border-radius: 8px; overflow-x: auto; }
</style>
