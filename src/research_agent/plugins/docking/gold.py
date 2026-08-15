"""GOLD (CCDC) 适配器

GOLD: 剑桥晶体数据中心 (CCDC) 的遗传算法分子对接软件 (商业)
通过 gold 命令行 + GOLD.conf 配置文件执行对接。
"""

import subprocess
from pathlib import Path
from typing import Any

from loguru import logger

from .base import DockingEngine, DockingResult


class GoldEngine(DockingEngine):
    """GOLD 对接引擎"""

    name = "gold"
    display_name = "CCDC GOLD"
    description = "基于遗传算法的分子对接软件，支持柔性侧链和共价对接"
    license = "Commercial (CCDC)"
    binary_name = "gold"

    INSTALL_GUIDE = (
        "1. 从 CCDC 购买 GOLD 并安装: https://www.ccdc.cam.ac.uk/solutions/software/gold/\n"
        "2. 确保 gold 命令在 PATH 中\n"
        "3. 配置许可: export GOLD_LICENSE_FILE=... 或使用 CCDC License Manager\n"
        "4. GOLD 使用 GOLD.conf 配置文件驱动对接"
    )

    @property
    def install_guide(self) -> str:
        return self.INSTALL_GUIDE

    @classmethod
    def get_default_parameters(cls) -> dict[str, Any]:
        return {
            "protein_file": {"type": "string", "default": "", "description": "蛋白文件 (mol2/pdb)"},
            "ligand_file": {"type": "string", "default": "", "description": "配体文件 (mol2/sdf)"},
            "binding_site": {"type": "string", "default": "sphere", "enum": ["sphere", "cavity", "point"],
                             "description": "结合位点定义方式"},
            "sphere_x": {"type": "number", "default": 0.0, "description": "结合位点球心X"},
            "sphere_y": {"type": "number", "default": 0.0, "description": "结合位点球心Y"},
            "sphere_z": {"type": "number", "default": 0.0, "description": "结合位点球心Z"},
            "sphere_radius": {"type": "number", "default": 10.0, "description": "结合位点球半径"},
            "fitness_function": {"type": "string", "default": "chemscore",
                                 "enum": ["chemscore", "goldscore", "plp", "asp"],
                                 "description": "打分函数"},
            "num_runs": {"type": "integer", "default": 10, "description": "遗传算法运行次数"},
            "search_efficiency": {"type": "string", "default": "100%",
                                  "enum": ["30%", "50%", "100%", "200%"],
                                  "description": "搜索效率"},
        }

    def prepare_receptor(self, receptor_path: str, output_dir: str | None = None) -> dict[str, Any]:
        """准备受体: GOLD 使用 mol2 或 pdb 格式"""
        self._require_executable()
        receptor = Path(receptor_path)
        if not receptor.exists():
            raise FileNotFoundError(f"受体文件不存在: {receptor_path}")

        if receptor.suffix.lower() in [".mol2", ".pdb", ".sdf"]:
            return {"path": str(receptor), "format": receptor.suffix.lower().lstrip(".")}

        raise RuntimeError(
            f"GOLD 支持 mol2/pdb/sdf 格式的受体，当前文件: {receptor.suffix}。"
            "请使用 MOE/SYBYL 等工具转换格式。"
        )

    def prepare_ligand(self, ligand_path: str, output_dir: str | None = None) -> dict[str, Any]:
        """准备配体"""
        self._require_executable()
        ligand = Path(ligand_path)
        if not ligand.exists():
            raise FileNotFoundError(f"配体文件不存在: {ligand_path}")

        if ligand.suffix.lower() in [".mol2", ".pdb", ".sdf", ".smi"]:
            return {"path": str(ligand), "format": ligand.suffix.lower().lstrip(".")}

        raise RuntimeError(
            f"GOLD 支持 mol2/pdb/sdf/smi 格式的配体，当前文件: {ligand.suffix}"
        )

    def run_docking(self, receptor: dict, ligand: dict, config: dict[str, Any]) -> DockingResult:
        """执行 GOLD 对接"""
        self._require_executable()
        out_dir = self.workdir / "gold_runs"
        out_dir.mkdir(parents=True, exist_ok=True)

        # 生成 GOLD.conf
        conf_file = out_dir / "GOLD.conf"
        binding = config.get("binding_site", "sphere")

        conf_lines = [
            "GOLD_GA_SEED = 0",
            f"FITNESS_FUNCTION = {config.get('fitness_function', 'chemscore')}",
            f"PROTEIN_FILE = {receptor['path']}",
            f"LIGAND_FILE = {ligand['path']}",
            f"NUMBER_OF_RUNS = {config.get('num_runs', 10)}",
            f"SEARCH_EFFICIENCY = {config.get('search_efficiency', '100%')}",
            f"BEST_HITS = {config.get('num_modes', 5)}",
            "FLIP_FREE_CORNERS = true",
            "FLIP_PYRIMIDAL_NITROGEN = true",
            "FLIP_AMIDE_BONDS = false",
            "DETECT_CIS_TRANS = true",
            "DETECT_MLP = true",
        ]

        if binding == "sphere":
            conf_lines.extend([
                "DEFINE_BINDING_SITE = sphere",
                f"CENTER = {config.get('sphere_x', 0.0)} {config.get('sphere_y', 0.0)} {config.get('sphere_z', 0.0)}",
                f"RADIUS = {config.get('sphere_radius', 10.0)}",
            ])
        elif binding == "cavity":
            conf_lines.append("DEFINE_BINDING_SITE = cavity")
        else:
            conf_lines.extend([
                "DEFINE_BINDING_SITE = point",
                f"BINDING_POINT = {config.get('sphere_x', 0.0)} {config.get('sphere_y', 0.0)} {config.get('sphere_z', 0.0)}",
            ])

        conf_lines.append("OUTPUT_DIR = " + str(out_dir))
        conf_file.write_text("\n".join(conf_lines))

        cmd = [self.executable_path, str(conf_file)]
        logger.info(f"GOLD 命令: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=config.get("timeout", 7200))
        except subprocess.TimeoutExpired:
            return DockingResult(success=False, engine=self.name,
                                 error="GOLD 对接超时")

        if result.returncode != 0:
            return DockingResult(success=False, engine=self.name,
                                 error=f"GOLD 执行失败: {(result.stderr or result.stdout)[:800]}")

        poses = self._parse_gold_results(out_dir)
        return DockingResult(
            success=True,
            engine=self.name,
            poses=poses,
            best_score=poses[0]["score"] if poses else None,
            output_dir=str(out_dir),
            metadata={"conf_file": str(conf_file)},
        )

    def _parse_gold_results(self, out_dir: Path) -> list[dict[str, Any]]:
        """解析 GOLD 输出文件 gold_solutions.txt"""
        poses = []
        solutions_file = out_dir / "gold_solutions.txt"
        if not solutions_file.exists():
            return poses
        try:
            lines = solutions_file.read_text().splitlines()
            rank = 0
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith(("Fit", "---", "#")):
                    continue
                parts = stripped.split()
                # GOLD solutions 格式: Fit值 各分项...
                if len(parts) >= 2:
                    try:
                        fit = float(parts[0])
                        rank += 1
                        poses.append({
                            "rank": rank,
                            "score": fit,
                            "file": str(solutions_file),
                        })
                    except ValueError:
                        continue
        except Exception as e:
            logger.warning(f"GOLD 结果解析失败: {e}")
        return poses


__all__ = ["GoldEngine"]

