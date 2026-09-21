# FSU KNAPSACK_MULTIPLE 数据来源冻结 v1

## 状态与范围

- 本地冻结标识：`mkp-fsu-knapsack-multiple-v1`
- 数据集精确名称：`KNAPSACK_MULTIPLE - Data for the 01 Multiple Knapsack Problem`
- 作者/维护者：John Burkardt
- 来源站点：Florida State University John Burkardt dataset pages
- 来源目录：<https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/>
- 数据集说明页：<https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/knapsack_multiple.html>
- 获取日期：2026-09-21（Asia/Shanghai）
- 上游版本：页面未提供 release/version 标识；说明页标注 `Last revised on 08 December 2009`
- 许可证：GNU Lesser General Public License v3.0（2007-06-29）
- 许可证链接：<https://people.sc.fsu.edu/~jburkardt/txt/gnu_lgpl.txt>
- 本地原始数据目录：`data/raw/mkp/fsu-knapsack-multiple/`

本任务只冻结用户明确授权的上述来源。`mkp-fsu-knapsack-multiple-v1` 是以来源 URL、获取日期和下列
逐文件 SHA-256 锚定的本地 provenance 版本，不冒充上游发布号。没有访问镜像、GitHub 或其他数据源。

原始数据目录受仓库 `.gitignore` 的 `data/raw/` 规则保护。仓库只提交本 provenance/checksum 文档，
不提交输入文件、参考解、下载缓存或运行产物。

## 问题契约

来源说明将该数据集定义为 **01 Multiple Knapsack**：给定多个容量为 `C(1:M)` 的背包，以及具有
重量 `W(1:N)` 和收益 `P(1:N)` 的物品。决策是 0/1 分配；每件物品至多分配给一个背包，每个背包
内物品总重量不得超过其容量，目标是**最大化所选物品的总收益**。

P7b 在不改变来源语义的前提下另行冻结下述可执行契约；来源问题仍是 maximize，系统统一选择分数
仍严格 minimize。可选 reference 不参与 prompt、选择分数或“最优值”声明。

## P7b parser、split 与 evaluator 契约

- benchmark/protocol：`mkp-fsu-protocol-v1`；数据来源版本仍是
  `mkp-fsu-knapsack-multiple-v1`。
- loader 必须显式接收 data root，不读取环境变量、隐式仓库路径或网络。它只接受本页 inventory；
  未知文件、symlink、缺少必需输入、空文件、原始字节数/SHA-256 不符、非整数/超出 signed 64-bit
  token、weight/profit 长度不一致、负 capacity/weight 均 fail closed，并返回结构化安全错误。
- P01--P06 全部属于 `mkp-fsu-protocol-only-v1` 的 `protocol-only` integration split。该协议没有
  train、validation 或 test，不允许参数选择、模型选择、训练、正式统计或把六个小实例伪装成实验集。
- 候选签名为 `heuristic(capacities, weights, profits) -> list[list[int]]`：外层每项对应一个背包，
  未出现的物品表示不选择；物品索引越界、同一物品重复出现或任一背包超容量均无效。
- `mkp-fsu-evaluator-v1` 在受限 spawned subprocess 中执行可信本地/Mock 代码，并施加 per-candidate
  工程 timeout。它计算 `raw_profit`，唯一 Top-N selection score 为 `score=-raw_profit`，因此不改变
  全局 minimize 语义。审计字段 `normalized_score=score/max(1, sum(max(0, profit)))` 不参与选择，
  也不是相对 reference/最优值的 gap。
- P01/P05/P06 的 reference 仅检查冻结字节、数值形状、0/1 和“物品至多一次”结构；不执行、
  不进入 prompt、不用于打分，且没有重新证明为最优解。

parser 后的协议实例 checksum 对 protocol version、instance ID、`protocol-only` split、解析后的
capacity/weight/profit 和三个输入文件的 byte/checksum 记录计算 canonical JSON SHA-256：

