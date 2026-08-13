"""数据库初始化脚本 - 创建表结构并写入种子数据

用法:
    python -m research_agent.init_db
"""

import asyncio
from loguru import logger


async def main():
    """初始化数据库"""
    logger.info("开始初始化数据库...")

    from .core.db import init_db, AsyncSessionLocal
    from .agents.skills import SkillRegistry
    from .plugins.seed import seed_plugins

    # 1. 创建表
    await init_db()

    # 2. 初始化内置技能
    SkillRegistry.initialize_builtin()
    skills = SkillRegistry.list_all()
    logger.info(f"已注册内置技能: {len(skills)} 个")
    for name, skill in skills.items():
        logger.debug(f"  - [{skill['category']}] {name}: {skill['description']}")

    # 3. 写入插件种子数据
    async with AsyncSessionLocal() as session:
        await seed_plugins(session)

    logger.info("数据库初始化完成!")
    print("\n" + "=" * 50)
    print("初始化完成! 已注册技能:")
    for name, skill in skills.items():
        print(f"  [{skill['category']}] {name}")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
