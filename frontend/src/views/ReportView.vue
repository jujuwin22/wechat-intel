<template>
  <div class="space-y-6">
    <!-- 标题 + 控制 -->
    <div class="flex flex-wrap items-center justify-between gap-4">
      <h1 class="text-2xl font-bold text-gray-800">📊 趋势报告</h1>
      <div class="flex items-center gap-3">
        <select
          v-model="selectedMonth"
          @change="loadReport"
          class="border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500"
        >
          <option value="">选择月份</option>
          <option v-for="m in months" :key="m" :value="m">{{ m }}</option>
        </select>
        <button
          @click="generateReport"
          :disabled="generating"
          class="px-4 py-2 rounded-md text-sm font-medium text-white transition-colors"
          :class="generating ? 'bg-gray-400 cursor-not-allowed' : 'bg-indigo-600 hover:bg-indigo-700'"
        >
          {{ generating ? '生成中...' : '生成报告' }}
        </button>
        <button
          @click="exportMarkdown"
          :disabled="!selectedMonth || exporting"
          class="px-4 py-2 rounded-md text-sm font-medium text-white transition-colors"
          :class="(!selectedMonth || exporting) ? 'bg-gray-400 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700'"
        >
          {{ exporting ? '导出中...' : '📥 导出Markdown' }}
        </button>
      </div>
    </div>

    <!-- 维度选择器 -->
    <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
      <div class="flex items-center justify-between mb-2">
        <span class="text-sm font-medium text-gray-700">选择事件维度（不选则基于全部事件生成）</span>
        <button @click="clearDimensions" class="text-xs text-gray-400 hover:text-gray-600">清除选择</button>
      </div>
      <div class="flex flex-wrap gap-2">
        <label
          v-for="dim in allDimensions"
          :key="dim"
          class="flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium cursor-pointer transition-colors"
          :class="selectedDimensions.includes(dim)
            ? 'border-indigo-400 bg-indigo-50 text-indigo-700'
            : 'border-gray-300 bg-white text-gray-600 hover:border-gray-400'"
        >
          <input type="checkbox" :value="dim" v-model="selectedDimensions" class="hidden" />
          <span class="w-2 h-2 rounded-full" :style="{ background: dimColor(dim) }"></span>
          {{ dim }}
        </label>
      </div>
    </div>

    <!-- 统计栏 -->
    <div v-if="stats.total_events" class="grid grid-cols-3 md:grid-cols-5 gap-3">
      <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-3 text-center">
        <div class="text-xl font-bold text-blue-600">{{ stats.total_events }}</div>
        <div class="text-xs text-gray-500 mt-1">事件总数</div>
      </div>
      <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-3 text-center">
        <div class="text-xl font-bold text-indigo-600">{{ stats.trend_count || trends.length }}</div>
        <div class="text-xs text-gray-500 mt-1">核心趋势</div>
      </div>
      <div
        v-for="(count, dim) in stats.dimensions"
        :key="dim"
        class="bg-white rounded-lg shadow-sm border border-gray-200 p-3 text-center"
      >
        <div class="text-xl font-bold" :style="{ color: dimColor(dim) }">{{ count }}</div>
        <div class="text-xs text-gray-500 mt-1">{{ dim }}</div>
      </div>
    </div>

    <!-- 执行摘要 -->
    <div v-if="executiveSummary" class="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-200 p-5">
      <div class="flex items-center gap-2 mb-2">
        <span class="text-lg">📋</span>
        <h2 class="text-base font-semibold text-gray-800">执行摘要</h2>
      </div>
      <p class="text-sm text-gray-700 leading-relaxed">{{ executiveSummary }}</p>
    </div>

    <!-- 趋势卡片 -->
    <div v-for="(trend, tIdx) in trends" :key="tIdx" class="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
      <!-- 趋势头部 -->
      <div class="bg-gray-50 px-5 py-3 border-b border-gray-200 cursor-pointer" @click="toggleTrend(tIdx)">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="flex-shrink-0 w-7 h-7 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-bold">
              {{ tIdx + 1 }}
            </span>
            <h3 class="text-sm font-bold text-gray-800">{{ trend.title }}</h3>
          </div>
          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-400">{{ trend.events?.length || 0 }} 条事件</span>
            <span class="text-gray-400 text-xs">{{ expandedTrends.has(tIdx) ? '▼' : '▶' }}</span>
          </div>
        </div>
        <p v-if="trend.summary" class="text-xs text-gray-600 mt-1 ml-9">{{ trend.summary }}</p>
      </div>

      <!-- 关联事件（可折叠） -->
      <div v-if="expandedTrends.has(tIdx)" class="divide-y divide-gray-100">
        <div
          v-for="(ev, eIdx) in trend.events"
          :key="eIdx"
          class="px-5 py-3"
        >
          <div class="flex items-start gap-2">
            <span
              class="flex-shrink-0 mt-0.5 px-1.5 py-0.5 rounded text-xs font-medium text-white"
              :style="{ background: dimColor(ev.dimension) }"
            >{{ ev.dimension }}</span>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span v-if="ev.company" class="text-xs font-semibold text-gray-700">{{ ev.company }}</span>
                <span class="text-xs text-gray-400">{{ ev.event_date }}</span>
                <span v-if="ev.source_count > 1" class="text-xs text-orange-500">🔗{{ ev.source_count }}源</span>
              </div>
              <p class="text-xs text-gray-700 font-medium mt-0.5">{{ ev.summary }}</p>
              <!-- 原文摘要 -->
              <div v-if="ev.excerpts?.length" class="mt-1.5 bg-gray-50 border-l-3 border-blue-400 rounded-r pl-2.5 pr-2 py-1.5">
                <p
                  v-for="(exc, xi) in ev.excerpts"
                  :key="xi"
                  class="text-xs text-gray-500 leading-relaxed whitespace-pre-line"
                >{{ exc }}</p>
              </div>
              <div class="flex items-center gap-2 mt-1 text-xs text-gray-400">
                <span>📰 {{ ev.source_account }}</span>
                <span v-if="ev.source_url">|</span>
                <a v-if="ev.source_url" :href="ev.source_url" target="_blank" class="text-blue-500 hover:underline font-medium">🔗 原文链接</a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 其他动态 -->
    <div v-if="unclassified.length" class="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
      <div class="bg-gray-50 px-5 py-3 border-b border-gray-200 cursor-pointer" @click="showUnclassified = !showUnclassified">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-gray-700">📌 其他动态</h3>
          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-400">{{ unclassified.length }} 条</span>
            <span class="text-gray-400 text-xs">{{ showUnclassified ? '▼' : '▶' }}</span>
          </div>
        </div>
      </div>
      <div v-if="showUnclassified" class="divide-y divide-gray-100">
        <div v-for="(ev, i) in unclassified" :key="i" class="px-5 py-2.5 flex items-center gap-2">
          <span
            class="flex-shrink-0 px-1.5 py-0.5 rounded text-xs font-medium text-white"
            :style="{ background: dimColor(ev.dimension) }"
          >{{ ev.dimension }}</span>
          <span v-if="ev.company" class="text-xs font-medium text-gray-700">{{ ev.company }}</span>
          <span class="text-xs text-gray-600 flex-1 truncate">{{ ev.summary }}</span>
          <span class="text-xs text-gray-400 flex-shrink-0">{{ ev.event_date }}</span>
        </div>
      </div>
    </div>

    <!-- Markdown回退（无结构化数据时） -->
    <div v-if="!trends.length && reportMarkdown" class="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <div class="prose prose-sm max-w-none" v-html="renderedHtml"></div>
    </div>

    <!-- 空状态 -->
    <div v-if="!trends.length && !reportMarkdown && !loading" class="bg-white rounded-lg shadow-sm border border-gray-200 p-12 text-center">
      <div class="text-4xl mb-3">📋</div>
      <div class="text-gray-500">{{ reportData.message || '暂无趋势报告，请先运行Pipeline生成' }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import axios from 'axios'
import { marked } from 'marked'

const months = ref([])
const selectedMonth = ref('')
const reportData = ref({})
const trends = ref([])
const unclassified = ref([])
const executiveSummary = ref('')
const reportMarkdown = ref('')
const stats = ref({})
const loading = ref(false)
const generating = ref(false)
const exporting = ref(false)
const showUnclassified = ref(false)
const expandedTrends = reactive(new Set())
const selectedDimensions = ref([])
const allDimensions = ['薪酬激励', '组织架构', '人事变动', '人才发展', '企业文化']

const dimColors = {
  '薪酬激励': '#e74c3c',
  '组织架构': '#3498db',
  '人事变动': '#9b59b6',
  '人才发展': '#2ecc71',
  '企业文化': '#f59e0b',
  '未分类': '#95a5a6',
}

function clearDimensions() {
  selectedDimensions.value = []
}

function dimColor(dim) {
  return dimColors[dim] || '#95a5a6'
}

function toggleTrend(idx) {
  if (expandedTrends.has(idx)) {
    expandedTrends.delete(idx)
  } else {
    expandedTrends.add(idx)
  }
}

const renderedHtml = computed(() => {
  if (!reportMarkdown.value) return ''
  return marked(reportMarkdown.value)
})

onMounted(async () => {
  await loadMonths()
  if (months.value.length) {
    selectedMonth.value = months.value[0]
    await loadReport()
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

async function loadReport() {
  if (!selectedMonth.value) return
  loading.value = true
  expandedTrends.clear()
  try {
    const { data } = await axios.get('/api/report', { params: { month: selectedMonth.value } })
    reportData.value = data
    trends.value = data.trends || []
    unclassified.value = data.unclassified || []
    executiveSummary.value = data.executive_summary || ''
    reportMarkdown.value = data.trend_markdown || ''
    stats.value = data.stats || {}
    // 默认展开所有趋势
    trends.value.forEach((_, i) => expandedTrends.add(i))
  } catch (e) {
    console.error('获取报告失败:', e)
  } finally {
    loading.value = false
  }
}

async function generateReport() {
  if (!selectedMonth.value) return
  generating.value = true
  try {
    await axios.post('/api/report/generate', {
      month: selectedMonth.value,
      dimensions: selectedDimensions.value.length ? selectedDimensions.value : [],
    })
    await loadReport()
  } catch (e) {
    alert(`生成失败: ${e.response?.data?.message || e.message}`)
  } finally {
    generating.value = false
  }
}

async function exportMarkdown() {
  if (!selectedMonth.value) return
  exporting.value = true
  try {
    const response = await axios.get('/api/report/export-markdown', {
      params: { month: selectedMonth.value },
      responseType: 'blob'
    })
    
    // 创建下载链接
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `${selectedMonth.value}_趋势报告.md`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (e) {
    alert(`导出失败: ${e.response?.data?.message || e.message}`)
  } finally {
    exporting.value = false
  }
}
</script>
