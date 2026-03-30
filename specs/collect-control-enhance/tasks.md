# 实施计划: 采集控制增强

- [x] **任务1:** 后端 - 新增 GET /api/collect/accounts 接口
  - _关联需求: #2_
- [x] **任务2:** 后端 - 新增 DELETE /api/collect/watermark 和 DELETE /api/collect/watermark/<name> 接口
  - _关联需求: #1_
- [x] **任务3:** 后端 - 扩展 POST /api/collect/run 接收 accounts 参数
  - _关联需求: #2_
- [x] **任务4:** 采集器 - config.py 新增 --accounts CLI 参数支持
  - _关联需求: #2_
- [x] **任务5:** 前端 - 水位线管理区域增加清除按钮
  - _关联需求: #1_
- [x] **任务6:** 前端 - 新增公众号勾选列表 + 采集时传入选中公众号
  - _关联需求: #2_
- [x] **任务7:** 验证 - 端到端测试（API验证通过，前端编译通过）
  - _关联需求: #1, #2_
