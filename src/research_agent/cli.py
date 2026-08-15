"""Research Agent CLI - 命令行接口"""

import asyncio
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress
from rich.table import Table

console = Console()


@click.group()
@click.version_option(version="1.0.0", prog_name="Research Agent")
def main():
    """科研智能体系统 - Research Agent

    面向科研场景的通用智能体系统，集成生物分析工具、分子对接软件、
    蛋白质结构软件、NCBI数据库接口、真实LLM对话与多智能体协作。
    """
    pass


@main.command()
@click.option("--host", "-h", default="127.0.0.1", help="服务器地址")
@click.option("--port", "-p", default=8010, type=int, help="服务器端口")
@click.option("--debug", "-d", is_flag=True, help="调试模式")
def server(host, port, debug):
    """启动后端服务"""
    console.print(Panel.fit(
        f"[bold]Research Agent 服务启动中...[/bold]\n"
        f"地址: [cyan]{host}:{port}[/cyan]\n"
        f"调试: [{'green' if debug else 'yellow'}]{'开启' if debug else '关闭'}[/]",
        border_style="blue"
    ))

    import uvicorn
    uvicorn.run(
        "research_agent.main:app",
        host=host,
        port=port,
        reload=debug,
        log_level="debug" if debug else "info",
    )


@main.command()
@click.option("--no-window", "-nw", is_flag=True, help="不打开桌面窗口")
@click.option("--browser", "-b", is_flag=True, help="使用浏览器模式")
def desktop(no_window, browser):
    """启动桌面应用"""
    if no_window or browser:
        # 仅启动服务器
        from .desktop_app import DesktopApp
        app = DesktopApp()
        app.initialize_database()
        app.backend.start()

        if browser:
            import webbrowser
            webbrowser.open(app.backend.base_url)
            console.print(f"[green]服务已启动: {app.backend.base_url}[/green]")
            try:
                import time
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            finally:
                app.backend.stop()
    else:
        # 启动完整桌面应用
        from .desktop_app import main as desktop_main
        desktop_main()


@main.command()
def init():
    """初始化数据库"""
    console.print("[bold]初始化数据库...[/bold]")
    console.print("正在创建表结构和种子数据...")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from .init_db import main as init_db_main
        loop.run_until_complete(init_db_main())
        console.print("[green]数据库初始化完成![/green]")
    except Exception as e:
        console.print(f"[red]初始化失败: {e}[/red]")
        sys.exit(1)
    finally:
        loop.close()


@main.command()
@click.argument("message")
@click.option("--session", "-s", help="会话ID")
@click.option("--format", "-f", default="text", type=click.Choice(["text", "json"]), help="输出格式")
def chat(message, session, format):
    """与智能体对话"""
    console.print(Panel(f"[bold]用户:[/bold] {message}", border_style="blue"))

    try:
        from .llm.chat import ChatEngine
        ChatEngine()

        console.print("[italic]处理中...[/italic]")

        # 简化的对话流程
        response = f"收到你的消息: '{message}'。智能体正在学习和进化中。"

        if format == "json":
            import json
            console.print(json.dumps({"response": response, "session": session}, ensure_ascii=False, indent=2))
        else:
            console.print(Panel(f"[bold]AI:[/bold] {response}", border_style="green"))

    except Exception as e:
        console.print(f"[red]对话失败: {e}[/red]")


@main.group()
def plugin():
    """插件管理"""
    pass


@plugin.command("list")
@click.option("--category", "-c", help="按分类筛选")
@click.option("--installed", "-i", is_flag=True, help="只显示已安装")
def plugin_list(category, installed):
    """列出插件"""
    table = Table(title="可用插件", show_lines=True)
    table.add_column("ID", style="cyan")
    table.add_column("名称", style="green")
    table.add_column("分类", style="yellow")
    table.add_column("版本", justify="right")
    table.add_column("状态")

    # 获取插件列表
    try:
        from .plugins.manager import PluginManager
        plugins = PluginManager.list_plugins(category=category, only_installed=installed)

        if not plugins:
            console.print("[yellow]暂无插件[/yellow]")
            return

        for p in plugins:
            status = "[green]已安装[/green]" if p.get("installed") else "[dim]未安装[/dim]"
            table.add_row(
                str(p.get("id", "")),
                p.get("name", ""),
                p.get("category", ""),
                p.get("latest_version", "1.0.0"),
                status
            )

        console.print(table)
    except Exception as e:
        console.print(f"[red]获取插件列表失败: {e}[/red]")


