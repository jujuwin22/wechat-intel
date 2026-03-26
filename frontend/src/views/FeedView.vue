<template>
  <div class="space-y-6">
    <!-- 标题 + 控制 -->
    <div class="flex flex-wrap items-center justify-between gap-4">
      <h1 class="text-2xl font-bold text-gray-800">📰 情报速递</h1>
      <div class="flex items-center gap-3">
        <select
          v-model="selectedMonth"
          @change="loadFeed"
          class="border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500"
        >
          <option value="">选择月份</option>
          <option v-for="m in months" :key="m" :value="m">{{ m }}</option>
        </select>
        <button
          @click="generateFeed"
          :disabled="generating"
          class="px-4 py-2 rounded-md text-sm font-medium text-white transition-colors"
          :class="generating ? 'bg-gray-400 cursor-not-allowed' : 'bg-indigo-600 hover:bg-indigo-700'"
        >
          {{ generating ? '生成中...' : '生成速递' }}
        </button>
      </div>
    </div>

    <!-- 统计栏 -->
    <div v-if="feedData.total_events" class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
        <div class="text-2xl font-bold text-blue-600">{{ feedData.total_events }}</div>
        <div class="text-xs text-gray-500 mt-1">事件总数</div>
      </div>
      <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
        <div class="text-2xl font-bold text-green-600">{{ feedData.source_accounts?.length || 0 }}</div>
        <div class="text-xs text-gray-500 mt-1">来源公众号</div>
      </div>
      <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
        <div class="text-2xl font-bold text-purple-600">{{ feedData.companies?.length || 0 }}</div>
        <div class="text-xs text-gray-500 mt-1">涉及公司</div>
      </div>
      <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
        <div class="text-2xl font-bold text-orange-600">{{ multiSourceCount }}</div>
        <div class="text-xs text-gray-500 mt-1">多源验证</div>
      </div>
    </div>

    <!-- 维度筛选 -->
    <div v-if="entries.length" class="flex flex-wrap gap-2">
      <button
        v-for="dim in allDimensions"
        :key="dim"
        @click="toggleDimension(dim)"
        class="px-3 py-1.5 rounded-full text-xs font-medium border transition-colors"
        :class="activeDimension === dim
          ? 'bg-blue-600 text-white border-blue-600'
          : 'bg-white text-gray-600 border-gray-300 hover:border-blue-400'"
      >
        {{ dim }} ({{ dimensionCount(dim) }})
      </button>
    </div>

    <!-- 事件列表 -->
    <div v-if="filteredEntries.length" class="space-y-3">
      <div
        v-for="(entry, idx) in filteredEntries"
        :key="idx"
        class="bg-white rounded-lg shadow-sm border border-gray-200 p-4 hover:shadow-md transition-shadow"
      >
        <div class="flex items-start gap-3">
          <span class="flex-shrink-0 w-7 h-7 rounded-full bg-gray-100 text-gray-500 flex items-center justify-center text-xs font-bold">
            {{ idx + 1 }}
          </span>
          <div class="flex-1 min-w-0">
            <div class="flex flex-wrap items-center gap-2 mb-1">
              <span
                class="px-2 py-0.5 rounded text-xs font-medium text-white"
                :style="{ background: dimColor(entry.canonical?.dimension) }"
              >
                {{ entry.canonical?.dimension || '未分类' }}
              </span>
              <span class="text-xs text-gray-400">{{ entry.canonical?.event_date || '' }}</span>
              <span v-if="entry.source_count > 1" class="text-xs text-orange-500 font-medium">
                🔗 {{ entry.source_count }}个来源
              </span>
            </div>
            <h3 class="text-sm font-semibold text-gray-800 mb-1">{{ entry.canonical?.summary }}</h3>
            <p v-if="entry.canonical?.detail" class="text-xs text-gray-500 line-clamp-2">{{ entry.canonical.detail }}</p>
            <div class="flex items-center gap-3 mt-2 text-xs text-gray-400">
              <span v-if="entry.canonical?.company">🏢 {{ entry.canonical.company }}</span>
              <span>📰 {{ entry.canonical?.source_account }}</span>
              <span>置信度 {{ entry.canonical?.confidence }}%</span>
              <a
                v-if="entry.all_urls?.[0]"
                :href="entry.all_urls[0]"
                target="_blank"
                class="text-blue-500 hover:underline"
              >查看原文</a>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else-if="!loading" class="bg-white rounded-lg shadow-sm border border-gray-200 p-12 text-center">
      <div class="text-4xl mb-3">📭</div>
      <div class="text-gray-500">{{ feedData.message || '暂无数据，请先运行采集和Pipeline' }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'

const months = ref([])
const selectedMonth = ref('')
const feedData = ref({})
const entries = ref([])
const loading = ref(false)
const generating = ref(false)
const activeDimension = ref('全部')

const dimColors = {
  '薪酬激励': '#e74c3c',
  '组织架构': '#3498db',
  '人才发展': '#2ecc71',
  '企业文化': '#f59e0b',
  '未分类': '#95a5a6',
}

const allDimensions = computed(() => {
  const dims = new Set(['全部'])
  entries.value.forEach(e => dims.add(e.canonical?.dimension || '未分类'))
  return Array.from(dims)
})

const filteredEntries = computed(() => {
  if (activeDimension.value === '全部') return entries.value
  return entries.value.filter(e => (e.canonical?.dimension || '未分类') === activeDimension.value)
})

const multiSourceCount = computed(() =>
  entries.value.filter(e => e.source_count > 1).length
)

function dimensionCount(dim) {
  if (dim === '全部') return entries.value.length
  return entries.value.filter(e => (e.canonical?.dimension || '未分类') === dim).length
}

function dimColor(dim) {
  return dimColors[dim] || '#95a5a6'
}

function toggleDimension(dim) {
  activeDimension.value = dim
}

onMounted(async () => {
  await loadMonths()
  if (months.value.length) {
    selectedMonth.value = months.value[0]
    await loadFeed()
  }
})

async function loadMonths() {
  try {
    const { data } = await axios.get('/api/feed/months')
    months.value = data
  } catch (e) {
    console.error('获取月份失败:', e)
  }
}

async function loadFeed() {
  if (!selectedMonth.value) return
  loading.value = true
  try {
    const { data } = await axios.get('/api/feed', { params: { month: selectedMonth.value } })
    feedData.value = data
    entries.value = data.entries || []
  } catch (e) {
    console.error('获取速递失败:', e)
  } finally {
    loading.value = false
  }
}

async function generateFeed() {
  generating.value = true
  try {
    await axios.post('/api/feed/generate', { month: selectedMonth.value })
    await loadFeed()
  } catch (e) {
    alert(`生成失败: ${e.response?.data?.message || e.message}`)
  } finally {
    generating.value = false
  }
}
</script>
