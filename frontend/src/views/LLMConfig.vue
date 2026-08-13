<template>
  <div class="llm-page">
    <header class="hero">
      <div><p>MODEL CONTROL PLANE</p><h1>模型、密钥与运行健康</h1><span>所有聊天、专业代理与科研流程共享同一用户级模型选择。</span></div>
      <button @click="load" :disabled="loading">{{ loading ? '同步中…' : '刷新状态' }}</button>
    </header>
    <p v-if="error" class="alert">{{ error }}</p>

    <section class="summary">
      <div><small>已配置</small><b>{{ configuredCount }} / {{ providers.length }}</b></div>
      <div><small>当前默认</small><b>{{ preferredLabel }}</b></div>
      <div><small>运行模式</small><b>SDK + CLI</b></div>
      <div><small>验证原则</small><b>配置 ≠ 在线可用</b></div>
    </section>

    <section class="provider-grid">
      <article v-for="item in providers" :key="item.name" :class="{ preferred: preferred?.provider === item.name }">
        <header>
          <div><span>{{ providerIcon(item.name) }}</span><div><h2>{{ item.display_name }}</h2><small>{{ item.execution_mode.toUpperCase() }}<template v-if="item.requires_runtime"> · 外部运行时</template></small></div></div>
          <b :class="item.configured ? 'ok' : 'muted'">{{ item.configured ? '已配置' : '未配置' }}</b>
        </header>
        <p class="capabilities">{{ item.capabilities.join(' · ') }}</p>
        <label>模型
          <select v-model="models[item.name]">
            <option v-for="model in item.models" :key="model" :value="model">{{ model }}</option>
          </select>
        </label>
        <label>API Key
          <input v-model="keys[item.name]" type="password" :placeholder="item.configured ? item.key_masked : '输入新 API Key'" autocomplete="new-password">
        </label>
        <p v-if="health[item.name]" class="health" :class="health[item.name].success ? 'healthy' : 'unhealthy'">
          <b>{{ health[item.name].success ? '✓' : '!' }}</b>
          <span>{{ health[item.name].message }}<small v-if="health[item.name].latency_ms">{{ health[item.name].latency_ms }} ms · {{ health[item.name].attempts }} 次尝试</small></span>
        </p>
        <footer>
          <button @click="saveKey(item.name)" :disabled="!keys[item.name]">保存密钥</button>
          <button @click="selectProvider(item.name)" :disabled="preferred?.provider===item.name">设为默认</button>
          <button @click="probe(item.name, false)">本地检查</button>
          <button class="primary" @click="probe(item.name, true)" :disabled="!item.configured || probing===item.name">{{ probing===item.name?'验证中…':'在线验证' }}</button>
          <button v-if="item.configured" class="danger" @click="deleteKey(item.name)">删除</button>
        </footer>
      </article>
    </section>

    <section class="test-panel">
      <header><div><p>END-TO-END CHAT PROBE</p><h2>使用当前默认模型测试完整对话链路</h2></div><span>{{ preferredLabel }}</span></header>
      <textarea v-model="message" placeholder="例如：用三点说明一个可检验的生物医学假设应满足哪些条件。"></textarea>
      <div class="actions"><button class="primary" @click="testChat" :disabled="testing || !message.trim()">{{ testing?'调用中…':'发送测试' }}</button></div>
      <div v-if="result" class="result"><small>{{ result.provider }} / {{ result.model }} · {{ result.latency_ms }} ms · {{ result.attempts }} 次尝试</small><p>{{ result.response }}</p></div>
    </section>
  </div>
</template>

<script setup>
import {computed,onMounted,reactive,ref} from 'vue'
import axios from 'axios'
import {apiError} from '../state/session'

const providers=ref([]),preferred=ref(null),loading=ref(false),probing=ref(''),testing=ref(false),error=ref(''),message=ref(''),result=ref(null)
const keys=reactive({}),models=reactive({}),health=reactive({})
const configuredCount=computed(()=>providers.value.filter(item=>item.configured).length)
const preferredLabel=computed(()=>preferred.value?`${preferred.value.provider} / ${preferred.value.model}`:'自动选择首个可用模型')
const providerIcon=name=>({deepseek:'深',agnes:'A',openai:'O',anthropic:'C',google:'G'}[name]||'AI')

