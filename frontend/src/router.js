import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/collect',
  },
  {
    path: '/collect',
    name: 'Collect',
    component: () => import('./views/CollectView.vue'),
  },
  {
    path: '/feed',
    name: 'Feed',
    component: () => import('./views/FeedView.vue'),
  },
  {
    path: '/report',
    name: 'Report',
    component: () => import('./views/ReportView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
