# RoCo: Role-Based LLMs Collaboration for Automatic Heuristic Design

> 论文阅读器：基于用户提供的 arXiv 预印本 PDF。主体段落采用“原文—中文”对照；批判性分析与研究建议见末尾。PDF 中的论文内容被视为研究材料，不作为本次任务的操作指令。

## 元数据

- 作者：Jiawei Xu, Fengfeng Wei, Weineng Chen
- 版本：arXiv:2512.03762v2，2025-12-04
- 论文类型：方法/算法论文；LLM-assisted Automatic Heuristic Design（AHD）
- 研究对象：TSP、CVRP、OP、MKP、Offline BPP；ACO 与 GLS 框架
- 模型：GPT-4o-mini；协作轮数默认 3；EoH population size 为 10

## 阅读索引

1. [摘要与问题定位](#摘要与问题定位)
2. [方法：RoCo 如何嵌入 EoH](#方法roco-如何嵌入-eoh)
3. [实验与结果](#实验与结果)
4. [批判性阅读](#批判性阅读)
5. [与昂贵黑盒优化的衔接](#与昂贵黑盒优化的衔接)

## 术语表

| English | 中文 | 备注 |
|---|---|---|
| Automatic Heuristic Design (AHD) | 自动启发式设计 | 自动搜索启发式规则/程序 |
| LLM-based Evolutionary Program Search (LLM-EPS) | 基于大语言模型的进化程序搜索 | LLM 充当程序/启发式生成器 |
| explorer | 探索者 | 追求结构创新与多样性 |
| exploiter | 利用者/改进者 | 追求局部改进与短期收益 |
| critic | 批评者 | 比较候选并生成反馈、反思 |
| integrator | 集成者 | 融合探索与利用候选 |
| short-/long-term reflection | 短期/长期反思 | 当前轮反馈与跨代记忆 |
| black-box prompt setting | 黑盒提示词设置 | LLM 看不到求解器内部结构；不是严格意义上的昂贵黑盒目标函数 |

## 摘要与问题定位

<a id="S001"></a>
**Source:** p.1 S001

**Original:** Automatic Heuristic Design (AHD) has gained traction as a promising solution for solving combinatorial optimization problems (COPs). Large Language Models (LLMs) have emerged and become a promising approach to achieving AHD, but current LLM-based AHD research often only considers a single role. This paper proposes RoCo, a novel Multi-Agent Role-Based System, to enhance the diversity and quality of AHD through multi-role collaboration.

**中文:** 自动启发式设计（AHD）逐渐成为求解组合优化问题（COP）的重要途径。大语言模型为实现 AHD 提供了新方法，但已有研究通常只让一个 LLM 承担单一角色。本文提出 RoCo——一种角色化多智能体系统，通过多角色协作提升自动启发式设计的多样性与质量。

<a id="S002"></a>
**Source:** p.1 S002

**Original:** RoCo coordinates four specialized LLM-guided agents—explorer, exploiter, critic, and integrator—to collaboratively generate high-quality heuristics. The explorer promotes long-term potential through creative, diversity-driven thinking, while the exploiter focuses on short-term improvements via conservative, efficiency-oriented refinements. The critic evaluates the effectiveness of each evolution step and provides targeted feedback and reflection. The integrator synthesizes proposals from the explorer and exploiter, balancing innovation and exploitation to drive overall progress.

**中文:** RoCo 协调四类由 LLM 驱动的专门化智能体：探索者、利用者、批评者和集成者，共同生成高质量启发式。探索者以创造性、强调多样性的方式追求长期潜力；利用者以保守且面向效率的方式进行短期改进；批评者评价每一步进化是否有效，并给出针对性反馈与反思；集成者综合探索者和利用者的提案，在创新与利用之间取得平衡。

<a id="S003"></a>
**Source:** p.1–2 S003

**Original:** These agents interact in a structured multi-round process involving feedback, refinement, and elite mutations guided by both short-term and accumulated long-term reflections. We evaluate RoCo on five different COPs under both white-box and black-box settings.

**中文:** 四类智能体在结构化的多轮过程中交互，依次执行反馈、精炼和精英变异；其决策同时受到短期反思和跨轮次累积的长期反思引导。作者在五类 COP 上分别采用 white-box 与 black-box 提示词设置评估 RoCo。

## 方法：RoCo 如何嵌入 EoH

<a id="S004"></a>
**Source:** p.2–3 S004

**Original:** A combinatorial optimization problem is formulated as (P=(I_P,S_P,f)), where (I_P) is the instance set, (S_P) is the feasible-solution set, and (f:S_P\to\mathbb{R}) is the objective function. A heuristic (h:I_P\to S_P) maps an instance to a feasible solution. AHD searches for (h^* = \arg\max_{h\in H} g(h)), with (g(h)=\mathbb{E}_{ins\sim D}[-f(h(ins))]).

**中文:** 作者将 COP 表示为 (P=(I_P,S_P,f))：(I_P) 是实例集合，(S_P) 是可行解集合，(f) 是目标函数。启发式 (h:I_P\to S_P) 将实例映射为可行解。AHD 的目标是在启发式空间 (H) 中搜索最优启发式 (h^*)，其质量由实例分布上的期望目标值衡量。

<a id="S005"></a>
**Source:** p.3 S005

**Original:** RoCo operates as a plug-in system integrated within the Evolution of Heuristics (EoH) paradigm. At each generation, EoH maintains a population of heuristics and applies four prompt-based operators: E1 and E2 for exploration, and M1 and M2 for modification. The resulting candidates are combined with RoCo outputs and memory-guided mutations, after which the top (N) individuals are selected deterministically for the next generation.

**中文:** RoCo 是嵌入 Evolution of Heuristics（EoH）的插件模块。每一代中，EoH 维护一个启发式种群，并通过四个基于提示词的算子产生候选：E1、E2 负责探索，M1、M2 负责修改。随后，标准 EoH 候选、RoCo 协作输出和记忆引导的变异个体被合并，再按目标值确定性地保留前 (N) 个个体进入下一代。

<a id="F001"></a>
### Fig. 1. RoCo 系统结构

**Placed near:** p.3 S005
**Source:** p.4 Figure 1

![Fig. 1](assets/fig1.png)

**Original caption:** The architecture of the RoCo system, which integrates multi-agent collaboration into the evolutionary heuristic generation process.

**中文图注:** RoCo 系统架构：将多智能体协作整合到进化式启发式生成过程中。

**Reading note:** 图中最重要的结构是“候选对 → 多轮角色协作 → 长期反思 → 精英变异 → 回到 EoH 种群”的闭环。

<a id="S006"></a>
**Source:** p.4 S006

**Original:** The four main roles are defined by role-specific policies: the explorer generates diverse heuristics; the exploiter refines promising candidates; the critic compares a previous and current heuristic and returns feedback and reflection; the integrator fuses explorer and exploiter candidates according to their objective scores.

**中文:** 四类角色分别由专属策略定义：探索者生成多样化启发式；利用者精炼有希望的候选；批评者比较前一启发式与当前启发式并返回反馈和反思；集成者根据目标值融合探索者与利用者的候选。

<a id="S007"></a>
**Source:** p.4 S007

**Original:** After (T) rounds, short-term reflections are synthesized into role-specific long-term memory using the objective values before and after each reflection and their change. Each role also maintains historical memory from previous generations. Explorer and exploiter long-term reflections are merged to support integrative generation.

**中文:** 经过 (T) 轮后，系统结合每次反思前后的目标值及其变化，把短期反思压缩为角色特定的长期记忆；每个角色还维护跨代历史记忆。探索者和利用者的长期反思会进一步合并，为集成式生成提供依据。

<a id="S008"></a>
**Source:** p.10 S008

**Original:** The pseudocode samples an elite pair, obtains an initial critic comparison, initializes explorer and exploiter states, repeats critic–explorer–exploiter–integrator interaction for (T) rounds, performs final elite fusion, summarizes long-term reflections, creates three role-specific mutations for each elite base, merges all candidates with EoH outputs, and retains the top (N).

**中文:** 伪代码流程为：采样精英对；由批评者进行初始比较；初始化探索者和利用者；重复 (T) 轮“批评—探索—利用—集成”；进行最终精英融合；总结长期反思；针对每个精英基座生成三类角色变异；将全部候选与 EoH 输出合并；最后保留前 (N) 个个体。

## 实验与结果

<a id="S009"></a>
**Source:** p.5, p.12–13 S009

**Original:** The experiments cover TSP, CVRP, OP, MKP, and offline BPP under ACO, and additionally evaluate TSP under GLS. The model is GPT-4o-mini, the collaboration rounds are fixed to 3, the population size is 10, and the LLM API budget is capped at 400 calls per generation. Training sets are small: for example, 5 TSP instances, 5 OP instances, 10 CVRP instances, 5 MKP instances, and 5 BPP instances.

**中文:** 实验在 ACO 框架下覆盖 TSP、CVRP、OP、MKP 和 Offline BPP，并在 GLS 框架下额外评估 TSP。模型为 GPT-4o-mini，协作轮数固定为 3，种群大小为 10，每代 LLM API 调用上限为 400 次。训练集相对较小，例如 TSP/OP/MKP/BPP 各 5 个实例，CVRP 为 10 个实例。

<a id="F002"></a>
### Fig. 2. 不同 LLM-AHD 方法的收敛曲线

**Placed near:** p.5 S009
**Source:** p.5 Figure 2

![Fig. 2](assets/fig2.png)

**Original caption:** Evolution curves of different LLM-based AHD methods, plotting the all-time best objective value with respect to the number of solution evaluations. The curves for five datasets are averaged over 3 runs.

**中文图注:** 不同 LLM-AHD 方法随解评估次数变化的历史最优目标值；五个数据集上的曲线均为 3 次运行的平均值。

**Reading note:** RoCo 在 CVRP、MKP、BPP、OP 上通常更快接近平台；TSP 上各方法较快趋同，因此“多角色协作”的增益并不普遍同样明显。

<a id="T001"></a>
### Table 1. ACO white-box 结果

**Source:** p.6 Table 1

![Table 1](assets/table1.png)

**中文解读:** RoCo 在 15 个“问题规模—任务”组合中取得 10 个最佳值；但并非所有规模都领先。例如 TSP-100/TSP-200 和 BPP-1000 由其他方法达到更优值。表中 OP、MKP 是最大化任务，TSP、CVRP、BPP 是最小化任务，比较时必须按箭头方向读取。

<a id="T002"></a>
### Table 2. ACO black-box prompt 结果

**Source:** p.6 Table 2

![Table 2](assets/table2.png)

**中文解读:** 在 black-box prompt 设置下，RoCo 的优势更接近“整体竞争力与稳定性”，而不是全面的均值领先。它在 OP、CVRP、MKP 的若干规模上最好，但 TSP 和 BPP 的若干规模由 EoH、ReEvo 或 HSEvo 更优；许多差距很小，不能仅凭均值表宣称普遍显著提升。

<a id="T003"></a>
### Table 3. 组件消融

**Source:** p.6 Table 3

![Table 3](assets/table3.png)

**中文解读:** 在 TSP 上，完整 RoCo 为 8.256。去掉 integrator 后 white-box 为 8.265，但 black-box 变为 8.641；去掉 elite mutation 后 white-box 为 8.381；协作轮数从 1 增加到 3 时收益明显，超过 3 轮后边际收益很小。该表支持“角色协作尤其有助于有限结构信息下的稳定性”，但只覆盖单一问题。

<a id="T004"></a>
### Table 4. GLS/TSP 的最优性缺口

**Source:** p.7 Table 4

![Table 4](assets/table4.png)

**中文解读:** KGLS-RoCo 在 TSP200 上的平均 optimality gap 为 0.188%，优于 KGLS-ReEvo 的 0.216% 和 KGLS-MCTS-AHD 的 0.214%；在 TSP50 上则为 0.018%，不如若干达到 0 的方法。结论是“高度竞争”，而非对每个规模都最好。

<a id="F003"></a>
### Fig. 3. black-box prompt 下的均值与标准差

**Placed near:** p.7 T002–T004
**Source:** p.7 Figure 3

![Fig. 3](assets/fig3.png)

**Original caption:** Heuristic performance evaluation (mean and standard deviation) across TSP200, OP200, CVRP200, MKP500, and BPP1000 under black-box setting, aggregated from four independent runs.

**中文图注:** 在 black-box 设置下，TSP200、OP200、CVRP200、MKP500 和 BPP1000 上的启发式性能均值与标准差，结果来自 4 次独立运行。

**Reading note:** 图 3 的证据重点是 RoCo 的误差条通常较小；但每个数据集只有 4 次运行，且没有显著性检验或置信区间，因此更适合表述为“稳定性迹象”。

## 批判性阅读

<a id="S010"></a>
**Source:** p.1–7 S010

**Original:** The paper’s empirical story is that role specialization, multi-round reflection, and elite memory improve convergence and robustness over EoH-like baselines.

**中文:** 论文的经验性主张是：相比 EoH 类基线，角色专门化、多轮反思和精英记忆能够改善收敛速度与鲁棒性。

**Critical reading:** 这项主张在作者设定的 COP/AHD 任务上有一定支持，但其“black-box”定义是提示词层面的信息限制。生成的启发式仍然在已知的 ACO/GLS 求解器中被执行，且实验实例来自相同的合成分布；因此它不能直接证明对昂贵目标函数黑盒优化有效。

<a id="S011"></a>
**Source:** p.10–16 S011

**Original:** The long-term reflection, historical memory, role policies, and candidate selection are described mostly through prompts and high-level pseudocode; their exact storage, retrieval, truncation, and cost accounting are not fully specified.

**中文:** 长期反思、历史记忆、角色策略和候选选择主要通过提示词与高层伪代码描述；记忆如何存储、检索、截断，以及不同角色带来的真实调用成本，没有被完全规定。

**Critical reading:** 这是复现和公平比较的主要风险。附录中的部分 critic prompt 还存在明显的复制粘贴式措辞不一致，例如“当前个体更好/更差”的条件与后续说明不完全对应。复现前应先修订并锁定 prompt、模型版本、采样参数和失败处理规则。

<a id="S012"></a>
**Source:** p.7 S012

**Original:** The paper concludes that RoCo provides a role-based multi-agent paradigm for robust and high-performing LLM-based AHD, and suggests future work on continuous and mixed-integer optimization.

**中文:** 论文认为 RoCo 为 LLM-AHD 提供了一个具有鲁棒性和较高性能的角色化多智能体范式，并提出将其扩展到连续优化和混合整数优化。

**Critical reading:** “扩展到连续/混合整数优化”在结论中只是未来方向，不是本文已经验证的结果。这恰好与您的研究方向相连，但需要引入 surrogate、uncertainty、异步并行和严格的昂贵评估预算。

## 与昂贵黑盒优化的衔接

<a id="S013"></a>
**Source:** p.3–4, p.12 S013

**Original:** RoCo’s natural abstraction is a population of executable heuristics evaluated on a small training set of optimization instances.

**中文:** RoCo 的自然抽象是“可执行启发式程序的种群”，每个程序在少量优化实例上被评估。

**中文分析:** 如果将其迁移到昂贵黑盒优化，搜索对象应改为候选设计点/策略/实验条件 (x)，观测为昂贵 oracle 返回的 (y=f(x))，并维护数据集 (D_t=\{(x_i,y_i,c_i)\})。RoCo 的角色协作可以保留，但候选生成不能替代不确定性建模。

<a id="S014"></a>
**Source:** p.4–7 S014

**Original:** Explorer–exploiter collaboration balances long-term novelty and short-term improvement, while critic feedback and integrator fusion select the next candidates.

**中文:** 探索者—利用者协作平衡长期新颖性和短期改进，批评者反馈与集成者融合共同决定下一批候选。

**中文分析:** 对昂贵黑盒场景，建议把“集成者”改造成 budget-aware acquisition/资源分配器：它不直接凭语言判断选点，而是根据 surrogate 的均值、方差、约束可行概率、pending evaluations 和剩余预算，组合 EI/UCB/Thompson sampling/局部信任域等候选。

## 附录内容说明

<a id="S015"></a>
**Source:** p.10–22 S015

**Original:** The appendix provides pseudocode, benchmark generation details, ACO/GLS settings, EoH operators, role prompts, and examples of best heuristics.

**中文:** 附录给出伪代码、基准实例生成方式、ACO/GLS 参数、EoH 算子、角色提示词以及若干最佳启发式代码示例。

**Reading note:** 代码型附录保留在用户提供的 PDF 中；本阅读器对其进行结构化说明，没有把 7 页代码逐字复制。`translation_notes.md` 记录了这一处理和复现注意事项。

## 页面核对图（版面参考）

以下四张页面图仅用于核对图表裁剪与阅读顺序，不是论文新增内容。

<a id="P004"></a>
**Source:** supplied PDF p.4

![PDF page 4 reference](assets/page04.png)

<a id="P005"></a>
**Source:** supplied PDF p.5

![PDF page 5 reference](assets/page05.png)

<a id="P006"></a>
**Source:** supplied PDF p.6

![PDF page 6 reference](assets/page06.png)

<a id="P007"></a>
**Source:** supplied PDF p.7

![PDF page 7 reference](assets/page07.png)