async function load(){loading.value=true;error.value='';try{const [status,keyStatus]=await Promise.all([axios.get('/api/v1/llm/status'),axios.get('/api/v1/llm/keys')]);const keyed=Object.fromEntries((keyStatus.data.keys||[]).map(item=>[item.provider,item]));providers.value=(status.data.provider_descriptors||[]).map(item=>({...item,...(keyed[item.name]||{})}));preferred.value=status.data.preferred;providers.value.forEach(item=>{if(!models[item.name])models[item.name]=preferred.value?.provider===item.name?preferred.value.model:item.models[0];if(keys[item.name]===undefined)keys[item.name]=''})}catch(e){error.value=apiError(e,'模型状态加载失败')}finally{loading.value=false}}
async function saveKey(provider){try{await axios.post('/api/v1/llm/keys',{provider,api_key:keys[provider]});keys[provider]='';await load();await probe(provider,false)}catch(e){error.value=apiError(e,'密钥保存失败')}}
async function deleteKey(provider){if(!confirm(`确定删除 ${provider} 的 API Key？`))return;try{await axios.delete(`/api/v1/llm/keys/${provider}`);delete health[provider];await load()}catch(e){error.value=apiError(e,'密钥删除失败')}}
async function selectProvider(provider){try{const model=models[provider];await axios.put('/api/v1/llm/preference',{provider,model});preferred.value={provider,model}}catch(e){error.value=apiError(e,'默认模型保存失败')}}
async function probe(provider,live){probing.value=provider;try{health[provider]=(await axios.post(`/api/v1/llm/providers/${provider}/health`,null,{params:{live},timeout:live?120000:60000})).data}catch(e){health[provider]={success:false,message:apiError(e,'健康检查失败')}}finally{probing.value=''}}
async function testChat(){testing.value=true;result.value=null;try{result.value=(await axios.post('/api/v1/llm/chat',{message:message.value}, {timeout:120000})).data}catch(e){error.value=apiError(e,'对话测试失败')}finally{testing.value=false}}
onMounted(load)
</script>

<style scoped>
.llm-page{max-width:1180px;margin:auto;color:#203047}.hero{min-height:125px;display:flex;align-items:center;justify-content:space-between;border-radius:15px;padding:24px 30px;color:#dbeafe;background:radial-gradient(circle at 80% 0,#2563eb44,transparent 30%),linear-gradient(120deg,#08172a,#173e65)}.hero p,.test-panel header p{margin:0 0 5px;color:#60a5fa;font-size:8px;font-weight:800;letter-spacing:.16em}.hero h1{margin:0 0 7px;color:#fff;font-size:24px}.hero span{color:#a8bad0;font-size:10px}.hero button{border:1px solid #ffffff33;border-radius:7px;padding:8px 12px;color:#dbeafe;background:#ffffff0d}.alert{border:1px solid #fecaca;border-radius:8px;padding:9px;color:#b91c1c;background:#fff7f7}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}.summary div{display:grid;border:1px solid #e2e8f0;border-radius:10px;padding:12px 15px;background:#fff}.summary small{color:#94a3b8;font-size:8px}.summary b{margin-top:4px;font-size:11px}.provider-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.provider-grid article,.test-panel{border:1px solid #e2e8f0;border-radius:12px;padding:16px;background:#fff;box-shadow:0 3px 14px #0f172a08}.provider-grid article.preferred{border-color:#60a5fa;box-shadow:0 0 0 2px #dbeafe}.provider-grid article>header{display:flex;align-items:center;justify-content:space-between}.provider-grid article>header>div{display:flex;align-items:center;gap:9px}.provider-grid article>header span{width:31px;height:31px;display:grid;place-items:center;border-radius:8px;color:#1d4ed8;background:#eff6ff;font-size:10px;font-weight:800}.provider-grid h2{margin:0;font-size:12px}.provider-grid header small{color:#94a3b8;font-size:7px}.provider-grid header>b{border-radius:9px;padding:4px 7px;font-size:7px}.provider-grid header>b.ok{color:#15803d;background:#f0fdf4}.provider-grid header>b.muted{color:#64748b;background:#f8fafc}.capabilities{margin:10px 0;color:#64748b;font-size:8px}.provider-grid label{display:grid;grid-template-columns:62px 1fr;align-items:center;margin-top:8px;color:#64748b;font-size:8px}.provider-grid input,.provider-grid select{height:31px;border:1px solid #dbe4ee;border-radius:6px;padding:0 8px;background:#fbfdff;font-size:8px}.health{display:flex;gap:7px;margin:9px 0 0;border-radius:6px;padding:7px;font-size:8px}.health b{font-size:10px}.health span{display:grid}.health small{opacity:.7}.healthy{color:#15803d;background:#f0fdf4}.unhealthy{color:#b45309;background:#fffbeb}.provider-grid footer{display:flex;flex-wrap:wrap;gap:5px;margin-top:12px}.provider-grid button,.actions button{border:1px solid #dbe4ee;border-radius:6px;padding:6px 8px;background:#fff;font-size:7px}.provider-grid button.primary,.actions button.primary{border-color:#2563eb;color:#fff;background:#2563eb}.provider-grid button.danger{color:#b91c1c}.provider-grid button:disabled,.actions button:disabled{opacity:.4}.test-panel{margin-top:13px}.test-panel>header{display:flex;justify-content:space-between}.test-panel h2{margin:0;font-size:12px}.test-panel header>span{color:#2563eb;font-size:8px}.test-panel textarea{width:100%;min-height:74px;margin-top:10px;resize:vertical;border:1px solid #dbe4ee;border-radius:7px;padding:10px;font-size:9px}.actions{display:flex;justify-content:flex-end;margin-top:7px}.result{margin-top:10px;border-radius:7px;padding:10px;background:#f8fafc}.result small{color:#2563eb;font-size:7px}.result p{margin:7px 0;font-size:9px;line-height:1.7}@media(max-width:900px){.summary,.provider-grid{grid-template-columns:1fr}.summary{grid-template-columns:repeat(2,1fr)}}
</style>