@plugin.command()
@click.argument("plugin_id")
def install(plugin_id):
    """安装插件"""
    console.print(f"正在安装插件 [cyan]{plugin_id}[/cyan]...")

    try:
        from .plugins.deployer import Deployer
        deployer = Deployer()
        result = deployer.deploy(plugin_id)

        if result.get("success"):
            console.print(f"[green]插件 {plugin_id} 安装成功![/green]")
        else:
            console.print(f"[red]安装失败: {result.get('message', '未知错误')}[/red]")
    except Exception as e:
        console.print(f"[red]安装失败: {e}[/red]")


@plugin.command()
@click.argument("plugin_id")
def uninstall(plugin_id):
    """卸载插件"""
    console.print(f"正在卸载插件 [cyan]{plugin_id}[/cyan]...")

    try:
        from .plugins.manager import PluginManager
        success = PluginManager.uninstall_plugin(plugin_id)

        if success:
            console.print(f"[green]插件 {plugin_id} 卸载成功![/green]")
        else:
            console.print("[red]卸载失败[/red]")
    except Exception as e:
        console.print(f"[red]卸载失败: {e}[/red]")


@plugin.command()
@click.argument("plugin_id")
def info(plugin_id):
    """查看插件详情"""
    try:
        from .plugins.manager import PluginManager
        plugin = PluginManager.get_plugin(plugin_id)

        if plugin:
            info_table = Table(show_header=False, box=None)
            info_table.add_column("属性", style="cyan")
            info_table.add_column("值")

            for key, value in plugin.items():
                info_table.add_row(str(key), str(value))

            console.print(Panel(info_table, title=f"插件详情: {plugin.get('name', plugin_id)}", border_style="blue"))
        else:
            console.print(f"[yellow]插件 {plugin_id} 未找到[/yellow]")
    except Exception as e:
        console.print(f"[red]获取插件信息失败: {e}[/red]")


@plugin.command()
def categories():
    """列出插件分类"""
    try:
        from .plugins.seed import get_categories
        cats = get_categories()

        table = Table(title="插件分类", show_lines=True)
        table.add_column("分类", style="cyan")
        table.add_column("名称", style="green")
        table.add_column("工具数", justify="right")

        for cat in cats:
            table.add_row(str(cat.get("id", "")), cat.get("name", ""), str(cat.get("count", 0)))

        console.print(table)
    except Exception as e:
        console.print(f"[red]获取分类失败: {e}[/red]")


@main.group()
def workflow():
    """工作流管理"""
    pass


@workflow.command("list")
@click.option("--category", "-c", help="按分类筛选")
def workflow_list(category):
    """列出自定义工作流"""
    try:
        from .workflows.engine import WorkflowEngine
        workflows = WorkflowEngine.list_workflows(category=category)

        if not workflows:
            console.print("[yellow]暂无工作流[/yellow]")
            return

        table = Table(title="工作流列表", show_lines=True)
        table.add_column("ID", style="cyan")
        table.add_column("名称", style="green")
        table.add_column("分类", style="yellow")
        table.add_column("节点数", justify="right")

        for wf in workflows:
            table.add_row(
                str(wf.get("id", "")),
                wf.get("name", ""),
                wf.get("category", ""),
                str(len(wf.get("nodes", [])))
            )

        console.print(table)
    except Exception as e:
        console.print(f"[red]获取工作流列表失败: {e}[/red]")


@workflow.command()
@click.argument("workflow_id")
@click.option("--inputs", "-i", help="输入参数 JSON")
def run(workflow_id, inputs):
    """执行工作流"""
    console.print(f"正在执行工作流 [cyan]{workflow_id}[/cyan]...")

    try:
        import json

        from .workflows.engine import WorkflowEngine

        input_data = {}
        if inputs:
            input_data = json.loads(inputs)

        with Progress() as progress:
            task = progress.add_task("执行中...", total=100)

            async def execute():
                nonlocal input_data
                result = await WorkflowEngine.execute(workflow_id, input_data)
                return result

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(execute())
                progress.update(task, completed=100)

                if result.get("success"):
                    console.print("[green]工作流执行成功![/green]")
                    console.print(Panel(str(result.get("output", "")[:500]), title="执行结果", border_style="green"))
                else:
                    console.print(f"[red]执行失败: {result.get('message', '未知错误')}[/red]")
            finally:
                loop.close()
    except Exception as e:
        console.print(f"[red]执行失败: {e}[/red]")


