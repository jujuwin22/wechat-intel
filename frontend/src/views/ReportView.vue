<template>
  <div class="space-y-6">
    <!-- 标题 + 控制 -->
    <div class="flex flex-wrap items-center justify-between gap-4">
      <h1 class="text-2xl font-bold text-gray-800">📊 趋势报告</h1>
      <select
        v-model="selectedMonth"
        @change="loadReport"
        class="border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500"
      >
        <option value="">选择月份</option>
        <option v-for="m in months" :key="m" :value="m">{{ m }}</option>
      </select>
    </div>

    <!-- 统计卡片 -->
    <div v-if="stats.total_events" class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
        <div class="text-2xl font-bold text-blue-600">{{ stats.total_events }}</div>
        <div class="text-xs text-gray-500 mt-1">事件总数</div>
      </div>
      <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
        <div class="text-2xl font-bold text-green-600">{{ stats.company_count || 0 }}</div>
        <div class="text-xs text-gray-500 mt-1">涉及公司</div>
      </div>
      <div
        v-for="(count, dim) in stats.dimensions"
        :key="dim"
        class="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center"
      >
        <div class="text-2xl font-bold" :style="{ color: dimColor(dim) }">{{ count }}</div>
        <div class="text-xs text-gray-500 mt-1">{{ dim }}</div>
      </div>
    </div>

    <!-- Markdown 渲染 -->
    <div v-if="reportMarkdown" class="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <div class="prose prose-sm max-w-none" v-html="renderedHtml"></div>
    </div>

    <!-- 空状态 -->
    <div v-else-if="!loading" class="bg-white rounded-lg shadow-sm border border-gray-200 p-12 text-center">
      <div class="text-4xl mb-3">📋</div>
      <div class="text-gray-500">{{ reportData.message || '暂无趋势报告，请先运行Pipeline生成' }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import { marked } from 'marked'

const months = ref([])
const selectedMonth = ref('')
const reportData = ref({})
const reportMarkdown = ref('')
const stats = ref({})
const loading = ref(false)

const dimColors = {
  '薪酬激励': '#e74c3c',
  '组织架构': '#3498db',
  '人才发展': '#2ecc71',
  '企业文化': '#f59e0b',
  '未分类': '#95a5a6',
}

function dimColor(dim) {
  return dimColors[dim] || '#95a5a6'
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
  try {
    const { data } = await axios.get('/api/report', { params: { month: selectedMonth.value } })
    reportData.value = data
    reportMarkdown.value = data.trend_markdown || ''
    stats.value = data.stats || {}
  } catch (e) {
    console.error('获取报告失败:', e)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.prose h1 { @apply text-xl font-bold text-gray-800 mt-6 mb-3; }
.prose h2 { @apply text-lg font-semibold text-gray-700 mt-5 mb-2 pb-1 border-b border-gray-200; }
.prose h3 { @apply text-base font-medium text-gray-700 mt-3 mb-1; }
.prose p { @apply text-sm text-gray-600 my-2; }
.prose ul { @apply list-disc pl-5 text-sm text-gray-600; }
.prose ol { @apply list-decimal pl-5 text-sm text-gray-600; }
.prose blockquote { @apply border-l-4 border-blue-300 pl-4 italic text-gray-500 my-3; }
.prose hr { @apply my-4 border-gray-200; }
.prose strong { @apply font-semibold text-gray-700; }
.prose em { @apply text-gray-500; }
</style>
