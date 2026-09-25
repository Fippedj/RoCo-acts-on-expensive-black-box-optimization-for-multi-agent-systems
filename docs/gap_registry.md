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
| G-009 | token 预算 | 必须自行设计 | p.10–16 `S011` | 分别记录输入/输出/总 token；Mock 词数记账保持原回归，Stage 5 adapter 只接受 provider usage 作为结算事实，并用显式注入、带 model/version 的 token-counter 做发送前上下文预检 | usage 缺失/非法时只结算可确认的 accepted call，不能用 counter、字符数或 0 回填；真实 tokenizer 仍待具体供应商验证 | ADR-0005；fake transport 已覆盖 |
| G-010 | 上下文截断 | 必须自行设计 | p.10–16 `S011` | ADR-0004 的 Mock 字符/字段优先级保持不变；Stage 5 adapter 新增独立的 `roco-provider-context-audit-v1` token-counter 契约，按固定顺序删除可选反馈/候选文本并保留必需契约字段 | fake counter 只验证协议，不能证明真实 tokenizer 精度；Stage 4 memory 的真实模型 token 截断仍未接线 | ADR-0004/0005；provider adapter 已离线验证 |
| G-011 | `G`（总代数） | 必须自行设计 | 当前材料无固定值；p.10 `S008` 仅有代循环 | 不写死，以配置的硬预算停止；Stage 2 smoke 的 `G=2` 与 Stage 3 smoke 的 `G=1` 都只是测试值 | 预算作用域不清可能影响论文曲线对齐 | Stage 2/3 run config |
| G-012 | 400 calls 与 400 evaluations | 论文陈述冲突/口径不完整 | p.5 `S009`：400 calls/generation；Appendix D 摘要：maximum 400 evaluations；p.10–16 `S011` | 两个独立 counter/limit，连同 tokens、candidates、cost、wall time 分账；实验指定首个触发即停止 | 必须复核 PDF 与可能的作者代码/回复 | ADR-0001；Stage 2 |
| G-013 | generated candidate 定义 | 必须自行设计 | 论文未定义预算术语 | 成功解析为一个新方案即计数；不要求代码有效或已评估 | 多方案单响应如何拆分须由输出 schema 禁止或定义 | Stage 2 / core models 前 |
| G-014 | valid evaluation 定义 | 必须自行设计 | 论文未定义失败/缓存计数 | 只有完成目标函数并产生可比较数值才增加；缓存命中单列，默认不重复增加 | 超时/部分实例成功/NaN 的规则待 evaluator 协议 | Stage 2 / evaluator 前 |
| G-015 | 无效代码重试 | 必须自行设计 | p.10–16 `S011` | Stage 2–4 仍不做内容/代码修复；ADR-0005 只允许 timeout、retryable transport、rate limit 和可重试 HTTP 5xx 在显式 `max_retries` 内重发同一请求，每个 accepted attempt 单独计费 | transport retry 不等于 prompt 修复；JSON/schema/auth/usage/context/budget 错误不得重试，既有 Mock smoke 调用数不变 | ADR-0005；fake transport 已覆盖 |
| G-016 | 训练超时 | 证据不足，必须复核 | `S009` 聚合实验设置但无逐项原文；`S011` 指出复现细节不足 | 暂保留 60 s、CVRP 120 s 工程占位；明确非论文设定 | 必须确认超时作用域；否则有效评估不可比 | Stage 2 / TSP evaluator 前 |
| G-017 | 并行调度 | 必须自行设计 | 论文未披露；`S011` | Stage 2/3 串行；并行结果不得影响随机流、tie-break 或 budget commit 顺序 | 后续并行需 reservation/commit 语义 | Stage 5 并行 |
| G-018 | 随机种子 | 必须自行设计 | p.10–16 `S011` | 工程默认 seed 2025；标签化派生并记录 Mock provider、TSP instance 和 RoCo collaboration/采样随机流 | 真实 LLM 通常不能完全确定性复现 | Stage 2/3 manifest |
| G-019 | Top-N tie-break/去重 | 必须自行设计 | p.3 `S005` 只明确确定性 Top-N | 候选 ID 含稳定内容摘要和谱系；有效候选按 `(score, candidate_id)` 排序；Stage 2/3 不做跨候选内容去重/缓存 | 若以后去重，是否节省 evaluation 与谱系保留需同时定义 | ADR-0002；后续缓存 ADR |
| G-020 | Critic better/worse 措辞矛盾 | 论文歧义 | p.10–16 `S011`；分析稿 §5.6 | 原歧义保留在论文资料；可执行 `roco-stage3-v1` 契约明确按 evaluator 方向和已验证数值比较，不从文本猜测分数 | 属于有意、已版本化的工程修订；论文 prompt 逐字复现必须单列实验 | ADR-0003；Stage 3 已固化 |
| G-021 | 每代候选/调用数量 | 必须自行设计 | p.3 `S005`、p.10 `S008` 未给足算子 multiplicity 与精英集合大小 | EoH multiplicity 继续配置化；Stage 3 每代协作一对精英、每轮 E/X 各一候选、末尾一个 Integrator 候选；Mock trace 可手工核对预算 | 无法仅从 400 反推；真实复现实验需单列 multiplicity | ADR-0002/0003；已用于 smoke |
| G-022 | Mock 与真实 LLM 的优先级 | 必须自行设计 | 论文使用 GPT-4o-mini（`S009`）；工程复现需要确定性路径 | CI、CLI、smoke 和缺省选择继续使用角色感知 Mock；Stage 5 adapter 只有显式依赖注入的 fake-transport 测试，仓库不提供 HTTP transport | Mock/fake 只验证控制流、协议、失败和预算；不验证真实兼容性、模型质量或论文性能 | ADR-0001/0003/0005；adapter 已离线验证 |
| G-023 | 单代协作 trace 与长期记忆的边界 | 必须自行设计 | 论文描述反思/记忆但未给可执行日志 schema；p.4 `S007`、p.10–16 `S011` | `roco-collaboration-trace-v1` 每代记录精英对、角色事件、候选/反馈、评估、预算前后与选择结果；只作 run audit，不供跨代检索 | JSONL 外形容易被误认为 LTReflect；报告必须注明 scope，Stage 4 另定 memory schema | ADR-0003；Stage 3 |
| G-024 | Stage 2/3 配置兼容分派 | 必须自行设计 | 论文未涉及仓库迁移兼容 | `evolution.mode: eoh|roco`；字段缺省按 `eoh`，旧 smoke 行为作为回归契约，RoCo 使用独立配置 | 后续新增模式不得改变缺省含义或旧候选顺序 | ADR-0003；Stage 3 |
| G-025 | trace 到长期事件的边界 | 必须自行设计 | 论文没有日志 schema；Stage 3 trace 明确 generation-local | 纯转换器从 proposal/compare/integrate 派生事件；初始 Critic 不入长期 memory；当代事件提交前不可被历史检索 | P3a 已完成成功/失败 mapping、Critic 来源和 selected 回填测试；待正常推送 | ADR-0004；P3a 已完成 |
| G-026 | 角色摘要 multiplicity | 必须自行设计 | 论文说明 LTReflect 机制但未披露每代调用数 | 每代 E/X/I 各一次；Critic 反馈作为证据但不建独立长期摘要；失败沿用旧/空摘要 | P3b `576b1dd` 已实现并验证固定 E/X/I 次序、严格结构响应、旧/空回退和预算停止 | ADR-0004；P3b 已完成 |
| G-027 | 代级恢复 | 必须自行设计 | 论文未披露 crash consistency | population、账本、随机/provider 游标进入 JSON checkpoint；只从连续有效 commit 恢复，半写代忽略 | P3a 底座已发布；P4 实现提交 `c7a1ae4` 增加显式 engine resume、提交后中断、坏 hash/gap/config/seed fail-closed 及不中断/恢复规范工件哈希等价 | ADR-0004；Stage 4 V1 已完成 |
| G-029 | memory/no-memory 消融边界 | 必须自行设计 | 论文未给出可执行的离线消融记账与工件协议 | 同 seed、`T=2`、两代显式比较 memory off/on；off 不构造 runtime、不写 memory，on 保持既有路径；只报告控制流与预算差异 | P4 `c7a1ae4` 验证 off 为 32 calls/22 generated/22 valid、on 为 44/28/28；不作性能优劣结论 | Stage 4 V1 已完成 |
| G-028 | memory 候选去重/cache | 必须自行设计 | 论文没有预算口径；Stage 2/3 当前不去重 | Stage 4 V1 仍不去重、不缓存；相同代码照常生成和评估，可仅记录代码哈希 | 成本较高但保持账本连续；未来改变需新 ADR/cache-hit counter | ADR-0004；后续阶段 |
| G-030 | provider transport 与凭据边界 | 必须自行设计 | 论文未披露 SDK、endpoint、认证或客户端重试；真实副作用需单独授权 | `OpenAICompatibleTransport` 只通过构造注入；request 不含 endpoint/header/key，模块不读 env/`.env`/keyring，仓库无 HTTP 实现；默认/CLI 路径仍为 Mock | 真实 TLS、认证、客户端 retry 和供应商兼容性完全未验证 | ADR-0005；真实 transport 另行授权 |
| G-031 | provider 响应与错误分类 | 必须自行设计 | 论文未给 wire schema 或失败 taxonomy | 单 choice、非流式严格 JSON；envelope/choice/message/usage/角色输出拒绝未知/缺失/重复/non-finite；分类 timeout、retryable transport、auth/permission、rate limit、malformed JSON、schema 和 provider error | 供应商扩展字段必须通过新 contract 版本显式决定，不能静默放宽 | ADR-0005；fake transport 已覆盖 |
| G-032 | accepted attempt、usage 与价格结算 | 必须自行设计 | ADR-0001 把在途结算、真实价格留待 provider 阶段 | 发送前以 input + max output + 最大费用预检；accepted attempt 即计 call，合法 usage 按版本化 synthetic price table 结算；未知/非法 usage 不伪造 tokens/cost 并关闭 adapter 后续发送；接受后实际超支如实入账再停止 | synthetic 价格不是厂商价格；真实 model/币种/价格版本需另行核验 | ADR-0005；fake transport 已覆盖 |
| G-033 | 离线 adapter 与真实实验边界 | 必须自行设计 | 工程验证与论文性能证据不是同一层级 | P5 仅证明 EoH/RoCo adapter 在 fake transport 下的请求、响应、重试、预算、上下文和脱敏契约；Stage 4 memory provider、真实 API 和实验均未接入 | 不得把“adapter 已离线验证”写成“真实 provider 已验证”或“论文复现完成” | ADR-0005；真实互操作/Stage 5 实验后续 |
| G-034 | TSP-50/100/200 数据 inventory 与 train/test 划分 | 部分论文明确 + 必须自行设计 | `S009` 明确 TSP 实验并举例训练集为 5 个实例；表格出现 TSP-50/100/200；当前材料未唯一给出所有坐标分布、generator、seeds、test count 或逐实例清单 | ADR-0006 的 dry-run 使用版本化 unit-square 坐标规则、派生 seed、per-instance/manifest SHA-256 和 geometry checksum；默认每 split/size 一例明确为工程值 | 关闭证据：获授权的来源/release 与许可证、逐实例 inventory/checksum、split policy 和论文对应记录；此前不得称论文数据或用其数值作复现 | Stage 5；真实 TSP 实验前关闭 |
| G-035 | white-box/black-box prompt 内容与可见字段 | 论文语义明确，完整实现细节不足 | `S003` 说明两种设置；`S011` 指出 prompts 未完整可执行且 Critic 有歧义；本地材料不足以冻结逐字 prompt 和字段选择 | `roco-prompt-visibility-v1` 将其定义为信息可见性条件：black-box 不含坐标/矩阵/evaluator internals；Mock 只记录 metadata，不生成效果主张 | 关闭证据：版本化 prompt/allowed-fields contract、来源映射、模型/上下文和可见字段审计；不能将提示词 black-box 混同昂贵 oracle black-box | Stage 5；真实 provider 前关闭 |
| G-036 | P6 dry-run 实例数、seed、运行长度与公平上限 | 必须自行设计 | 论文给出部分全局参数，但 G-011/G-012/G-021 仍使完整 run budget/multiplicity 不可由本地材料唯一确定 | 固定 3 seed、每 split/size 1 instance、`N=4`、一代、`T=2` 和六类相同 hard ceilings；所有值写入 config/result | 关闭证据：论文/授权实验的重复数、seed、multiplicity、timeout scope 与六维预算的预注册；这些工程值不得描述为论文预算或方法公平结果 | Stage 5；真实实验设计前重定 |
| G-037 | 候选 COP 的来源与许可证 | 必须自行设计/部分关闭 | P7b-0 已获用户明确授权，仅从 John Burkardt/FSU `KNAPSACK_MULTIPLE` HTTPS 目录获取；来源说明页声明 GNU LGPL，许可链接核实为 LGPL v3；上游未给 release/version，只标注 2009-12-08 修订 | `mkp-fsu-knapsack-multiple-v1` 以来源 URL、获取日期、许可和逐文件 SHA-256 冻结本地 snapshot；见 `docs/data_provenance/mkp_fsu_knapsack_multiple_v1.md` | MKP 的来源/许可子项已关闭，但本地冻结 ID 不冒充上游 release；未来内容变化须新 provenance 版本。OP/BPP/CVRP/GLS 仍无获授权来源/许可，保持 E0 | MKP P7b-0 部分关闭；其他 COP 仍阻断 |
| G-038 | 候选 COP 的实例 inventory、checksum 与 split | 必须自行设计/MKP 子项关闭 | P7b-0 已验证 MKP P01–P06 的 18 个输入与 3 个可选 reference；P7b loader 再按原始字节 fail closed，并冻结六个 parser 后 instance checksum 与 dataset manifest checksum | `mkp-fsu-protocol-only-v1` 将 P01–P06 全部放入 `protocol-only` integration split；没有 train/validation/test、参数选择、训练或统计。原始文件仍只在 Git 忽略目录 | FSU MKP 的 inventory/checksum/parser semantic/split 子项已关闭；该设计有意不产生正式实验 split。其他 COP 的 inventory/checksum/split 全部未关闭 | MKP E3 已验证；其他 COP 仍阻断 |
| G-039 | 候选 COP 的目标、约束、evaluator 与指标 | 必须自行设计/MKP 子项关闭 | FSU 来源支持 01 Multiple Knapsack：maximize profit、每物品至多一个背包、容量硬约束；P7b 单元测试覆盖正常、非法索引、重复分配、超容量、格式/runtime/timeout | `mkp-fsu-evaluator-v1` 候选为每背包物品索引列表；计算 `raw_profit`，全局唯一 selection score 为 minimize `-raw_profit`；审计 normalized score 不参与选择；optional reference 不进入 prompt/打分且不声称最优 | FSU MKP 离线 evaluator 子项已关闭。reference gap/最优值未建立，因此不能计算 optimality gap；OP/BPP/CVRP/GLS evaluator 仍开放 | MKP E3 已验证；其他 COP/真实实验仍阻断 |
| G-040 | 跨 COP 公平预算、随机性、provider 与 visibility | 必须自行设计/MKP Mock 子项关闭 | G-009/G-012/G-018/G-021/G-035 不能唯一给出跨问题原值；P7b 因此新增独立 `mkp-fsu-mock-engineering-v1`，不继承 P6/论文 | 每条 MKP Mock run 同享 20 calls、50000 tokens、16 candidates、16 valid evals、USD 0.25、60 s；root seed 707 标签派生；provider=`mock`/network=`unused`；唯一 `full_instance` contract 排除 reference/optimum 并记录 allowed-fields/prompt hash | 12 条 EoH/RoCo run 的完整实际 ledger 与 replay 已验证，故只关闭此 MKP Mock profile 子项。真实 provider、E4 seed/repetition、其他 COP 与任何跨 COP 比较仍开放 | MKP E3 Mock 子项关闭；E4/其他 COP 仍阻断 |
| G-041 | 多 COP 统计、失败处理与结论边界 | 必须自行设计 | 当前没有任何非 TSP 真实实验；P6 只有 3-seed metadata-only Mock dry-run | P7a 规定每个可比较 cell 最少 10 个匹配 seed、描述统计、10,000 次 paired bootstrap 95% interval 和 fail-closed 失败报告 | 关闭证据：运行前固定的分析计划、全部 planned/completed/failed run 工件、匹配 seed 表、bootstrap 输入/脚本与偏离记录；不得由缺失/失败 run 推导优越性 | E4 真实实验前关闭 |
| G-042 | EBBO ledger、canonical JSON、稳定 ID 与旧账本兼容 | 必须自行设计/P9a 已关闭 | P9a 新建独立 `roco_ebbo.ebbo` ledger/contracts/store；不导入、不修改 Stage 2--5 `BudgetLedger` | `ebbo-ledger-v1`、`roco-ebbo-canonical-json-v1`、domain-separated full SHA-256 ID、63-bit label seed、非时间 replay checksum；accepted attempt 立即永久计 call | strict JSON/duplicate/nonfinite、ID/seed、budget/cancel/duplicate/failure/timeout/invalid/overrun/unknown、store reopen/replay 和旧 smoke 回归 | P9a 已关闭；未来 schema bridge 需新 gap |
| G-043 | EBBO surrogate 与共享 posterior | 必须自行设计/P9a 子项关闭 | 论文无 GP/神经 surrogate 证据；P9a 不新增第三方依赖 | `ebbo-nearest-observation-surrogate-v1` 只读成功 Observation；最近目标为 mean、归一化距离为 uncertainty、cold prior 可配置，无拟合或隐藏 fallback | P9a 单元/双运行 replay 已验证；P9b 四角色同一已提交 observation/pool view 与稳定 posterior-view ID 已验证；它不是概率 posterior、校准方法或论文事实 | P9a 工程与 P9b 共享读取子项关闭；P10 模型选择仍开放 |
| G-044 | acquisition、候选池生成与 tie-break | 必须自行设计/Mock 子项关闭 | EI/UCB/TS 未由论文或仓库决定 | P9a deterministic LCB/finite pool；P9b 池内只选 ID；P9c 对 pending/已接受候选 exclusion，不做 fantasy | 工程 Mock 的 score/ID tie-break、pending exclusion 和恢复 replay 已测试；acquisition 比较尚无实验 | P9a/P9b/P9c Mock 子项关闭；P10 acquisition 比较开放 |
| G-045 | EBBO benchmark、搜索域、reference 与真实 oracle 来源 | 必须自行设计/P9a Mock 子项关闭 | TSP/MKP evaluator 不是昂贵黑盒 benchmark；P9a 无数据下载或外部来源 | 工程 fixture `x in [-5,5]`、`f(x)=(x-2)^2+1`、`ebbo-mock-expensive-oracle-v1`；不声称 benchmark/reference | 只证明控制流、审计、失败和 replay；P10 仍需用户授权 source/license/version/reference/provider/oracle/预算 | P9a Mock 子项关闭；P10 real 开放 |
| G-046 | 噪声、replicate 与 Observation 聚合 | 必须自行设计/P9a 子项关闭 | 论文/仓库未定义真实 EBBO noise 或 replicate | P9a 固定 `noise.kind=none`、`replicate_index=0`，duplicate dispatch 默认拒绝；每次真实接受仍逐 attempt 计费 | Mock no-noise/no-replicate 已测试；真实 noise/heteroscedasticity/聚合/latent regret 未定 | P9a 子项关闭；P10 真实部分开放 |
| G-047 | 可选约束、不可行点与失败观测建模 | 必须自行设计/Mock 事实子项关闭 | Mock 明确 `none-v1` | P9c 失败、timeout、取消后 Observation objective/constraints/feasible 均 null；只有成功事实进入 surrogate，失败候选排除重发 | 负路径/恢复测试已验证不伪造 penalty；constraint surrogate、真实 failure-aware 模型未实现 | P9a/P9c Mock 事实子项关闭；P10 开放 |
| G-048 | 异步 reservation、pending、乱序完成、取消与恢复 | 必须自行设计/P9c Mock 子项关闭 | P9a/P9b 串行不变；P9c 单进程 `max_concurrency=2` fake completion | scheduler-only dispatch；reserved+accepted hold、稳定回调排序、取消确认、late audit、显式 checkpoint/resume 与 strict fail-closed | 中断/不中断状态/事件/checksum 等价；损坏/缺失/不匹配 checkpoint 拒绝；真实远端顺序/对账与任意点 crash 未实现 | P9c Mock 子项关闭；真实异步开放 |
| G-049 | evaluation cost 模型与成本感知调度 | 必须自行设计/Mock 准入子项关闭 | EBBO cost 不能与 provider USD 合并 | P9c 在 P9a fixed Mock cost 上增加 outstanding expected hold；实际超额照实入账、停止新准入并排空 pending；unknown fail-closed | 预算边界/overrun/unknown 测试已验证；cost-aware acquisition、换算、多资源和真实公平 profile 未定 | P9a/P9c Mock accounting 关闭；P10 真实成本开放 |
| G-050 | EBBO 指标、target、重复数与统计结论 | 必须自行设计 | 当前仅有工程 Mock smoke、没有 EBBO benchmark/E4 工件；reference optimum、cumulative regret 的噪声/失败处理、target 和 repetitions 均未知 | 未来报告 simple regret、条件明确时的 cumulative regret、cost-to-target、失败率和时间；跨 benchmark 不聚合 raw score；沿用 E4 结论闸门 | P10 前冻结 reference/target、seed set、重复数、失败/censoring、interval/多重比较和偏离记录；没有 E4 不作性能/显著性/泛化/优越性结论 | P10 前关闭；当前开放 |
| G-051 | EBBO 角色输出、权限与可选 memory | 必须自行设计 | Stage 3 角色生成/融合启发式代码，Stage 4 memory 绑定旧 trace/mutation；均不能直接作为 EBBO 调度协议 | P9b 角色固定为 global explorer/local exploiter/model critic/resource integrator；Integrator 只选有限 pool，scheduler 唯一 dispatch；默认无 EBBO memory | P9b strict role request/response/audit schema、越权/未知 ID/重复/非有限拒绝、advisory/hard veto、provider error/timeout/预算耗尽降级与四路径重放已验证；未来 memory 仍须另定 Observation 来源、检索、预算、隐私与 no-memory 对照 | P9b 角色权限/降级/工程消融子项关闭；真实 LLM 与 memory 接入仍开放 |

