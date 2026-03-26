<template>
  <div class="space-y-6">
    <!-- 标题 + 状态 -->
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold text-gray-800">🔄 采集控制</h1>
      <span
        class="px-3 py-1 rounded-full text-sm font-medium"
        :class="running ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'"
      >
        {{ running ? '采集中...' : '空闲' }}
      </span>
    </div>

    <!-- 控制面板 -->
    <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <div class="flex flex-wrap items-end gap-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">开始日期</label>
          <input
            v-model="startDate"
            type="date"
            class="border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">结束日期</label>
          <input
            v-model="endDate"
            type="date"
            class="border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>
        <button
          @click="startCollect"
          :disabled="running"
          class="px-5 py-2 rounded-md text-sm font-medium text-white transition-colors"
          :class="running
            ? 'bg-gray-400 cursor-not-allowed'
            : 'bg-blue-600 hover:bg-blue-700'"
        >
          {{ running ? '采集中...' : '开始采集' }}
        </button>
      </div>
    </div>

    <!-- 水位线信息 -->
    <div v-if="Object.keys(watermark).length" class="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <h2 class="text-lg font-semibold text-gray-700 mb-3">📊 采集水位线</h2>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        <div
          v-for="(info, name) in watermark"
          :key="name"
          class="bg-gray-50 rounded-md p-3 text-sm"
        >
          <div class="font-medium text-gray-800">{{ name }}</div>
          <div class="text-gray-500 text-xs mt-1">更新: {{ info.updated_at || '-' }}</div>
        </div>
      </div>
    </div>

    <!-- 日志区域 -->
    <div class="bg-gray-900 rounded-lg shadow-sm p-4">
      <div class="flex items-center justify-between mb-2">
        <h2 class="text-sm font-medium text-gray-400">实时日志</h2>
        <span class="text-xs text-gray-500">{{ logLines.length }} 行</span>
      </div>
      <div
        ref="logContainer"
        class="font-mono text-xs text-green-400 h-80 overflow-y-auto space-y-0.5"
      >
        <div v-if="!logLines.length" class="text-gray-600 italic">等待采集启动...</div>
        <div v-for="(line, i) in logLines" :key="i" class="whitespace-pre-wrap">{{ line }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import axios from 'axios'

const running = ref(false)
const startDate = ref('')
const endDate = ref('')
const logLines = ref([])
const logContainer = ref(null)
const watermark = ref({})

let eventSource = null

onMounted(async () => {
  await fetchStatus()
  await fetchWatermark()
})

async function fetchStatus() {
  try {
    const { data } = await axios.get('/api/collect/status')
    running.value = data.running
  } catch (e) {
    console.error('获取状态失败:', e)
  }
}

async function fetchWatermark() {
  try {
    const { data } = await axios.get('/api/collect/watermark')
    watermark.value = data.accounts || {}
  } catch (e) {
    console.error('获取水位线失败:', e)
  }
}

async function startCollect() {
  if (running.value) return

  logLines.value = []
  running.value = true

  try {
    await axios.post('/api/collect/run', {
      start_date: startDate.value,
      end_date: endDate.value,
    })
    connectSSE()
  } catch (e) {
    if (e.response?.status === 409) {
      logLines.value.push('⚠️ 采集已在运行中')
    } else {
      logLines.value.push(`✗ 启动失败: ${e.message}`)
    }
    running.value = false
  }
}

function connectSSE() {
  if (eventSource) {
    eventSource.close()
  }

  eventSource = new EventSource('/api/collect/log')

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.line) {
        logLines.value.push(data.line)
        scrollToBottom()
      }
      if (data.done) {
        running.value = false
        eventSource.close()
        eventSource = null
        fetchWatermark()
      }
    } catch (e) {
      console.error('解析SSE数据失败:', e)
    }
  }

  eventSource.onerror = () => {
    running.value = false
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}
</script>
