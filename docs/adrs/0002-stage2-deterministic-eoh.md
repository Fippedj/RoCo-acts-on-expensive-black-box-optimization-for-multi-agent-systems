# ADR-0002：Stage 2 确定性最小 EoH

- 状态：Accepted for Stage 2
- 日期：2026-09-19
- 上游：ADR-0001、`docs/gap_registry.md` G-009/G-011–G-019/G-021/G-022

## 决策

- smoke 的预算作用域是完整 run；任一硬上限达到后，账本拒绝启动下一项工作。一次恰好触及上限的原子操作允许完成。
- 初始化按 E1、E2、M1、M2 顺序循环生成 `N` 个候选。之后每代每个算子生成 `candidates_per_operator: 1` 个候选，父代与有效子代合并后选 Top-N。
- 默认最小化；有效候选按 `(score, candidate_id)` 排序破同分。无效候选保留结构化评估记录但不进入 Top-N。初始化会继续轮询算子直至获得 `N` 个有效候选（最多 `4N` 次），代内无效子代不补位；不执行 LLM 修复重试。
- smoke 使用 `generations=2` 作为工程测试值。`collaboration_rounds=1` 只做配置兼容与合法性校验，不触发任何 RoCo 协作。
- run seed 通过 SHA-256 标签化派生 Mock provider 与 TSP instance 的独立 seed，并写入 manifest。真实 LLM 的不可确定性不在本阶段处理。
- Mock token 是可重复的词数近似，分别记 input/output；不是任何真实模型 tokenizer 的论文复现值。Mock cost 明确为 0 USD。
- `evaluator_timeout_seconds=5` 作用于单个候选的 spawn 子进程执行，不代表论文训练超时。语法/签名/AST 拒绝发生在父进程，候选源码只在子进程编译执行。
- Stage 2 串行运行，不实现缓存、重试、并行 reservation 或断点续跑。

## 候选与预算数量

默认 smoke 初始化 4 个候选，随后执行 2 代，每代 E1/E2/M1/M2 各 1 个候选，因此无错误路径为：

```text
4 initialization + 2 generations * 4 operators = 12 candidates
12 mock LLM calls = 12 generated candidates = 12 valid evaluations
```

上限仍设为 20 calls、20 valid evaluations 和 20,000 mock tokens，所以正常 smoke 不应触及预算。

## 安全边界

AST allow-list、受限 builtins、spawn 子进程与 timeout 只用于隔离开发错误和简单失控循环。它们不能替代容器、独立 OS 用户、syscall/seccomp、filesystem/network namespace 或资源配额。Stage 2 不得执行来自不可信来源的候选代码。

## 明确延期

四角色、Critic/Integrator、协作轮次、反思、JSONL 长期记忆/检索、memory-guided mutation、真实 OpenAI-compatible 调用、论文规模 evaluator 和 EBBO 全部延期到相应后续阶段。