| 实例 | 背包/物品 | `mkp-fsu-protocol-v1` instance checksum |
|---|---:|---|
| P01 | 2 / 10 | `994f106ed9f23e733f9b700c65d1933587d88f87643293e298677f9dbe17b89f` |
| P02 | 3 / 10 | `6894edca1ad4da8efe66839c47a69d592d5c4e608a8c059ab634a79416c383a1` |
| P03 | 4 / 10 | `177762f02a136d6a8a867f1b2a83a05ac76b1c8a25317de3c4f80b52631d3e56` |
| P04 | 1 / 10 | `15ef9891ba57c025661aa7b1ba8c4cab2856b4a50fff304279c73dcf45a54d1e` |
| P05 | 2 / 6 | `9a04daacc8a8353ff7479d43c7964da2230560f820a39f3d796fcc24f7165aa3` |
| P06 | 2 / 10 | `eb916f4cf6ecfc02608dea943ed01ab50fcc53ce71bff7f8f44de456d050d365` |

包含 21 个文件 present 状态、上述六个实例、来源/许可和 split policy 的 dataset manifest checksum
为 `076c848d9e93b8d644195e4bbf7bc6da4fcd9de9594528ff59109bdd83a874ce`。它与逐文件原始字节
SHA-256 是不同层级的 checksum，二者都必须验证。

## 实例概览

| 实例 | 来源页描述的规模 | 必需输入 | 可选 reference |
|---|---|---|---|
| P01 | 10 个物品，2 个背包 | `p01_c.txt`、`p01_w.txt`、`p01_p.txt` | `p01_s.txt` |
| P02 | 10 个物品，3 个背包 | `p02_c.txt`、`p02_w.txt`、`p02_p.txt` | 无；来源页标为 not available |
| P03 | 10 个物品，4 个背包 | `p03_c.txt`、`p03_w.txt`、`p03_p.txt` | 无；来源页标为 not available |
| P04 | 10 个物品，1 个背包 | `p04_c.txt`、`p04_w.txt`、`p04_p.txt` | 无；来源页标为 not available |
| P05 | 6 个物品，2 个背包 | `p05_c.txt`、`p05_w.txt`、`p05_p.txt` | `p05_s.txt` |
| P06 | 10 个物品，2 个背包 | `p06_c.txt`、`p06_w.txt`、`p06_p.txt` | `p06_s.txt` |

P01/P05/P06 的 `*_s.txt` 是来源提供的可选 reference 文件，不是 parser/evaluator 输入，也没有在
P7b-0 中重新证明其最优性或提取最优值。P02/P03/P04 没有 reference 文件不是下载失败；本任务按授权
没有尝试不存在的 `p02_s.txt`、`p03_s.txt` 或 `p04_s.txt`。

## 冻结文件 inventory

下载使用 HTTPS 和失败即停止语义。SHA-256 对下载后的原始字节直接计算，没有换行、空白或数值规范化。
21 个实际文件均非空，经本地检查为 `text/plain`，且所有非空白 token 均为数值。

