# ADR-0005：离线 OpenAI-compatible provider adapter

- 状态：Accepted for Stage 5 P5 implementation
- 日期：2026-09-20
- 上游：ADR-0001、ADR-0003、ADR-0004
- 基线：Stage 4 已发布提交 `59c3357`
- 范围：EoH 与 generation-local RoCo provider adapter 的离线协议验证

## 背景

Stage 2–4 只使用确定性的 `MockLLMProvider`。ADR-0001 要求把 LLM calls、输入/输出
tokens、generated candidates、valid evaluations、cost 和 wall time 分开记账；
ADR-0003 固定了 EoH/RoCo 的结构化请求、角色温度和失败降级；ADR-0004 又明确指出，
Mock 的字符预算不能冒充真实模型 tokenizer。

首次 OpenAI-compatible 接入必须先验证请求、响应、错误和预算边界，但本阶段没有真实
网络、凭据或费用授权。因此本 ADR 只接受一个可注入 fake transport 的 adapter，
不实现或选择任何 HTTP 客户端，也不声称完成真实 provider 互操作或模型实验。

## 决策

### 1. adapter 只通过显式依赖注入构造

`OpenAICompatibleProvider` 构造时必须显式接收：

1. 非敏感的 `OpenAICompatibleConfig`；
2. 实现 `OpenAICompatibleTransport` protocol 的 transport；
3. 实现版本化 `TokenCounter` protocol 的模型 token counter；
4. 带版本、币种和输入/输出单价的 `PricingTable`。

仓库不提供 HTTP/network transport 实现。adapter 模块在 import、构造和默认路径中均
不得创建 socket、HTTP client 或后台任务。transport 请求对象不能表示 endpoint、API
key、Authorization header 或其他认证字段。任何未来网络 transport 都属于独立任务，
必须在单独授权下负责凭据和底层异常脱敏，并保证自身没有隐式重试。

adapter 不读取 `os.environ`、`.env`、keyring 或进程外的凭据来源。`.env.example` 只
保留这一安全说明，不再列出 endpoint、key 或真实模型字段。只有调用者显式构造 adapter
并注入依赖时该路径才存在；现有 CLI、smoke 和配置仍默认构造 `MockLLMProvider`。

### 2. 本版本只覆盖 EoH 和 generation-local RoCo

adapter 实现现有 `LLMProvider.generate()` 和 `RoleLLMProvider.generate_role()` 边界：

- EoH 只接受 `E1`、`E2`、`M1`、`M2`，输出恰好一个包含非空
  `description` 与 `code` 的候选；
- Explorer、Exploiter 和 Integrator 输出同一严格单候选对象；
- Critic 只输出恰好一个非空 `feedback` 字段，不输出候选或虚构分数；
- adapter 原样使用现有 RoCo `prompt_version` 和请求温度，不覆盖 Explorer `1.3`、
  Exploiter `0.8`、Critic/Integrator `1.0` 的既有默认值；
- objective 仍固定为 minimize，所有候选仍经过既有 AST、spawn evaluator、timeout、
  `BudgetLedger` 和统一 Top-N。

本版本不实现 `MemoryLLMProvider.summarize_memory()` 或
`generate_memory_mutation()`。Stage 4 memory runtime 和
`configs/smoke/tsp_memory_mock.yaml` 继续只使用 Mock；共享类型中即使存在
`memory_mutation` action，也不能据此声称 OpenAI-compatible memory 路径已接通。

### 3. 请求和响应采用版本化严格契约

每次请求记录 provider、model、prompt、request contract、pricing 和 token-counter
版本。`roco-openai-compatible-request-v1` 是本实现的 provider/adapter contract 版本，
并与 provider 名称及 audit schema 版本一起区分后续不兼容修改。transport-neutral 请求
固定为单结果、非流式、严格 JSON schema，并显式携带 temperature、最大输出 tokens
和 timeout。

成功响应必须满足受限的 OpenAI-compatible chat-completion envelope：模型名匹配、
恰好一个 choice、assistant content 为 JSON、finish reason 合法，并且 envelope、choice、
message、usage 和角色输出均拒绝未知或缺失字段。JSON 重复 key、NaN、Infinity、类型错、
空字符串和多候选都 fail closed。格式正确但不符合契约的内容不能增加
`generated_candidates`，也不能被猜测、修复或从自由文本中提取。

错误至少分类为：

- `timeout`；
- `retryable_transport`；
- `auth_permission`；
- `rate_limit`；
- `malformed_json`；
- `schema_error`；
- `provider_error`。

实现还可细分 `usage_error`、`context_length` 和 `budget_exceeded`。所有公开错误消息为
固定安全文本；不得拼接上游响应正文、异常 repr、endpoint、header、认证字段或原始
provider request ID。

### 4. token counter 与上下文决策是独立版本化边界

