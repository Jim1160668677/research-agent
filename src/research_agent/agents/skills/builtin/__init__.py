"""内置技能包 - 初始化所有内置技能"""

from ..base import SkillRegistry


def initialize_builtin_skills():
    """初始化所有内置技能"""
    from .docking_skills import register_docking_skills
    from .ncbi_skills import register_ncbi_skills
    from .research_skills import register_research_skills

    register_ncbi_skills(SkillRegistry)
    register_research_skills(SkillRegistry)
    register_docking_skills(SkillRegistry)
    return SkillRegistry


__all__ = ["initialize_builtin_skills"]
