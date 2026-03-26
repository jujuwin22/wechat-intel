# 实施计划: wechat-intel 项目剥离与重构

- [x] **任务1:** 创建项目脚手架（README、.gitignore、.env.example、目录结构）
  - _关联需求: #6_

- [x] **任务2:** 迁移配置文件（companies.yaml精简版、wechat_channels.yaml、feed_settings.yaml、source_credibility.yaml、prompts/）
  - _关联需求: #6_

- [x] **任务3:** 迁移数据模型（server/feed/models.py）
  - _关联需求: #2_

- [x] **任务4:** 迁移微信采集模块（server/collector/collector.py、config.py），解耦硬编码路径，API Key统一从.env读取
  - _关联需求: #1_

- [x] **任务5:** 迁移docker-compose.yml到项目根目录
  - _关联需求: #1_

- [x] **任务6:** 迁移Feed Pipeline（ingest、splitter、quality_filter、dedup、renderer、trend_report、pipeline），适配新路径
  - _关联需求: #2_

- [x] **任务7:** 创建Flask API入口（server/app.py），实现8个API端点
  - _关联需求: #3, #4, #5_

- [x] **任务8:** 创建server/requirements.txt（最小依赖集）
  - _关联需求: #6_

- [x] **任务9:** 初始化Vue前端项目（Vite + Vue 3 + TailwindCSS + Vue Router + Axios）
  - _关联需求: #3, #4, #5_

- [x] **任务10:** 实现前端布局组件（App.vue内置导航栏）
  - _关联需求: #3, #4, #5_

- [x] **任务11:** 实现采集控制页（CollectView.vue，SSE日志流、启动采集、watermark展示）
  - _关联需求: #3_

- [x] **任务12:** 实现情报速递页（FeedView.vue，事件列表、维度筛选、触发Pipeline）
  - _关联需求: #4_

- [x] **任务13:** 实现趋势报告页（ReportView.vue，趋势分析展示、月份切换）
  - _关联需求: #5_

- [x] **任务14:** 配置Vite开发代理 + Flask静态文件服务（生产模式）
  - _关联需求: #6_

- [x] **任务15:** 端到端验证：前端 build 成功，Flask app 导入成功，依赖安装完成
  - _关联需求: #1, #2, #3, #4, #5_

- [x] **任务16:** 完善README（安装、配置、运行说明、API端点、CLI命令、项目结构）
  - _关联需求: #6_
