# RoCo 缺口登记表

## 分类标准

- **论文明确**：当前精读材料存在可定位的论文陈述。
- **合理推断**：为把论文流程变成确定性接口所需，且与原文相容，但论文没有完整规定。
- **必须自行设计**：存在多种会实质影响结果/成本的选择，不能声称为论文复现值。

每个“合理推断”或“必须自行设计”项都必须在配置、run manifest 或 ADR 中显式出现；不得沉入代码常量。

| ID | 主题 | 分类 | 论文证据/缺口证据 | V1 处理 | 风险与待办 | Owner / 最晚阶段 |
|---|---|---|---|---|---|---|
| G-001 | 四角色职责 | 论文明确 | p.1 `S002`；p.4 `S006` | Stage 3 以版本化 prompt 和结构化角色请求实现 Explorer、Exploiter、Critic、Integrator；共享 provider 但契约和温度独立 | 真实模型前仍需逐条核对附录 prompt；Mock 只验证协议 | Stage 3 已落地；真实 provider 前复核 |
| G-002 | 单代主顺序 | 论文明确 | p.3 `S005`；p.10 `S008` | Stage 3 实现精英对→初始 Critic→`T` 轮 E/X+Critic→最终 Integrator→统一 Top-N；`G10/G11` 明确留给 Stage 4 | 附录对轮内/最终 Integrator 的措辞仍需原 PDF 复核，不影响已版本化的 Stage 3 口径 | ADR-0003；Stage 4 接续 |
| G-003 | 初始 Critic 与 `T` 轮边界 | 合理推断 | p.10 `S008` | 初始 Critic 记为 round 0 且不计入 `T`；每轮 E/X 后 Critic；最后 Integrator 也不增加轮次 | 若原伪代码存在轮内 Integrator，论文对齐调用预算会变化；不得静默改现有语义 | ADR-0003；已用调用顺序测试固化 |
| G-004 | 精英采样邻居边界 | 合理推断 | p.10 `S008`；分析稿 §5.3 | Stage 3 使用排名权重 `1/(i+1)^k`，seed 驱动并在 trace 中记录 ranks、`k` 与结果；不足两人由配置前置拒绝 | 邻居偏移的逐式论文对齐仍待原 PDF 复核 | Stage 3 已落地；论文数值复现前复核 |
| G-005 | LTReflect 写入内容 | 论文明确 + 自行设计 | p.4 `S007` 明确前后值与变化；p.10–16 `S011` 指出结构缺失 | JSONL 事件至少含角色、候选引用、反馈、前/后分数、方向标准化 `delta_g`、成功标志、代/轮次 | schema 版本、崩溃恢复和脱敏需测试 | Stage 4 / memory 实现前 |
| G-006 | LTReflect 存储后端 | 必须自行设计 | p.10–16 `S011` | JSONL append-only；摘要另存版本/哈希，不引入向量库 | 并发写、原子提交、文件增长 | ADR-0001；Stage 4 |
| G-007 | LTReflect 检索 | 必须自行设计 | p.10–16 `S011` | 最近 `K=5` 条符合当前角色/任务作用域的有效事件；确定性排序 | “有效”的精确定义、成功/失败平衡尚需协议 | ADR-0001；Stage 4 |
| G-008 | memory-guided mutation prompt | 必须自行设计 | p.4 `S007`、p.10 `S008` 只给机制；`S011` 指出 prompt/检索不完整 | 输入契约：角色视角、当前精英、累计摘要、最近 K 个带数值证据事件、输出 schema；每精英三角色各一次 | 完整模板、注入顺序、反提示注入防护待 Stage 4 版本化 | Stage 4 / prompt 冻结前 |
| G-009 | token 预算 | 必须自行设计 | p.10–16 `S011` | 分别记录输入/输出/总 token；Stage 2/3 使用 run-scoped 总硬上限，角色事件记录预算前后，当前不宣称论文值或每角色配额 | tokenizer/model 差异；真实 provider 若需每角色上限须新增配置 | Stage 2/3 已分账；真实 provider 前扩展 |
| G-010 | 上下文截断 | 必须自行设计 | p.10–16 `S011` | Stage 3 Mock 只传当前代结构化状态，不实现真实模型 token 截断；原优先级建议保留 | 精确 token 配额、删除审计及摘要可信度待真实 provider/Stage 4 测试 | Stage 4 或真实 provider 接入前 |
| G-011 | `G`（总代数） | 必须自行设计 | 当前材料无固定值；p.10 `S008` 仅有代循环 | 不写死，以配置的硬预算停止；Stage 2 smoke 的 `G=2` 与 Stage 3 smoke 的 `G=1` 都只是测试值 | 预算作用域不清可能影响论文曲线对齐 | Stage 2/3 run config |
| G-012 | 400 calls 与 400 evaluations | 论文陈述冲突/口径不完整 | p.5 `S009`：400 calls/generation；Appendix D 摘要：maximum 400 evaluations；p.10–16 `S011` | 两个独立 counter/limit，连同 tokens、candidates、cost、wall time 分账；实验指定首个触发即停止 | 必须复核 PDF 与可能的作者代码/回复 | ADR-0001；Stage 2 |
| G-013 | generated candidate 定义 | 必须自行设计 | 论文未定义预算术语 | 成功解析为一个新方案即计数；不要求代码有效或已评估 | 多方案单响应如何拆分须由输出 schema 禁止或定义 | Stage 2 / core models 前 |
| G-014 | valid evaluation 定义 | 必须自行设计 | 论文未定义失败/缓存计数 | 只有完成目标函数并产生可比较数值才增加；缓存命中单列，默认不重复增加 | 超时/部分实例成功/NaN 的规则待 evaluator 协议 | Stage 2 / evaluator 前 |
| G-015 | 无效代码重试 | 必须自行设计 | p.10–16 `S011` | Stage 2/3 不做 LLM 修复重试；静态检查/评估失败写结构化事件并安全跳过，调用照常记账 | 未来若加修复必须配置上限并保持原失败事件，不能改变现有 smoke 调用数 | 后续真实 provider ADR |
| G-016 | 训练超时 | 证据不足，必须复核 | `S009` 聚合实验设置但无逐项原文；`S011` 指出复现细节不足 | 暂保留 60 s、CVRP 120 s 工程占位；明确非论文设定 | 必须确认超时作用域；否则有效评估不可比 | Stage 2 / TSP evaluator 前 |
| G-017 | 并行调度 | 必须自行设计 | 论文未披露；`S011` | Stage 2/3 串行；并行结果不得影响随机流、tie-break 或 budget commit 顺序 | 后续并行需 reservation/commit 语义 | Stage 5 并行 |
| G-018 | 随机种子 | 必须自行设计 | p.10–16 `S011` | 工程默认 seed 2025；标签化派生并记录 Mock provider、TSP instance 和 RoCo collaboration/采样随机流 | 真实 LLM 通常不能完全确定性复现 | Stage 2/3 manifest |
| G-019 | Top-N tie-break/去重 | 必须自行设计 | p.3 `S005` 只明确确定性 Top-N | 候选 ID 含稳定内容摘要和谱系；有效候选按 `(score, candidate_id)` 排序；Stage 2/3 不做跨候选内容去重/缓存 | 若以后去重，是否节省 evaluation 与谱系保留需同时定义 | ADR-0002；后续缓存 ADR |
| G-020 | Critic better/worse 措辞矛盾 | 论文歧义 | p.10–16 `S011`；分析稿 §5.6 | 原歧义保留在论文资料；可执行 `roco-stage3-v1` 契约明确按 evaluator 方向和已验证数值比较，不从文本猜测分数 | 属于有意、已版本化的工程修订；论文 prompt 逐字复现必须单列实验 | ADR-0003；Stage 3 已固化 |
| G-021 | 每代候选/调用数量 | 必须自行设计 | p.3 `S005`、p.10 `S008` 未给足算子 multiplicity 与精英集合大小 | EoH multiplicity 继续配置化；Stage 3 每代协作一对精英、每轮 E/X 各一候选、末尾一个 Integrator 候选；Mock trace 可手工核对预算 | 无法仅从 400 反推；真实复现实验需单列 multiplicity | ADR-0002/0003；已用于 smoke |
| G-022 | Mock 与真实 LLM 的优先级 | 必须自行设计 | 论文使用 GPT-4o-mini（`S009`）；工程复现需要确定性路径 | CI、开发和验收使用角色感知 Mock；`eoh`/`roco` 均离线，真实 provider 不在 Stage 3 范围 | Mock 只验证控制流、失败和预算，不验证论文性能 | ADR-0001/0003；Stage 3 |
| G-023 | 单代协作 trace 与长期记忆的边界 | 必须自行设计 | 论文描述反思/记忆但未给可执行日志 schema；p.4 `S007`、p.10–16 `S011` | `roco-collaboration-trace-v1` 每代记录精英对、角色事件、候选/反馈、评估、预算前后与选择结果；只作 run audit，不供跨代检索 | JSONL 外形容易被误认为 LTReflect；报告必须注明 scope，Stage 4 另定 memory schema | ADR-0003；Stage 3 |
| G-024 | Stage 2/3 配置兼容分派 | 必须自行设计 | 论文未涉及仓库迁移兼容 | `evolution.mode: eoh|roco`；字段缺省按 `eoh`，旧 smoke 行为作为回归契约，RoCo 使用独立配置 | 后续新增模式不得改变缺省含义或旧候选顺序 | ADR-0003；Stage 3 |

## 当前阻断项

Stage 3 的离线工程路径没有未解决的实现阻断项。ADR-0002 继续固定旧 EoH smoke；
ADR-0003 固定四角色状态机、失败降级、配置分派和单代 trace。G-002–G-004 与
G-020 中未能从论文唯一确定的部分已作为显式工程口径版本化，而不是冒充作者原值。

进入论文数值复现或真实 provider 前，仍须回到原 PDF 逐式核验精英邻居采样、
Integrator 位置、Critic 原 prompt 和训练 timeout。进入 Stage 4 前必须另行实现并测试
LTReflect、跨代记忆存储/检索及 memory-guided mutation；Stage 3 的运行 trace 不能
用来宣称这些缺口已经关闭。