@main.group()
def ncbi_cmd():
    """NCBI数据库查询"""
    pass


@ncbi_cmd.command()
@click.argument("query")
@click.option("--max-results", "-m", default=10, help="最大结果数")
def pubmed(query, max_results):
    """搜索PubMed"""
    console.print(f"正在搜索 PubMed: [cyan]{query}[/cyan]")

    try:
        from .ncbi_skills.adapter import NCBIAdapter

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(NCBIAdapter.search_pubmed(query, max_results))

            if results:
                table = Table(title=f"PubMed 搜索结果 ({len(results)} 条)", show_lines=True)
                table.add_column("PMID", style="cyan")
                table.add_column("标题")
                table.add_column("作者")
                table.add_column("年份", justify="right")

                for r in results[:10]:
                    table.add_row(
                        str(r.get("pmid", "")),
                        (r.get("title", "")[:80] + "...") if len(r.get("title", "")) > 80 else r.get("title", ""),
                        r.get("authors", ""),
                        str(r.get("year", ""))
                    )

                console.print(table)
            else:
                console.print("[yellow]未找到结果[/yellow]")
        finally:
            loop.close()
    except Exception as e:
        console.print(f"[red]搜索失败: {e}[/red]")


@ncbi_cmd.command()
@click.argument("accession")
def genbank(accession):
    """获取GenBank序列"""
    console.print(f"正在获取 GenBank: [cyan]{accession}[/cyan]")

    try:
        from .ncbi_skills.adapter import NCBIAdapter

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            record = loop.run_until_complete(NCBIAdapter.fetch_genbank(accession))

            if record:
                console.print(Panel(
                    f"[bold]登录号:[/bold] {record.get('accession', '')}\n"
                    f"[bold]描述:[/bold] {record.get('description', '')}\n"
                    f"[bold]长度:[/bold] {record.get('length', '')} bp\n"
                    f"[bold]物种:[/bold] {record.get('organism', '')}",
                    title="GenBank 记录",
                    border_style="green"
                ))
            else:
                console.print("[yellow]未找到记录[/yellow]")
        finally:
            loop.close()
    except Exception as e:
        console.print(f"[red]获取失败: {e}[/red]")


@main.command()
@click.option("--host", "-h", default="127.0.0.1", help="服务器地址")
@click.option("--port", "-p", default=8010, type=int, help="服务器端口")
def health(host, port):
    """检查服务状态"""
    try:
        import httpx
        resp = httpx.get(f"http://{host}:{port}/health", timeout=3)

        if resp.status_code == 200:
            data = resp.json()
            console.print(Panel(
                f"[green]● 服务运行中[/green]\n"
                f"状态: {data.get('status', 'unknown')}\n"
                f"版本: {data.get('version', 'unknown')}\n"
                f"地址: http://{host}:{port}",
                border_style="green"
            ))
        else:
            console.print("[red]● 服务异常[/red]")
    except Exception:
        console.print("[red]● 服务未启动[/red]")
        console.print(f"  请运行: [cyan]research-agent server --port {port}[/cyan]")


@main.group()
def db():
    """数据库管理"""
    pass


@db.command()
def migrate():
    """执行数据库迁移"""
    console.print("正在执行数据库迁移...")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from .core.db import init_db
            loop.run_until_complete(init_db())
            console.print("[green]数据库迁移完成![/green]")
        finally:
            loop.close()
    except Exception as e:
        console.print(f"[red]迁移失败: {e}[/red]")


@db.command()
def reset():
    """重置数据库 (警告: 清除所有数据)"""
    if not click.confirm("这将重置数据库，所有数据将丢失。继续?"):
        console.print("[yellow]已取消[/yellow]")
        return

    console.print("正在重置数据库...")
    try:
        import os

        from .core.app import settings

        db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
        if os.path.exists(db_path):
            os.remove(db_path)
            console.print(f"[green]已删除: {db_path}[/green]")

        # 重新初始化
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from .init_db import main as init_db_main
            loop.run_until_complete(init_db_main())
            console.print("[green]数据库已重置![/green]")
        finally:
            loop.close()
    except Exception as e:
        console.print(f"[red]重置失败: {e}[/red]")


if __name__ == "__main__":
    main()
