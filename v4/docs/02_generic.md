# 通用与科研示例

GenericChangeAdapter.snapshot 返回内存 AuthoritySnapshot；assess 校验 max_workers 范围，超过演示阈值进入 REVIEW；execute 在 RLock 内比较整个权威指纹，记录应用并变更版本。ResearchWorkflowAdapter 继承这个合成存储，重写 action、resource_type 和三项参数校验，合法请求也要求 REVIEW。

这些示例没有接入配置中心、科研设备或 Redis；RLock 只保护同一进程。公开 tests 覆盖拒绝、状态漂移和审批消费。企业接入应把 snapshot 和 CAS 移到真正权威系统，不复制内存锁冒充分布式事务。
