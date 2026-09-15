# Array Generation Guide

本文档说明如何配置阵列生成、如何生成执行文件，以及如何执行整个流程。

## 1. 目标

当前方案的核心目标是：

- 先用一个标准化的三板单元（base / inner / side）作为基础模型
- 根据层数和扇区数生成完整数组
- 给每个实体分配稳定业务编号：`L{layer}_S{sector}_{body_type}`
- 在生成结束后，根据删除清单只保留需要的实体

例如：

- `L1_S1_base`
- `L1_S1_inner`
- `L1_S1_side`
- `L1_S2_base`
- ...

这样可以避免直接依赖 SolidWorks 的 body 索引，保证后续删除和参数化生成稳定可控。

---

## 2. 配置文件结构与需求规范

根据明确需求：
- **层高自动堆叠**：单层总高 $H_{layer} = \text{base\_thickness\_mm} + \text{wall\_height\_mm}$，第 $L$ 层的轴向基准高度为 $Z = (L - 1) \times H_{layer}$，无需手动指定层距。
- **多层上下严格对齐**：所有层共享相同的等分数 $N$（`sector_count`），每层扇区角度严格重合，无层间旋转偏置。
- **删除清单为具体 ID 数组**：在 `custom_clearance.delete_bodies` 中明确罗列待删除的实体逻辑 ID（格式：`L{layer}_S{sector}_{body_type}`）。

### 2.1 推荐完整配置文件结构

```json
{
  "name": "valve_core_multi_layer_demo",
  "version": "1.0",
  "unit_params": {
    "outer_diameter_mm": 60.0,
    "middle_radius_mm": 20.0,
    "inner_radius_mm": 10.0,
    "base_thickness_mm": 10.0,
    "wall_height_mm": 40.0,
    "side_thickness_mm": 10.0
  },
  "array_params": {
    "layer_count": 2,
    "sector_count": 8
  },
  "custom_clearance": {
    "delete_bodies": [
      "L1_S1_inner",
      "L1_S2_side",
      "L2_S1_base"
    ]
  }
}
```

### 2.2 字段说明

#### 1) `unit_params`（单体几何尺寸，单位 mm）
- `outer_diameter_mm`: 外径（$R_0 = \text{outer\_diameter\_mm} / 2$）
- `middle_radius_mm`: 中间半径（$R_1$）
- `inner_radius_mm`: 内径（$R_2$）
- `base_thickness_mm`: 底板厚度
- `wall_height_mm`: 壁高（单层总高 $H_{layer} = \text{base\_thickness} + \text{wall\_height}$）
- `side_thickness_mm`: 侧板厚度

#### 2) `array_params`（阵列排布）
- `layer_count`: 轴向总层数（整数 $\ge 1$）
- `sector_count`: 单圈等分数 $N$（整数 $\ge 3$），扇区单角 $\theta = 360^\circ / N$

#### 3) `custom_clearance`（自定义流道/实体清除）
- `delete_bodies`: 字符串数组，填入需要清除的具体实体逻辑 ID。

---

## 3. 实体编号规则 (Logical ID)

实体编号采用统一的结构化命名：

$$\text{Logical ID} = \text{L}\{layer\}\_\text{S}\{sector\}\_\{body\_type\}$$

- **层号 $L$**：$1 \le layer \le \text{layer\_count}$（自底向上，第 1 层 $Z=0$）
- **扇区号 $S$**：$1 \le sector \le \text{sector\_count}$（逆时针 CCW 方向，第 1 扇区角度范围 $0^\circ \sim \theta$）
- **实体类型 $body\_type$**：
  - `base`：底板实体
  - `inner`：内板实体
  - `side`：侧板实体

**实体总数**：$M = \text{layer\_count} \times \text{sector\_count} \times 3$。例如 2 层、8 扇区时，完整阵列共 $2 \times 8 \times 3 = 48$ 个实体。

---

## 3. 生成数组计划

脚本入口：

- [scripts/execute_array_generation.py](scripts/execute_array_generation.py)

### 3.1 生成默认配置的执行计划

在仓库根目录执行：

```bash
python scripts/execute_array_generation.py --config configs/valve_core_array.example.json --output outputs/generated/array-execution.json
```

生成结果会写入：

- [outputs/generated/array-execution.json](outputs/generated/array-execution.json)

该文件中包含：

- `config`
- `angle_step_deg`
- `manifest`
- `delete_manifest`
- `steps`
- `total_entities`

其中 `manifest` 是最重要的部分，它记录了每个实体的逻辑 ID，例如：

```json
{
  "logical_id": "L1_S2_inner",
  "layer": 1,
  "sector": 2,
  "body_type": "inner",
  "angle_deg": 45.0,
  "translation_mm": [0.0, 0.0, 0.0]
}
```

---

## 4. 指定删除清单

如果你希望在生成后删除一部分实体，可以直接在命令行里传入逻辑 ID：

```bash
python scripts/execute_array_generation.py --config configs/valve_core_array.example.json --output outputs/generated/array-execution.json --delete L1_S1_inner
```

这里的 `--delete` 可以传多个值，例如：

```bash
python scripts/execute_array_generation.py --config configs/valve_core_array.example.json --output outputs/generated/array-execution.json --delete L1_S1_inner L1_S2_side L2_S3_base
```

删除后的执行结构会在 `delete_manifest` 中记录这些目标。

---

## 5. 执行入口：SolidWorks 生成报告

脚本入口：

- [scripts/solidworks_array_execute.py](scripts/solidworks_array_execute.py)

### 5.1 Dry-run 验证

在不真正执行 SolidWorks 的情况下，先验证计划是否正确：

```bash
python scripts/solidworks_array_execute.py --payload outputs/generated/array-execution.json --output outputs/generated/solidworks-array-run.json
```

这会生成一个报告文件，说明：

- 需要生成多少实体
- 删除清单有多少目标
- 后续真实执行的任务是什么

### 5.2 真实执行模式

如果你确认要进入实际流程：

```bash
python scripts/solidworks_array_execute.py --payload outputs/generated/array-execution.json --output outputs/generated/solidworks-array-run.json --execute
```

这个入口会按照配置执行真实处理流程，并输出一份执行报告。

---

## 6. 工作流建议

推荐顺序如下：

1. 编辑配置文件
2. 生成执行 payload
3. 检查 `manifest` 是否正确
4. 如需删除，传入 `--delete`
5. 运行 SolidWorks 执行入口进行处理
6. 检查输出报告，确认删除和生成是否符合预期

---

## 7. 生成顺序示例

### 示例 A：默认生成

```bash
python scripts/execute_array_generation.py --config configs/valve_core_array.example.json --output outputs/generated/array-execution.json
python scripts/solidworks_array_execute.py --payload outputs/generated/array-execution.json --output outputs/generated/solidworks-array-run.json
```

### 示例 B：生成并删除指定实体

```bash
python scripts/execute_array_generation.py --config configs/valve_core_array.example.json --output outputs/generated/array-execution.json --delete L1_S1_inner L1_S2_side
python scripts/solidworks_array_execute.py --payload outputs/generated/array-execution.json --output outputs/generated/solidworks-array-run.json --execute
```

---

## 8. 说明

当前实现处于“阵列逻辑生成和执行入口”阶段。它已经覆盖：

- 配置文件定义
- 生成逻辑编号
- 生成阵列计划
- 生成执行 payload
- 删除清单
- 可执行报告输出

下一步若继续推进到真实 SolidWorks COM 绑定层，可以在这套结构上直接扩展成真正的零件复制、旋转、平移和删除动作。
