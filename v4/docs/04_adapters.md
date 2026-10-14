# 接口不是完成部署

DomainAdapter.snapshot(request) -> AuthoritySnapshot；assess(request, authority) -> tuple[GateDecision, tuple[str,...]]；execute(request, expected) -> str。结构类型 Protocol 不要求继承，但也不自动检查业务真实性。execute 必须自己在权威提交处重新比对 expected，返回非空实际回执。

Runtime 默认 fail-closed；可信适配器被替换、管理员绕过 Runtime 或调用方伪造认证主体不属于本地类型检查能解决的攻击。只有四个公开合成适配路径及测试已实际执行，任意第三方系统标 EXTENSION_POINT。
