# 分子对接与蛋白质结构软件集成文档

## 1. 集成软件清单

### 1.1 分子对接引擎
| 软件 | 许可证 | 检测命令 | 输出格式 |
|------|--------|----------|----------|
| AutoDock Vina | GPL | `vina` | PDBQT + log |
| Schrödinger Glide | 商业 | `glide` | MAE/Maestro |
| CCDC GOLD | 商业 | `gold` | gold_solutions.txt |

### 1.2 蛋白质结构工具
| 软件 | 许可证 | 检测命令 | 功能 |
|------|--------|----------|------|
| PyMOL | 开源/商业 | `pymol` | 结构渲染、突变分析 |
| UCSF ChimeraX | 开源 | `chimerax` | 结构渲染、密度图 |
| Swiss-PdbViewer | 免费 | `spdbv` | 结构比对、氢键分析 |

## 2. 架构设计

### 2.1 统一抽象层

```
DockingEngine (抽象基类)
 ├── prepare_receptor(path) → {path, format}
 ├── prepare_ligand(path)   → {path, format}
 ├── run_docking(receptor, ligand, config) → DockingResult
 └── detect(config_paths)   → executable_path | None

StructureTool (抽象基类)
 ├── render_structure(pdb, output, style) → StructureJob
 └── detect(config_paths)   → executable_path | None
```

### 2.2 检测机制
1. 用户配置路径（通过 `DockingManager(config)` 传入）
2. 系统 PATH（`shutil.which`）
3. 未找到 → `available=False` + 安装指引（API返回）

### 2.3 结果标准化
所有引擎统一返回 `DockingResult`：
```json
{
  "success": true,
  "engine": "autodock_vina",
  "poses": [{"rank": 1, "score": -7.2, "file": "..."}],
  "best_score": -7.2,
  "output_dir": "./docking_work/vina_runs",
  "error": null
}
```

## 3. 调用方式

### 3.1 REST API
```bash
# 查看引擎状态
GET /api/v1/docking/engines

# 执行对接
POST /api/v1/docking/run
{
  "engine": "autodock_vina",
  "receptor_path": "/data/receptor.pdb",
  "ligand_path": "/data/ligand.pdb",
  "parameters": {"center_x": 10.5, "center_y": 20.3, "center_z": 5.0,
                 "size_x": 25, "size_y": 25, "size_z": 25}
}

# 渲染结构
POST /api/v1/docking/structure/render
{
  "tool": "pymol",
  "pdb_path": "/data/protein.pdb",
  "style": "cartoon"
}
```

### 3.2 技能调用
```python
await executor.execute("molecular_docking",
    engine="autodock_vina",
    receptor_path="receptor.pdb",
    ligand_path="ligand.pdb",
    center_x=10.5, center_y=20.3, center_z=5.0,
    size_x=25, size_y=25, size_z=25)

await executor.execute("structure_render",
    tool="chimerax",
    pdb_path="protein.pdb",
    style="surface")

await executor.execute("docking_status")  # 检查所有引擎可用性
```

## 4. 各引擎说明

### 4.1 AutoDock Vina
- 准备: `prepare_receptor4.py`/`prepare_ligand4.py` (MGLTools) 或 Open Babel 生成 PDBQT
- 参数: center/size (对接盒子), exhaustiveness, num_modes
- 输出: PDBQT 姿态文件 + log 分数表

### 4.2 Glide
- 准备: prepwizard (受体), LigPrep (配体)
- 参数: precision (HTVS/SP/XP), gridfile
- 通过生成 `.in` 输入文件驱动

### 4.3 GOLD
- 准备: mol2/pdb/sdf 格式
- 参数: fitness_function (chemscore/goldscore/plp/asp), binding_site
- 通过生成 `GOLD.conf` 驱动，结果在 `gold_solutions.txt`

## 5. 未安装时的行为
- `DockingManager.list_engines()` 返回 `available: false` + `install_guide`
- 执行对接返回结构化错误: `{"success": false, "error": "...未安装..."}`
- 前端据此展示安装指引

## 6. 测试覆盖
- 引擎检测逻辑 (mock PATH)
- 默认参数完整性
- 结果解析 (Vina log/PDBQT, GOLD solutions)
- 缺失文件/未安装错误处理
- 技能注册与执行
- 完整 API 路由测试

运行: `pytest tests/test_docking.py` (25个测试)
