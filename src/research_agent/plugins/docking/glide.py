"""Schrödinger Glide 适配器

Glide: Schrödinger 商业分子对接软件
通过 Maestro 命令行 (glide) 执行，使用 input file (*.in) 配置对接参数。
商业软件 - 需要 Schrödinger 许可证。未安装时提供清晰的检测与指引。
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger

from .base import DockingEngine, DockingResult


class GlideEngine(DockingEngine):
    """Glide 对接引擎"""

    name = "glide"
    display_name = "Schrödinger Glide"
    description = "Schrödinger 商业分子对接软件，高精度对接 (SP/XP) 与共价对接"
    license = "Commercial (Schrödinger)"
    binary_name = "glide"

    INSTALL_GUIDE = (
        "1. 从 Schrödinger 购买并安装 Maestro: https://www.schrodinger.com\n"
        "2. 确保 glide 命令在 PATH 中 (通常位于 $SCHRODINGER/glide)\n"
        "3. 配置许可证: export SCHROD_LICENSE_FILE=... 或启动 License Server\n"
        "4. 受体准备: 使用 Protein Preparation Wizard (prepwizard)\n"
        "5. 网格生成: glide -WAIT <gridfile>.in  (Grid Generation)"
    )

    @property
    def install_guide(self) -> str:
        return self.INSTALL_GUIDE

    @classmethod
    def get_default_parameters(cls) -> dict[str, Any]:
        return {
            "precision": {"type": "string", "default": "SP", "enum": ["SP", "XP", "HTVS"],
                           "description": "对接精度: HTVS快速/SP标准/XP高精度"},
            "num_poses": {"type": "integer", "default": 10, "description": "输出姿态数"},
            "gridfile": {"type": "string", "default": "", "description": "Glide网格文件 (.grid)"},
            "ligand_file": {"type": "string", "default": "", "description": "配体文件 (mae/sdf)"},
            "receptor_mae": {"type": "string", "default": "", "description": "受体文件 (mae)"},
        }

    def prepare_receptor(self, receptor_path: str, output_dir: str | None = None) -> dict[str, Any]:
        """准备受体: 调用 prepwizard 进行蛋白准备"""
        self._require_executable()
        receptor = Path(receptor_path)
        if not receptor.exists():
            raise FileNotFoundError(f"受体文件不存在: {receptor_path}")

        # Glide 使用 .mae 格式，若输入为 pdb 则提示使用 prepwizard
        if receptor.suffix.lower() in [".mae", ".maegz"]:
            return {"path": str(receptor), "format": "mae"}

        prepwizard = shutil.which("prepwizard")
        if prepwizard:
            out_dir = Path(output_dir) if output_dir else self.workdir
            out_dir.mkdir(parents=True, exist_ok=True)
            output_mae = out_dir / f"{receptor.stem}_prep.mae"
            cmd = [prepwizard, "-r", str(receptor), "-o", str(output_mae), "-wat", "dis"]
            logger.info(f"运行 prepwizard: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                raise RuntimeError(f"prepwizard 失败: {result.stderr[:500]}")
            return {"path": str(output_mae), "format": "mae"}

        raise RuntimeError(
            "Glide 需要受体为 .mae 格式。未找到 prepwizard，"
            "请使用 Schrödinger Protein Preparation Wizard 准备受体。"
        )

    def prepare_ligand(self, ligand_path: str, output_dir: str | None = None) -> dict[str, Any]:
        """准备配体: 使用 LigPrep"""
        self._require_executable()
        ligand = Path(ligand_path)
        if not ligand.exists():
            raise FileNotFoundError(f"配体文件不存在: {ligand_path}")

        if ligand.suffix.lower() in [".mae", ".sdf", ".maegz", ".pdb"]:
            return {"path": str(ligand), "format": ligand.suffix.lower().lstrip(".")}

        ligprep = shutil.which("ligprep")
        if ligprep:
            out_dir = Path(output_dir) if output_dir else self.workdir
            out_dir.mkdir(parents=True, exist_ok=True)
            output_mae = out_dir / f"{ligand.stem}_lp.mae"
            cmd = [ligprep, "-i", "2", "-o", "1", "-N", "1",
                   str(ligand), str(output_mae)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"LigPrep 失败: {result.stderr[:500]}")
            return {"path": str(output_mae), "format": "mae"}

        raise RuntimeError("未找到 ligprep，请先运行 LigPrep 准备配体。")

    def run_docking(self, receptor: dict, ligand: dict, config: dict[str, Any]) -> DockingResult:
        """执行 Glide 对接"""
        self._require_executable()
        out_dir = self.workdir / "glide_runs"
        out_dir.mkdir(parents=True, exist_ok=True)

        # 生成 glide input file
        input_name = f"glide_{Path(ligand['path']).stem}"
        input_file = out_dir / f"{input_name}.in"
        out_maegz = out_dir / f"{input_name}_pv.maegz"

        precision = config.get("precision", "SP")
        num_poses = config.get("num_poses", 10)

        input_content = (
            f"GRIDFILE   {config.get('gridfile', '')}\n"
            f"LIGANDFILE {ligand['path']}\n"
            f"PRECISION  {precision}\n"
            f"POSE_OUTTYPE ligandlib_pv\n"
            f"NENHANCED 0\n"
            f"NREPORT {num_poses}\n"
            f"OUTPUTDIR {out_dir}\n"
            f"POSE_FILE {input_name}_pv.maegz\n"
            f"POSE_VIEW\n"
        )
        input_file.write_text(input_content)

        cmd = [self.executable_path, "-WAIT", str(input_file)]
        logger.info(f"Glide 命令: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=config.get("timeout", 7200))
        except subprocess.TimeoutExpired:
            return DockingResult(success=False, engine=self.name,
                                 error="Glide 对接超时")

        if result.returncode != 0:
            return DockingResult(success=False, engine=self.name,
                                 error=f"Glide 执行失败: {(result.stderr or result.stdout)[:800]}")

        # 从输出日志解析 GlideScore
        poses = self._parse_glide_log(out_dir)
        return DockingResult(
            success=True,
            engine=self.name,
            poses=poses,
            best_score=poses[0]["score"] if poses else None,
            output_dir=str(out_dir),
            metadata={
                "input_file": str(input_file),
                "output_file": str(out_maegz) if out_maegz.exists() else None,
                "precision": precision,
            },
        )

    def _parse_glide_log(self, out_dir: Path) -> list[dict[str, Any]]:
        """从 Glide 日志解析得分"""
        poses = []
        for log_file in out_dir.glob("*.log"):
            try:
                lines = log_file.read_text().splitlines()
                for line in lines:
                    if "GlideScore" in line or "GScore" in line:
                        parts = line.replace("=", " ").split()
                        for i, p in enumerate(parts):
                            if p in ("GlideScore", "GScore") and i + 1 < len(parts):
                                try:
                                    poses.append({
                                        "rank": len(poses) + 1,
                                        "score": float(parts[i + 1]),
                                        "file": str(log_file),
                                    })
                                except ValueError:
                                    continue
            except Exception as e:
                logger.warning(f"Glide log 解析失败: {e}")
        return poses


__all__ = ["GlideEngine"]

