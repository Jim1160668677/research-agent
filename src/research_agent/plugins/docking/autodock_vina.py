"""AutoDock Vina 适配器

AutoDock Vina: 开源分子对接软件 (GPL)
文档: https://github.com/ccsb-scripps/AutoDock-Vina
工作流: 受体/配体需转换为 PDBQT 格式 (用 prepare_receptor4.py / prepare_ligand4.py 或
AutoDockTools)，Vina 通过配置文件或命令行参数执行对接。
"""

from typing import Dict, List, Any, Optional
import subprocess
import shutil
from pathlib import Path
from loguru import logger

from .base import DockingEngine, DockingResult


class AutoDockVinaEngine(DockingEngine):
    """AutoDock Vina 对接引擎"""

    name = "autodock_vina"
    display_name = "AutoDock Vina"
    description = "开源分子对接软件，使用启发式搜索算法预测配体结合模式"
    license = "GPL"
    binary_name = "vina"

    INSTALL_GUIDE = (
        "1. 下载: https://github.com/ccsb-scripps/AutoDock-Vina/releases\n"
        "2. Windows: 将 vina.exe 加入 PATH\n"
        "3. Linux: sudo apt install autodock-vina 或从源码编译\n"
        "4. 配体/受体准备: 安装 AutoDockTools 或 MGLTools (prepare_receptor4.py / prepare_ligand4.py)"
    )

    @property
    def install_guide(self) -> str:
        return self.INSTALL_GUIDE

    @classmethod
    def get_default_parameters(cls) -> Dict[str, Any]:
        return {
            "center_x": {"type": "number", "default": 0.0, "description": "对接盒子中心X"},
            "center_y": {"type": "number", "default": 0.0, "description": "对接盒子中心Y"},
            "center_z": {"type": "number", "default": 0.0, "description": "对接盒子中心Z"},
            "size_x": {"type": "number", "default": 20.0, "description": "盒子尺寸X (埃)"},
            "size_y": {"type": "number", "default": 20.0, "description": "盒子尺寸Y (埃)"},
            "size_z": {"type": "number", "default": 20.0, "description": "盒子尺寸Z (埃)"},
            "exhaustiveness": {"type": "integer", "default": 8, "description": "搜索穷尽度 (越大越精确)"},
            "num_modes": {"type": "integer", "default": 9, "description": "输出结合模式数量"},
            "energy_range": {"type": "number", "default": 3.0, "description": "最大能量差 (kcal/mol)"},
        }

    def prepare_receptor(self, receptor_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """准备受体: 尝试用 prepare_receptor4.py 转换为 PDBQT"""
        self._require_executable()
        out_dir = Path(output_dir) if output_dir else self.workdir
        out_dir.mkdir(parents=True, exist_ok=True)

        receptor = Path(receptor_path)
        if not receptor.exists():
            raise FileNotFoundError(f"受体文件不存在: {receptor_path}")

        # 如果已是 PDBQT 直接使用
        if receptor.suffix.lower() == ".pdbqt":
            return {"path": str(receptor), "format": "pdbqt"}

        # 查找 prepare_receptor4.py
        prep_script = shutil.which("prepare_receptor4.py") or self._find_prep_script()
        pdbqt_path = out_dir / f"{receptor.stem}_receptor.pdbqt"

        if prep_script:
            logger.info(f"使用 {prep_script} 转换受体为 PDBQT")
            cmd = [prep_script, "-r", str(receptor), "-o", str(pdbqt_path)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"受体准备失败: {result.stderr[:500]}")
        else:
            raise RuntimeError(
                "未找到 prepare_receptor4.py (AutoDockTools)。"
                "请安装 MGLTools: https://ccsb.scripps.edu/mgltools/"
            )

        return {"path": str(pdbqt_path), "format": "pdbqt"}

    def _find_prep_script(self) -> Optional[str]:
        """在常见位置查找 prepare_receptor4.py"""
        for pattern in [
            Path.home() / "mgltools*" / "bin" / "prepare_receptor4.py",
            Path.home() / "Programs" / "mgltools*" / "bin" / "prepare_receptor4.py",
            Path("C:/Program Files") / "MGLTools*" / "bin" / "prepare_receptor4.py",
        ]:
            matches = list(Path.home().parent.glob(str(pattern).replace(str(Path.home().parent), "*"))) if "*" in str(pattern) else []
            if pattern.exists():
                return str(pattern)
            if matches:
                return str(matches[0])
        return None

    def prepare_ligand(self, ligand_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """准备配体: 转换为 PDBQT"""
        self._require_executable()
        out_dir = Path(output_dir) if output_dir else self.workdir
        out_dir.mkdir(parents=True, exist_ok=True)

        ligand = Path(ligand_path)
        if not ligand.exists():
            raise FileNotFoundError(f"配体文件不存在: {ligand_path}")

        if ligand.suffix.lower() == ".pdbqt":
            return {"path": str(ligand), "format": "pdbqt"}

        prep_script = shutil.which("prepare_ligand4.py") or self._find_prep_script()
        pdbqt_path = out_dir / f"{ligand.stem}_ligand.pdbqt"

        if prep_script:
            cmd = [prep_script, "-l", str(ligand), "-o", str(pdbqt_path)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"配体准备失败: {result.stderr[:500]}")
        else:
            # 尝试使用 Open Babel
            obabel = shutil.which("obabel")
            if obabel:
                cmd = [obabel, str(ligand), "-O", str(pdbqt_path), "--partialcharge", "gasteiger"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    raise RuntimeError(f"Open Babel 转换失败: {result.stderr[:500]}")
            else:
                raise RuntimeError(
                    "未找到 prepare_ligand4.py 或 Open Babel。"
                    "请安装 MGLTools 或 Open Babel (https://openbabel.org)"
                )

        return {"path": str(pdbqt_path), "format": "pdbqt"}

    def run_docking(self, receptor: Dict, ligand: Dict, config: Dict[str, Any]) -> DockingResult:
        """执行 Vina 对接"""
        self._require_executable()
        out_dir = self.workdir / "vina_runs"
        out_dir.mkdir(parents=True, exist_ok=True)

        output_path = out_dir / f"{Path(ligand['path']).stem}_out.pdbqt"
        log_path = out_dir / f"{Path(ligand['path']).stem}_log.txt"

        cmd = [
            self.executable_path,
            "--receptor", receptor["path"],
            "--ligand", ligand["path"],
            "--center_x", str(config.get("center_x", 0.0)),
            "--center_y", str(config.get("center_y", 0.0)),
            "--center_z", str(config.get("center_z", 0.0)),
            "--size_x", str(config.get("size_x", 20.0)),
            "--size_y", str(config.get("size_y", 20.0)),
            "--size_z", str(config.get("size_z", 20.0)),
            "--exhaustiveness", str(config.get("exhaustiveness", 8)),
            "--num_modes", str(config.get("num_modes", 9)),
            "--energy_range", str(config.get("energy_range", 3.0)),
            "--out", str(output_path),
            "--log", str(log_path),
        ]

        logger.info(f"Vina 对接命令: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=config.get("timeout", 3600))
        except subprocess.TimeoutExpired:
            return DockingResult(
                success=False, engine=self.name,
                error=f"对接超时 (>{config.get('timeout', 3600)}s)",
            )

        if result.returncode != 0:
            return DockingResult(
                success=False, engine=self.name,
                error=f"Vina 执行失败: {(result.stderr or result.stdout)[:800]}",
            )

        # 解析结果
        poses = self._parse_log(log_path)
        if not poses and output_path.exists():
            # 回退: 从 PDBQT 输出解析
            poses = self._parse_pdbqt(output_path)

        return DockingResult(
            success=True,
            engine=self.name,
            poses=poses,
            best_score=poses[0]["score"] if poses else None,
            output_dir=str(out_dir),
            metadata={
                "log_path": str(log_path),
                "output_path": str(output_path),
                "stdout": result.stdout[:500],
            },
        )

    def _parse_log(self, log_path: Path) -> List[Dict[str, Any]]:
        """解析 Vina log 文件中的得分"""
        poses = []
        if not log_path.exists():
            return poses
        try:
            lines = log_path.read_text().splitlines()
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith(("mode", "---", "|")):
                    continue
                # 第一列是数字(rank)，第二列是得分
                parts = stripped.split()
                if len(parts) >= 2 and parts[0].isdigit():
                    try:
                        rank = int(parts[0])
                        score = float(parts[1])
                        poses.append({
                            "rank": rank,
                            "score": score,
                            "file": str(log_path),
                        })
                    except (ValueError, IndexError):
                        continue
        except Exception as e:
            logger.warning(f"Vina log 解析失败: {e}")
        return poses

    def _parse_pdbqt(self, output_path: Path) -> List[Dict[str, Any]]:
        """从 PDBQT 输出文件解析模型得分"""
        poses = []
        if not output_path.exists():
            return poses
        try:
            lines = output_path.read_text().splitlines()
            for line in lines:
                if line.startswith("MODEL"):
                    pass
                elif "REMARK VINA RESULT" in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            score = float(parts[3])
                            poses.append({
                                "rank": len(poses) + 1,
                                "score": score,
                                "file": str(output_path),
                            })
                        except ValueError:
                            continue
        except Exception as e:
            logger.warning(f"Vina PDBQT 解析失败: {e}")
        return poses


__all__ = ["AutoDockVinaEngine"]

