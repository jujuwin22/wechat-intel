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

    <!-- wewe-rss 订阅源状态 -->
    <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold text-gray-700">📡 wewe-rss 订阅源</h2>
        <span
          class="px-2 py-0.5 rounded-full text-xs font-medium"
          :class="feedsStatus === 'ok' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'"
        >
          {{ feedsStatus === 'ok' ? `已连接 · ${feeds.length} 个订阅` : '未连接' }}
        </span>
      </div>
      <div v-if="feeds.length" class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
        <div
          v-for="feed in feeds"
          :key="feed.id"
          class="bg-gray-50 rounded-md px-3 py-2 text-sm"
        >
          <div class="font-medium text-gray-800 truncate">{{ feed.name }}</div>
          <div class="text-gray-400 text-xs mt-0.5">{{ formatTime(feed.updateTime) }}</div>
        </div>
      </div>
      <div v-else-if="feedsStatus === 'error'" class="text-sm text-red-500">
        {{ feedsError }}
      </div>
    </div>

    <!-- 公众号选择 -->
    <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold text-gray-700">📝 采集公众号</h2>
        <div class="flex gap-2">
          <button
            @click="selectAllAccounts"
            class="text-xs px-2 py-1 rounded border border-gray-300 hover:bg-gray-50 text-gray-600"
            :disabled="running"
          >全选</button>
          <button
            @click="deselectAllAccounts"
            class="text-xs px-2 py-1 rounded border border-gray-300 hover:bg-gray-50 text-gray-600"
            :disabled="running"
          >全不选</button>
        </div>
      </div>
      <div v-if="allAccounts.length" class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
        <label
          v-for="acc in allAccounts"
          :key="acc.name"
          class="flex items-center gap-2 bg-gray-50 rounded-md px-3 py-2 text-sm cursor-pointer hover:bg-gray-100 transition-colors"
          :class="{ 'opacity-50': running }"
        >
          <input
            type="checkbox"
            :value="acc.name"
            v-model="selectedAccounts"
            :disabled="running"
            class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <div>
            <div class="font-medium text-gray-800 truncate">{{ acc.name }}</div>
            <div class="text-gray-400 text-xs">{{ acc.dimensions?.join(', ') }}</div>
          </div>
        </label>
      </div>
      <div v-else class="text-sm text-gray-400 italic">加载中...</div>
    </div>

    <!-- 水位线信息 -->
    <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold text-gray-700">📊 采集水位线</h2>
        <button
          v-if="Object.keys(watermark).length"
          @click="clearAllWatermark"
          :disabled="running"
          class="text-xs px-3 py-1 rounded bg-red-50 text-red-600 border border-red-200 hover:bg-red-100 transition-colors disabled:opacity-50"
        >清除全部</button>
      </div>
      <div v-if="Object.keys(watermark).length" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        <div
          v-for="(info, name) in watermark"
          :key="name"
          class="bg-gray-50 rounded-md p-3 text-sm flex items-center justify-between"
        >
          <div>
            <div class="font-medium text-gray-800">{{ name }}</div>
            <div class="text-gray-500 text-xs mt-1">更新: {{ info.updated_at || '-' }}</div>
          </div>
          <button
            @click="clearWatermark(name)"
            :disabled="running"
            class="text-xs px-2 py-1 rounded text-red-500 hover:bg-red-50 transition-colors disabled:opacity-50"
            title="清除此公众号水位线"
          >清除</button>
        </div>
      </div>
      <div v-else class="text-sm text-gray-400 italic">无水位线记录</div>
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
const feeds = ref([])
const feedsStatus = ref('loading')
const feedsError = ref('')
const allAccounts = ref([])
const selectedAccounts = ref([])

let eventSource = null

onMounted(async () => {
  await Promise.all([fetchStatus(), fetchWatermark(), fetchFeeds(), fetchAccounts()])
})

function formatTime(ts) {
  if (!ts) return '-'
  try {
    return new Date(ts * 1000).toLocaleDateString('zh-CN')
  } catch {
    return '-'
  }
}

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

async function fetchFeeds() {
  try {
    const { data } = await axios.get('/api/collect/feeds')
    if (data.status === 'ok') {
      feeds.value = data.feeds || []
      feedsStatus.value = 'ok'
    } else {
      feedsStatus.value = 'error'
      feedsError.value = data.message || '连接失败'
    }
  } catch (e) {
    feedsStatus.value = 'error'
    feedsError.value = e.message || '网络错误'
  }
}

async function fetchAccounts() {
  try {
    const { data } = await axios.get('/api/collect/accounts')
    allAccounts.value = data.accounts || []
    selectedAccounts.value = allAccounts.value.map(a => a.name)
  } catch (e) {
    console.error('获取公众号列表失败:', e)
  }
}

function selectAllAccounts() {
  selectedAccounts.value = allAccounts.value.map(a => a.name)
}

function deselectAllAccounts() {
  selectedAccounts.value = []
}

async function clearWatermark(name) {
  try {
    await axios.delete(`/api/collect/watermark/${encodeURIComponent(name)}`)
    await fetchWatermark()
  } catch (e) {
    console.error('清除水位线失败:', e)
  }
}

async function clearAllWatermark() {
  try {
    await axios.delete('/api/collect/watermark')
    await fetchWatermark()
  } catch (e) {
    console.error('清除全部水位线失败:', e)
  }
}

async function startCollect() {
  if (running.value) return

  if (selectedAccounts.value.length === 0) {
    logLines.value = ['⚠️ 请至少选择一个公众号']
    return
  }

  logLines.value = []
  running.value = true

  try {
    await axios.post('/api/collect/run', {
      start_date: startDate.value,
      end_date: endDate.value,
      accounts: selectedAccounts.value,
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
