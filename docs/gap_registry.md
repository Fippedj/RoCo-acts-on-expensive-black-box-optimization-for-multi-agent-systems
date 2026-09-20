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
| G-005 | LTReflect 写入内容 | 论文明确 + 自行设计 | p.4 `S007` 明确前后值与变化；p.10–16 `S011` 指出结构缺失 | ADR-0004 已发布并冻结 `roco-memory-event-v1`；minimize 的 `delta_g=before-after`，失败保留 null 结果，候选代码不复制入 memory | P3a 已由 `a0b24b1` 实现严格 schema、trace 转换器和脱敏测试；65 passed 与完整质量门禁通过，待正常推送 | P3a 已完成 |
| G-006 | LTReflect 存储后端 | 必须自行设计 | p.10–16 `S011` | 每代不可变 JSONL segment + 摘要/checkpoint；commit-last marker 以长度和 SHA-256 验证 | P3a 已实现 fsync/原子 rename、孤儿检测及 checkpoint 恢复测试；待正常推送 | ADR-0004；P3a 已完成 |
| G-007 | LTReflect 检索 | 必须自行设计 | p.10–16 `S011` | 前代已提交、同 benchmark/objective/role 的 `K=5`；默认最近改善 3 条、其他/失败 2 条，不足跨类补位，最终旧到新注入 | P3b 提交 `576b1dd` 已实现并验证 commit-only 读取、3/2 作用域、补位、旧到新排序及审计；远端状态实时核验 | ADR-0004；P3b 已完成 |
| G-008 | memory-guided mutation prompt | 必须自行设计 | p.4 `S007`、p.10 `S008` 只给机制；`S011` 指出 prompt/检索不完整 | 每个配置化精英按 E/X/I 各一次；输入为任务契约、精英、角色摘要、K 条数值事件，输出单候选严格 JSON；外部文本作为数据编码 | P3b 提交 `576b1dd` 以 opt-in Mock 路径接入每精英三候选、统一 evaluator/Top-N 和结构化失败；44/28 smoke 已通过 | ADR-0004；P3b 已完成 |
| G-009 | token 预算 | 必须自行设计 | p.10–16 `S011` | 分别记录输入/输出/总 token；Stage 2/3 使用 run-scoped 总硬上限，角色事件记录预算前后，当前不宣称论文值或每角色配额 | tokenizer/model 差异；真实 provider 若需每角色上限须新增配置 | Stage 2/3 已分账；真实 provider 前扩展 |
| G-010 | 上下文截断 | 必须自行设计 | p.10–16 `S011` | ADR-0004 固定保留优先级和删除审计；Mock 用确定性字符/字段预算，真实 provider 必须另加 tokenizer 契约 | P3b `576b1dd` 已按事件文本→完整旧事件→摘要文本执行并记录审计；字符预算仍不等于模型 token | P3b 已完成；真实 provider 前再版本化 |
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
| G-025 | trace 到长期事件的边界 | 必须自行设计 | 论文没有日志 schema；Stage 3 trace 明确 generation-local | 纯转换器从 proposal/compare/integrate 派生事件；初始 Critic 不入长期 memory；当代事件提交前不可被历史检索 | P3a 已完成成功/失败 mapping、Critic 来源和 selected 回填测试；待正常推送 | ADR-0004；P3a 已完成 |
| G-026 | 角色摘要 multiplicity | 必须自行设计 | 论文说明 LTReflect 机制但未披露每代调用数 | 每代 E/X/I 各一次；Critic 反馈作为证据但不建独立长期摘要；失败沿用旧/空摘要 | P3b `576b1dd` 已实现并验证固定 E/X/I 次序、严格结构响应、旧/空回退和预算停止 | ADR-0004；P3b 已完成 |
| G-027 | 代级恢复 | 必须自行设计 | 论文未披露 crash consistency | population、账本、随机/provider 游标进入 JSON checkpoint；只从连续有效 commit 恢复，半写代忽略 | P3a 已实现 JSON-safe snapshot、连续 commit 扫描和恢复读取；待正常推送 | ADR-0004；P3a 已完成 |
| G-028 | memory 候选去重/cache | 必须自行设计 | 论文没有预算口径；Stage 2/3 当前不去重 | Stage 4 V1 仍不去重、不缓存；相同代码照常生成和评估，可仅记录代码哈希 | 成本较高但保持账本连续；未来改变需新 ADR/cache-hit counter | ADR-0004；后续阶段 |

## 当前阻断项

Stage 3 的离线工程路径没有未解决的实现阻断项。ADR-0002 继续固定旧 EoH smoke；
ADR-0003 固定四角色状态机、失败降级、配置分派和单代 trace。G-002–G-004 与
G-020 中未能从论文唯一确定的部分已作为显式工程口径版本化，而不是冒充作者原值。

进入论文数值复现或真实 provider 前，仍须回到原 PDF 逐式核验精英邻居采样、
Integrator 位置、Critic 原 prompt 和训练 timeout。P2 已完成：Stage 4 的 schema、检索、
摘要、mutation 与恢复协议已经由 `cf1e06b`/ADR-0004 设计冻结并发布。P3a 事实层与恢复
底座已由 `a0b24b1` 提交并通过 65 passed、Ruff、mypy、doctor、Stage 2 12/12 与 Stage 3
18/13 smoke。P3b 已由 `576b1dd` 形成本地实现提交，并通过 75 tests、完整质量门禁和
44/28 memory smoke；远端同步状态必须实时核验。Stage 4 尚未整体完成，下一任务 P4
仍需 engine 级中断恢复、不中断/恢复端到端等价与 memory/no-memory 消融验收。
