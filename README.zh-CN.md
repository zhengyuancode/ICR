<div align="center">

# ICR · 接口闭合恢复

**工具调用失败后，修复工作流，并保持后续接口兼容。**

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square)
![Version](https://img.shields.io/badge/version-0.1.0-0F766E?style=flat-square)
![Dependencies](https://img.shields.io/badge/core_dependencies-0-475569?style=flat-square)

[English](README.md) · **简体中文**

[快速开始](#快速开始) · [工作流恢复](#工作流恢复) · [关系查询证书](#关系查询证书) · [使用文档](#使用文档) · [实验复现](#测试与实验复现)

</div>

---

ICR（Interface-Closed Recovery）是一个用于**只读工具工作流恢复**的 Python 工具。当某个实现失败，或者替代实现改变了中间数据接口时，ICR 联合选择替代实现和需要调整的节点，避免单独替换一个工具后破坏下游调用。

对于定义在 JSON 关系快照上的单列查询工具，ICR 还可以寻找替代查询路径、生成**观察输入证书**，并执行经过验证的查询：替代路径必须在绑定的快照上，为实际输入返回可信目标值。

## 能做什么

| 工作流修复 | 关系查询恢复 | 应用接入 |
| :--- | :--- | :--- |
| 联合选择实现与修复范围 | 针对实际输入验证替代路径 | 使用 Python API 或 JSON CLI |
| 保持外部输入和最终输出接口 | 拒绝歧义结果和过期证书 | 注册只读 Python 函数或 HTTP 适配器 |
| 实现失败后重新规划 | 按声明的调用成本选择可准入路径 | 在数据传入下游前校验契约 |

## 快速开始

需要 **Python 3.10 或更高版本**。核心工具零运行时依赖，不需要 GPU、模型 API 或下载实验数据集。

```bash
git clone https://github.com/zhengyuancode/ICR.git
cd ICR
python -m pip install .
icr demo
```

已经克隆仓库？在仓库根目录执行最后两条命令即可。也可以使用 `python -m icr demo`。

演示会实际执行两种恢复过程：

- **工作流恢复：** CSV 数据获取工具失败后，切换到 JSON 实现，并同时切换消费者，保持最终摘要的输出接口。
- **查询路径恢复：** 直接余额查询不可用时，改走“客户 → 账户 → 余额”。其他记录的缺失值使全局证书无法通过，但当前输入有完整记录见证，因此可以通过观察输入证书并返回 `42`。

## 工作流恢复

### 1. 生成恢复方案

为每个节点描述原始实现、经过确认的替代实现、操作标识、输入输出契约和变更成本，并把依赖边绑定到输入端口。完整配置见 [`examples/workflow.json`](examples/workflow.json)。

```bash
icr plan examples/workflow.json --failed fetch
```

该命令输出最小成本的实现组合，以及需要变更的节点。规划阶段只生成建议，不调用实际工具。

```json
{
  "assignment": {"fetch": "json", "summarize": "json"},
  "changed": ["fetch", "summarize"],
  "cost": 2,
  "feasible": true
}
```

上面摘录了输出中的关键字段。如果消费者不能变更，可以固定它的原始实现：

```bash
icr plan examples/workflow.json --failed fetch --immutable summarize
```

此时示例会返回不可行，因为 JSON 替代实现无法直接接入原来的 CSV 消费者。

### 2. 接入实际工具

注册自己的处理函数、契约校验器和外部输入后，可以自动执行并在失败后重新规划：

```python
from icr import Workflow, recover

workflow = Workflow.from_file("examples/workflow.json")

# handlers：{(节点名, 实现名): 可调用函数}
# validators：{契约标识: 校验函数}
# external_inputs：{节点名: 按输入端口顺序排列的值}
outputs, plan, failures = recover(
    workflow, handlers, external_inputs, validators, max_attempts=3
)
```

这里的 `handlers`、`validators` 和 `external_inputs` 需要由应用提供。完整可运行示例见 [`icr/demo.py`](icr/demo.py)。

[`examples/http_workflow.py`](examples/http_workflow.py) 提供实际 HTTP 接入示例：通过环境变量 `ICR_CSV_URL` 和 `ICR_JSON_URL` 配置端点后，执行：

```bash
python examples/http_workflow.py customer-1
```

两个端点应提供同一客户的同一逻辑记录，并已确认是只读操作。CSV 端点返回一条带 `id,orders` 表头的记录；JSON 端点返回对应对象。示例会校验客户标识、数据格式，并设置请求超时。

更多配置、求解预算和执行行为见 [工作流使用指南](docs/workflows.md)。

## 关系查询证书

下面的完整 Python 示例不需要网络或模型服务：

```python
from icr import Snapshot, Projection, RelationalRecovery

snapshot = Snapshot([
    {"customer": "Ada", "account": "A7", "balance": 42},
    {"customer": "Ben", "account": None, "balance": 10},
])

engine = RelationalRecovery(snapshot, [
    Projection("customer_account", "customer", "account"),
    Projection("account_balance", "account", "balance"),
])

admission, rejected = engine.repair("customer", "balance", "Ada")
if admission.admitted:
    value = engine.execute(admission.certificate, current_snapshot=snapshot)
    assert value == 42
```

证书包含快照和工具目录的摘要、路径、实际输入、预期输出及记录见证。执行前会重新核验证据，拒绝过期或被修改的证书。

也可以使用 CLI：

```bash
icr repair examples/snapshot.json examples/catalog.json --source customer --target balance --input '"Ada"' --exclude direct_balance --execute
```

`--input` 接收 JSON 值，字符串需要保留 JSON 双引号。如果 Windows PowerShell 的引号转义有差异，直接使用上面的 Python 示例即可。`--exclude` 排除失败工具；不加 `--execute` 时仅输出证书建议。

更多值相等规则、NULL 语义、搜索范围及快照更新方法见 [关系证书指南](docs/relational.md)。

## 使用文档

| 入口 | 内容 |
| :--- | :--- |
| [工作流指南](docs/workflows.md) | 配置、规划、执行、HTTP 适配及代理接入（英文） |
| [关系证书指南](docs/relational.md) | 证据、值相等、路径搜索及快照更新（英文） |
| [HTTP 示例](examples/http_workflow.py) | 接入自己的 CSV / JSON 端点 |
| [实验复现指南](REPRODUCING.md) | 数据获取、实验运行及结果统计（英文） |

<details>
<summary><strong>展开查看公共 API</strong></summary>

| 使用场景 | API |
| :--- | :--- |
| 规划多输入 DAG 的联合修复 | `Workflow`, `plan_repair` |
| 校验后执行已注册的只读函数 | `execute` |
| 执行，并在失败后自动恢复 | `recover` |
| 寻找和执行带证书的关系查询路径 | `RelationalRecovery` |
| 求固定替代方案的最小闭合区域 | `least_region`, `Edge` |
| 精确求解森林上的联合选择 | `solve_tree`, `Choice` |
| 精确求解端口绑定的约束问题 | `solve_ports`, `PortChoice` |

</details>

## 执行契约

操作等价关系和输入输出契约由应用声明，ICR 不会根据工具名称自动推断语义等价。工作流执行器要求显式的只读声明和契约校验器；恢复时会重新执行前驱，不负责写操作回滚或授权。

关系证书验证的是固定快照上的声明式查询语义。对会变化的数据，应用需要获取一致快照并传入执行检查；对任意远程 API 的行为或完整代理任务意图，不能仅凭该证书作保证。

## 测试与实验复现

```bash
python -m pip install ".[test]"
python -m pytest -q
python scripts/verify_claims.py
```

测试覆盖实际执行、HTTP 失败恢复、失败替代实现排除、接口边界、过期快照、歧义查询及穷举 oracle 对照。`verify_claims.py` 从已提交记录重新计算实验统计，不调用模型，也不下载数据。

| 目录 | 用途 |
| :--- | :--- |
| `icr/` | 可安装工具、公共 API 和 CLI |
| `examples/` | 实际接入示例与配置 |
| `docs/` | 工具使用说明 |
| `tests/` | 工具功能及执行测试 |
| `experiments/`, `research/`, `scripts/` | 实验运行程序、结果记录及复核脚本 |

完整实验步骤见 [`REPRODUCING.md`](REPRODUCING.md)。只有重新运行在线模型实验时才需要模型 API；公共数据集遵循上游许可，单独获取。仓库不包含论文、图片或科研绘图生成脚本。

---

<div align="center">

[源代码](https://github.com/zhengyuancode/ICR) · [反馈问题](https://github.com/zhengyuancode/ICR/issues) · [English](README.md)

</div>
