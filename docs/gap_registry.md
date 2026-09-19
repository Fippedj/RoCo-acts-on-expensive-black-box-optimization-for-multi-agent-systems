# RoCo 缺口登记表

## 分类标准

- **论文明确**：当前精读材料存在可定位的论文陈述。
- **合理推断**：为把论文流程变成确定性接口所需，且与原文相容，但论文没有完整规定。
- **必须自行设计**：存在多种会实质影响结果/成本的选择，不能声称为论文复现值。

每个“合理推断”或“必须自行设计”项都必须在配置、run manifest 或 ADR 中显式出现；不得沉入代码常量。

| ID | 主题 | 分类 | 论文证据/缺口证据 | V1 处理 | 风险与待办 | Owner / 最晚阶段 |
|---|---|---|---|---|---|---|
| G-001 | 四角色职责 | 论文明确 | p.1 `S002`；p.4 `S006` | 保留四种独立策略接口，但 Stage 1 不实现 | prompt 细节仍需逐条审计 | Stage 3 / 角色协作前 |
| G-002 | 单代主顺序 | 论文明确 | p.3 `S005`；p.10 `S008` | 采用 `paper_spec/algorithm.md` 状态机 | 附录措辞可能把轮内/最终 Integrator 混写，需原 PDF 复核 | Stage 3 / 状态机实现前 |
| G-003 | 初始 Critic 与 `T` 轮边界 | 合理推断 | p.10 `S008` | 初始 Critic 不计入 `T`；每轮 E/X 后 Critic；最后 Integrator | 若原伪代码存在轮内 Integrator，调用预算会变化 | Stage 3 / 调用数测试前 |
| G-004 | 精英采样邻居边界 | 合理推断 | p.10 `S008`；分析稿 §5.3 | 使用排名权重 `1/(i+1)^k`，相邻伙伴规则配置化并记录 | 首尾排名、重复采样和不足两人的行为需逐式复核 | Stage 2 / sampler 接口前 |
| G-005 | LTReflect 写入内容 | 论文明确 + 自行设计 | p.4 `S007` 明确前后值与变化；p.10–16 `S011` 指出结构缺失 | JSONL 事件至少含角色、候选引用、反馈、前/后分数、方向标准化 `delta_g`、成功标志、代/轮次 | schema 版本、崩溃恢复和脱敏需测试 | Stage 4 / memory 实现前 |
| G-006 | LTReflect 存储后端 | 必须自行设计 | p.10–16 `S011` | JSONL append-only；摘要另存版本/哈希，不引入向量库 | 并发写、原子提交、文件增长 | ADR-0001；Stage 4 |
| G-007 | LTReflect 检索 | 必须自行设计 | p.10–16 `S011` | 最近 `K=5` 条符合当前角色/任务作用域的有效事件；确定性排序 | “有效”的精确定义、成功/失败平衡尚需协议 | ADR-0001；Stage 4 |
| G-008 | memory-guided mutation prompt | 必须自行设计 | p.4 `S007`、p.10 `S008` 只给机制；`S011` 指出 prompt/检索不完整 | 输入契约：角色视角、当前精英、累计摘要、最近 K 个带数值证据事件、输出 schema；每精英三角色各一次 | 完整模板、注入顺序、反提示注入防护待 Stage 4 版本化 | Stage 4 / prompt 冻结前 |
| G-009 | token 预算 | 必须自行设计 | p.10–16 `S011` | 分别记录输入/输出/总 token；每角色硬上限必须显式配置，当前不宣称论文值 | tokenizer/model 差异；截断后语义丢失 | Stage 2 / provider schema 前 |
| G-010 | 上下文截断 | 必须自行设计 | p.10–16 `S011` | 优先级：任务/输出契约 > 当前候选与目标值 > 最近数值证据 >摘要 > 较旧原文；记录每次删除 | 精确 token 配额及摘要可信度待测试 | Stage 3 / prompt builder 前 |
| G-011 | `G`（总代数） | 必须自行设计 | 当前材料无固定值；p.10 `S008` 仅有代循环 | 不写死，以配置的硬预算停止；smoke 的 `G=2` 只用于测试 | 预算作用域不清可能影响论文曲线对齐 | Stage 2 / run config 前 |
| G-012 | 400 calls 与 400 evaluations | 论文陈述冲突/口径不完整 | p.5 `S009`：400 calls/generation；Appendix D 摘要：maximum 400 evaluations；p.10–16 `S011` | 两个独立 counter/limit，连同 tokens、candidates、cost、wall time 分账；实验指定首个触发即停止 | 必须复核 PDF 与可能的作者代码/回复 | ADR-0001；Stage 2 |
| G-013 | generated candidate 定义 | 必须自行设计 | 论文未定义预算术语 | 成功解析为一个新方案即计数；不要求代码有效或已评估 | 多方案单响应如何拆分须由输出 schema 禁止或定义 | Stage 2 / core models 前 |
| G-014 | valid evaluation 定义 | 必须自行设计 | 论文未定义失败/缓存计数 | 只有完成目标函数并产生可比较数值才增加；缓存命中单列，默认不重复增加 | 超时/部分实例成功/NaN 的规则待 evaluator 协议 | Stage 2 / evaluator 前 |
| G-015 | 无效代码重试 | 必须自行设计 | p.10–16 `S011` | 建议静态检查→小样例→最多 2 次修复；每次调用照常计费，最终失败保留事件 | 重试上限尚未由本 ADR 固化，需独立 ADR/配置 | Stage 2 / validation pipeline 前 |
| G-016 | 训练超时 | 证据不足，必须复核 | `S009` 聚合实验设置但无逐项原文；`S011` 指出复现细节不足 | 暂保留 60 s、CVRP 120 s 工程占位；明确非论文设定 | 必须确认超时作用域；否则有效评估不可比 | Stage 2 / TSP evaluator 前 |
| G-017 | 并行调度 | 必须自行设计 | 论文未披露；`S011` | V1 串行；并行结果不得影响随机流、tie-break 或 budget commit 顺序 | 后续并行需 reservation/commit 语义 | Stage 2 串行；Stage 5 并行 |
| G-018 | 随机种子 | 必须自行设计 | p.10–16 `S011` | 工程默认 seed 2025；派生并记录采样、mock、evaluator、实例等独立随机流 | 真实 LLM 通常不能完全确定性复现 | Stage 2 / RunManifest 前 |
| G-019 | Top-N tie-break/去重 | 必须自行设计 | p.3 `S005` 只明确确定性 Top-N | 内容哈希去重；按分数稳定排序，明确候选 ID tie-break | 去重是否节省 evaluation 需和缓存规则一致 | Stage 2 / population 前 |
| G-020 | Critic better/worse 措辞矛盾 | 论文歧义 | p.10–16 `S011`；分析稿 §5.6 | 原 prompt 原样存档，修订版另设版本并写变更理由，不静默修正 | 可能反转反馈方向 | Stage 3 / prompt 冻结前 |
| G-021 | 每代候选/调用数量 | 必须自行设计 | p.3 `S005`、p.10 `S008` 未给足算子 multiplicity 与精英集合大小 | 全部 multiplicity 配置化；用 Mock 手工演算预算 | 无法仅从 400 反推 | Stage 2 / EoH MVP 前 |
| G-022 | Mock 与真实 LLM 的优先级 | 必须自行设计 | 论文使用 GPT-4o-mini（`S009`）；工程复现需要确定性路径 | CI、开发和验收优先 Mock；真实 provider 仅在确定性路径通过后启用 | Mock 只验证控制流，不验证论文性能 | ADR-0001；Stage 2 |

## 当前阻断项

Stage 1 文档本身无阻断项。Stage 2 MVP 已通过 ADR-0002 固化：预算按单次 run 作用、候选/evaluation 的计数定义、派生随机流、Top-N tie-break、每算子候选数，以及 smoke evaluator 的单候选超时作用域。论文训练超时仍未被这些工程值替代，留待复现实验协议核验。

进入 Stage 3 前仍须对原 PDF 逐式核验 G-002 至 G-004，并处理 Critic prompt 的 better/worse 歧义；这些问题未进入 Stage 2 代码路径。