## 当前阻断项

Stage 6 P8 设计由 `6efec47` 发布；P9a 由 `4189f65970feab0a17299445641916c6245de4a8`
发布；P9b `fa3b464` 是已发布 P9c 提交的祖先，P9c 已由
`b698649cdf360d56eb063fc257a0e6614a53b733` 发布。P9c Mock 完整离线验收通过：
221 passed/1 skipped，Ruff check/format、
mypy、doctor、六条 Stage 2/3/4/P9a/P9b/P9c smoke 和 `git diff --check` 均通过。
G-042 与 G-052 Mock 子项关闭；G-043/G-044/G-047--G-049 仅关闭具体工程 Mock 子项。
真实异步 reconciliation、真实成本/约束/噪声、G-050 统计、G-051
memory/真实 LLM 均开放。P10 只有在用户明确授权 benchmark、来源、许可证、真实
provider/oracle 和预算后才可关闭真实实验与统计子项。待决字段和 E2/E3/E4 闸门见
`docs/paper_spec/p10_experiment_preregistration_template.md`；模板不关闭 gap，也不授权实验。
P9a/P9b/P9c Mock 不构成 E4 或性能证据。

Stage 3 的离线工程路径没有未解决的实现阻断项。ADR-0002 继续固定旧 EoH smoke；
ADR-0003 固定四角色状态机、失败降级、配置分派和单代 trace。G-002–G-004 与
G-020 中未能从论文唯一确定的部分已作为显式工程口径版本化，而不是冒充作者原值。

