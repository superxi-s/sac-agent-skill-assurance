# 一个可执行的配额业务接入

运行根目录 examples/custom_domain.py。QuotaAdapter 独立实现三个方法：snapshot 从合成内存权威返回对象、归属、版本与期限；assess 只允许演示请求并强制 REVIEW；execute 在锁内比较 expected 后递增版本，返回合成回执。示例验证未授权用户被 BLOCK、合法确认执行、同一审批不可再写。

接生产需要替换的是可信权威及原子写，不是让 LLM 提供 snapshot。测试对象固定 quota=10→20，不来自任何真实客户。完整执行代码而非不可运行伪代码在 [配额示例](../examples/custom_domain.py)。
