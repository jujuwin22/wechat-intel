<template>
  <div class="min-h-screen bg-gray-50">
    <!-- 顶部导航 -->
    <nav class="bg-white border-b border-gray-200 shadow-sm">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex justify-between h-14">
          <div class="flex items-center space-x-8">
            <span class="text-lg font-bold text-gray-800">📡 微信情报系统</span>
            <router-link
              v-for="item in navItems"
              :key="item.path"
              :to="item.path"
              class="px-3 py-2 rounded-md text-sm font-medium transition-colors"
              :class="$route.path === item.path
                ? 'bg-blue-50 text-blue-700'
                : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'"
            >
              {{ item.icon }} {{ item.label }}
            </router-link>
          </div>
        </div>
      </div>
    </nav>

    <!-- 主内容 -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      <router-view />
    </main>
  </div>
</template>

<script setup>
const navItems = [
  { path: '/collect', label: '采集控制', icon: '🔄' },
  { path: '/feed', label: '情报速递', icon: '📰' },
  { path: '/report', label: '趋势报告', icon: '📊' },
]
</script>