进入论文数值复现或真实 provider 前，仍须回到原 PDF 逐式核验精英邻居采样、
Integrator 位置、Critic 原 prompt 和训练 timeout。P2 已完成：Stage 4 的 schema、检索、
摘要、mutation 与恢复协议已经由 `cf1e06b`/ADR-0004 设计冻结并发布。P3a 事实层与恢复
底座由 `a0b24b1` 发布，P3b 运行时由 `576b1dd` 发布；远端同步状态仍须实时核验。当前
P4 由 `c7a1ae4` 实现并包含在 Stage 4 发布基线 `59c3357` 中，已验证 engine 级提交后
中断恢复、不中断/恢复端到端规范哈希等价及 memory/no-memory 消融。Stage 4 冻结 V1 的
离线 Mock 实现已完成。P5 的 OpenAI-compatible EoH/RoCo adapter 已由
`38428700d8f272f8107e8cd042f5fdec24d3e33d` 按 ADR-0005 使用 injected fake transport
离线验证；仓库没有 HTTP transport，不读取真实凭据、不发起网络，Mock 仍为默认。这不包含
真实 API、Stage 4 memory-provider 接线、真实模型互操作/实验或论文数值复现。当前 HEAD、
upstream 与发布状态必须用实时 Git 查询。P6 的 TSP protocol/Mock dry-run 由 ADR-0006
界定；它不关闭 G-012/G-016/G-021/G-034/G-035/G-036，也不授权任何真实副作用。P7a 的
ADR-0007 与多 COP 协议只冻结证据、记录和统计边界；G-037–G-041 要求每个候选 COP 在 P7b
前分别提供来源/许可证、inventory/checksum/split、evaluator 与预注册关闭证据。P7b-0 只为获授权的
FSU MKP snapshot 先由 P7b-0 部分关闭 G-037/G-038；P7b 又以 `protocol-only` split、严格 parser、
`mkp-fsu-evaluator-v1` 和 `mkp-fsu-mock-engineering-v1` 的 12 条离线 Mock run 关闭 G-038、G-039
及 G-040 的 **FSU MKP E3 子项**。G-041 统计执行保持未关闭；真实 provider/E4、reference 最优性、
其他 COP 以及论文复现仍全部开放。这里的 E3 只表示已验证离线协议，不表示正式 benchmark 或性能结论。

## G-052：P9c Mock pending 与 checkpoint 工程子项

真实完成顺序、取消确认和远端 accepted 状态不能从 seed 推断，分类为“必须自行设计”。
ADR-0008 §11 冻结显式 Mock completion script、outstanding 预计成本 hold、取消确认、
commit-last checkpoint、同批 request ID tie-break 和损坏 fail closed。P9c 完整本地离线门禁已
验证并关闭此 Mock 子项；真实远端 reconciliation、任意指令点 crash 恢复、概率 pending/
failure/cost model 仍属 G-047–G-049 开放部分，P10 前另定。