| 文件 | 角色 | 字节数 | SHA-256 | 完整 URL |
|---|---|---:|---|---|
| `p01_c.txt` | input/capacity | 8 | `d6c953e90bd72846a1505608d59e96e6fb8406e4dd6250e6368bbfa8aef83aaa` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p01_c.txt> |
| `p01_w.txt` | input/weight | 30 | `5eb586c0c659c6d746e6eda5da0795812afc4c63791259a7c2a274fef6af5e60` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p01_w.txt> |
| `p01_p.txt` | input/profit | 29 | `d9f102a31d73849425c2ce4a970a82f7b4b591f497980578dc4b1da3d1f110c8` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p01_p.txt> |
| `p01_s.txt` | optional reference | 40 | `e65b1c47da5ca36f650c5a804d089d7187ed4665369fb24fb26477af885990c7` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p01_s.txt> |
| `p02_c.txt` | input/capacity | 12 | `fd7f9550a013dc6b35c3ed6d9a87102965b5b3794953589f68f36fd564b1f9ab` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p02_c.txt> |
| `p02_w.txt` | input/weight | 30 | `5eb586c0c659c6d746e6eda5da0795812afc4c63791259a7c2a274fef6af5e60` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p02_w.txt> |
| `p02_p.txt` | input/profit | 29 | `d9f102a31d73849425c2ce4a970a82f7b4b591f497980578dc4b1da3d1f110c8` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p02_p.txt> |
| `p03_c.txt` | input/capacity | 13 | `0f1114f6530d66a2785aba56885195818c8c5ee1998fac30a524a464dafa8a3c` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p03_c.txt> |
| `p03_w.txt` | input/weight | 30 | `5eb586c0c659c6d746e6eda5da0795812afc4c63791259a7c2a274fef6af5e60` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p03_w.txt> |
| `p03_p.txt` | input/profit | 29 | `d9f102a31d73849425c2ce4a970a82f7b4b591f497980578dc4b1da3d1f110c8` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p03_p.txt> |
| `p04_c.txt` | input/capacity | 4 | `167918ace289465acd4dd6ab6587fe10bfe54bc475ad8074b049ac358f98f9e2` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p04_c.txt> |
| `p04_w.txt` | input/weight | 30 | `5eb586c0c659c6d746e6eda5da0795812afc4c63791259a7c2a274fef6af5e60` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p04_w.txt> |
| `p04_p.txt` | input/profit | 29 | `d9f102a31d73849425c2ce4a970a82f7b4b591f497980578dc4b1da3d1f110c8` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p04_p.txt> |
| `p05_c.txt` | input/capacity | 7 | `3248423c1f2097f6592fd824017e5ef163e701066f3c2ee0b829e63159d4d518` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p05_c.txt> |
| `p05_w.txt` | input/weight | 18 | `5820062de6534969e9eadad7d51f9ca47f057d3e78a9798f8d33d9b146915f03` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p05_w.txt> |
| `p05_p.txt` | input/profit | 24 | `2fa85603a75194604399f7275c67dc5d1e020842008d6487398af8e7c4c6ab4d` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p05_p.txt> |
| `p05_s.txt` | optional reference | 24 | `1c563c0ee92386add0ad598c2e2c9ff7df078f749e6384e20a8e15bbca44c95f` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p05_s.txt> |
| `p06_c.txt` | input/capacity | 9 | `af1915196cb9572f0b4009a82d45ec3653dd8200bbae4475919c9cad6a6d2774` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p06_c.txt> |
| `p06_w.txt` | input/weight | 30 | `7c7a64be6b196a1be701b413585679ef1826c2e9963cc9b81b52c73e7a8c8856` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p06_w.txt> |
| `p06_p.txt` | input/profit | 30 | `72fc12193721214ff34fc1dec98af63dcf3d76cb3a71659b3d6458d8cea435cb` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p06_p.txt> |
| `p06_s.txt` | optional reference | 40 | `e80639098e548ef7abe683b21ba2946ccbed4826a6c39c884b0e8818b1d563d8` | <https://people.sc.fsu.edu/~jburkardt/datasets/knapsack_multiple/p06_s.txt> |

汇总：18 个必需输入文件、3 个可选 reference 文件，共 21 个文件、495 字节。

## P7b Mock dry-run 与证据等级

`configs/experiments/mkp_fsu_mock_dry_run.yaml` 使用单一 `full_instance` visibility；允许字段只有实例 ID、
capacity、weight、profit、目标、约束和候选签名，明确排除 reference/claimed optimum，且该条件不是昂贵
oracle。provider 固定为 Mock、`network=unused`，不接入 memory runtime。

工程 profile `mkp-fsu-mock-engineering-v1` 为所有 run 提供同一硬上限：20 calls、50000 Mock tokens、
16 generated candidates、16 valid evaluations、USD 0.25、60 seconds。它不是 P6 profile 或论文预算。
固定 root seed 707 通过 benchmark/version/instance checksum/split/visibility/method 派生 run seed。
P01--P06 × EoH/RoCo 共 12 条 run 的接口验收全部完成：EoH 每条实际 8 calls/8 candidates/8 valid
evaluations，RoCo 每条实际 18 calls/13 candidates/13 valid evaluations，Mock cost 为 0；JSONL/CSV、
dataset manifest、六类账本和忽略 wall time 的 replay checksum 可重放。这里的实际 objective 输出只作
evaluator/replay 断言，不作汇总、排名、置信区间或方法比较。

因此，FSU MKP 的这一精确 **离线 Mock 协议**达到 ADR-0007 的 E3；P7b-0 历史边界仍只是 E2。
E3 不表示真实 provider 支持、正式 benchmark、论文原始数据、论文数值复现或模型性能证据。

该数据规模很小，只用于本 E3 离线适配验证。不得用于论文复现、正式统计、模型性能、泛化、显著性
或优越性结论。P7b 没有执行 reference、真实 LLM/API 或任何付费请求；G-041 统计执行保持开放。