`TokenCounter` 必须声明不可变的 `contract_version` 和精确 `model_name`，后者必须与
adapter 模型一致。它对实际序列化请求计数；字符数、单词数或 Stage 4 Mock 的字符预算
都不是合法的真实模型 token counter。

adapter 为输出预留 `max_output_tokens`。若输入超限，只能按确定顺序删除被标记为可选的
反馈或候选文本，并在 `ContextAudit` 中记录原始/最终 token 数、删除字段、counter 版本
和 `within_limit|truncated|rejected` 决定。system/output contract 和核心结构字段不删除；
删除所有可选字段后仍超限则在调用 transport 前拒绝。此协议不改变 ADR-0004 的 Mock
memory 字符截断行为。

### 5. transport acceptance 决定 LLM-call 结算

每个 attempt 发送前，账本以一次 call、已计数输入、最大输出和相应最大费用做保守
preflight。达到或预计越过任一硬预算时不调用 transport。

transport 必须明确报告请求是否已被接受：

- `accepted=false`：不增加 LLM call、tokens 或 cost；
- `accepted=true`：无论随后成功、返回错误、解析失败还是 schema 失败，都恰好增加一次
  `llm_calls`；每个已接受的 retry attempt 分别结算；
- 成功或带 usage 的失败：按 provider usage 结算 input/output tokens，并用版本化价格表
  计算 cost；
- 已接受但 usage 缺失或非法：仍增加 call，但 tokens/cost 保持未知，不以 `0`、字符数或
  token-counter 估算回填；审计标记 `accounting_complete=false`，且该 adapter 实例关闭
  后续发送。成功响应的 usage 错误返回不可重试的 `usage_error`；HTTP/transport 错误仍
  保留其 timeout/auth/rate/provider 主分类，但在结算不完整时不得重试；
- provider 报告的实际 usage 若使已接受工作越过硬预算，真实消耗不得回滚；记录
  `budget_exceeded` 并立即停止后续消费动作。

成功响应的 prompt tokens 必须等于注入 counter 对已发送请求的计数，completion tokens
不得超过预留上限，total 必须等于两者之和。价格按每百万 input/output tokens 分开计算；
币种必须与 `BudgetLedger` 一致。未知价格不得伪装为零。

只有严格解析出候选时增加 `generated_candidates`；Critic feedback 不增加该计数。
`valid_evals` 仍只由 evaluator 在得到有限、可比较的目标值后增加。

### 6. timeout 和 retry 显式且有限

每次 `send()` 都传递正的有限 `timeout_seconds`。总 attempts 固定为
`1 + max_retries`，其中 `max_retries` 是非负整数；默认或任一路径都不存在无限 retry。

只有 `timeout`、`retryable_transport`、`rate_limit` 和明确的 HTTP 5xx provider error
可以在预算仍未达到、usage 结算完整且尚有 attempts 时重试。auth/permission、其他
provider、usage、JSON、schema、context 和 budget 错误不重试。
这只是 transport-level retry，不是 ADR-0004/G-015 禁止的内容修复请求；adapter 不修改
prompt 后重试，也不为非法代码自动请求模型修复。

### 7. 审计对象只保存脱敏元数据

每个 attempt 写入版本化 `ProviderCallAudit`，至少记录逻辑请求序号、attempt、operation/
role、prompt/provider-contract/model/pricing/token-counter 版本、timeout、temperature、
accepted、usage、cost、状态、错误分类、是否计划 retry 和上下文决定。

请求、响应和 provider request ID 只保存 SHA-256，不保存原始消息、响应正文或 ID。
认证信息根本不进入 adapter 数据模型。日志、异常和序列化审计使用同一安全边界；测试
必须用诱饵敏感字符串证明它们不会出现在这些对象中。

## 离线验证边界

P5 的测试只能注入 fake transport、fake model token counter 和 synthetic versioned
pricing table。应覆盖 EoH/RoCo 成功、角色温度、timeout、有限 retry、
accepted-then-error、usage/cost、预算越界、JSON/schema 错误、上下文决策、脱敏和默认
路径不构造 transport。

`configs/providers/openai_compatible_fake.example.yaml` 是无 endpoint、无凭据、无真实
价格的说明性示例，不是网络 smoke 配置。通过这些测试只说明 adapter 的离线协议、
失败和记账行为可审计；它不验证 HTTP、TLS、认证、某个供应商的实际兼容性、真实
tokenizer、真实价格、模型输出质量或论文结果。

## 后果

正面结果是 provider 边界可以在 CI 中完全离线复核，已接受失败不会从预算中消失，且
原始认证与响应内容不会进入持久化审计。代价是本仓库当前仍不能调用任何真实
OpenAI-compatible 服务。若以后需要真实 transport，必须另行获得网络、凭据和费用授权，
选择并审计具体 tokenizer/价格表，增加真实互操作验证，并继续保持 Mock 默认与三个既有
smoke 的精确回归。
