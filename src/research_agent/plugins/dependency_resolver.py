"""依赖解析器 - 自动解析软件间依赖关系

- 传递依赖闭包 (transitive closure)
- 循环依赖检测
- 版本约束校验 (>=, >, <=, <, ==)
- 拓扑排序生成安装顺序
"""

from collections import defaultdict, deque
from typing import Any


class VersionSpec:
    """版本约束解析: ">=1.2", ">=2.0,<3.0", "==1.2.5", ">=1.19" """

    def __init__(self, spec: str):
        self.spec = (spec or "").strip()
        self.constraints: list[tuple[str, tuple]] = []
        for part in [p.strip() for p in self.spec.split(",") if p.strip()]:
            op = None
            for candidate in (">=", "<=", "==", ">", "<", "~="):
                if part.startswith(candidate):
                    op = candidate
                    rest = part[len(candidate):].strip()
                    break
            if op is None:
                op = "=="
                rest = part
            self.constraints.append((op, self._parse(rest)))

    @staticmethod
    def _parse(v: str) -> tuple:
        return tuple(int(x) for x in v.strip().split(".") if x.isdigit())

    def matches(self, version: str) -> bool:
        if not self.spec or not version:
            return True
        actual = self._parse(version)
        if not actual:
            return True
        for op, target in self.constraints:
            if op == ">=" and not (actual >= target):
                return False
            if op == "<=" and not (actual <= target):
                return False
            if op == ">" and not (actual > target):
                return False
            if op == "<" and not (actual < target):
                return False
            if op == "==" and not (actual == target):
                return False
            if op == "~=" and not (actual[:2] == target[:2] and actual >= target):
                return False
        return True

    def __str__(self):
        return self.spec or "any"


class DependencyResolver:
    """依赖解析器: 以插件依赖图为基础解析传递依赖"""

    def __init__(self, get_plugin_by_name):
        """get_plugin_by_name: async (name) -> Optional[dict]"""
        self._get = get_plugin_by_name

    async def resolve(self, root_name: str) -> dict[str, Any]:
        """解析根插件的完整依赖闭包

        返回:
            {
                "root": root_name,
                "total": n,
                "order": ["dep1", "dep2", ...],       # 拓扑安装顺序 (含root)
                "satisfied": [...],                     # 已安装满足的
                "missing": [...],                       # 缺失的
                "conflicts": [...],                     # 版本冲突
                "cycle": null | [...],                  # 循环依赖路径
                "graph": {"name": ["deps..."]},
            }
        """
        visited: set[str] = set()
        stack: list[str] = []
        cycle: list[str] | None = None
        graph: dict[str, list[str]] = {}
        version_map: dict[str, str] = {}  # name -> candidate version
        edge_constraints: dict[tuple[str, str], str] = {}  # (from, to) -> spec

        async def walk(name: str):
            nonlocal cycle
            if cycle:
                return
            if name in stack:
                idx = stack.index(name)
                cycle = stack[idx:] + [name]
                return
            if name in visited:
                return
            stack.append(name)
            plugin = await self._get(name)
            visited.add(name)
            deps: list[str] = []
            if plugin:
                version_map[name] = plugin.get("version") or ""
                for dep in plugin.get("dependencies") or []:
                    dep_name = dep.get("name", "")
                    if not dep_name:
                        continue
                    deps.append(dep_name)
                    edge_constraints[(name, dep_name)] = dep.get("version", "")
                    await walk(dep_name)
            graph[name] = deps
            stack.pop()

        await walk(root_name)

        # 冲突检测: 同一依赖被不同插件以互不兼容版本要求
        conflicts: list[dict[str, Any]] = []
        dep_specs: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for (_, dep_name), spec in edge_constraints.items():
            if spec:
                dep_specs[dep_name].append((_, spec))
        for dep_name, reqs in dep_specs.items():
            for origin, spec in reqs:
                available = version_map.get(dep_name, "")
                matched = any(
                    candidate_name == dep_name and VersionSpec(spec).matches(candidate_ver)
                    for candidate_name, candidate_ver in version_map.items()
                )
                if not matched:
                    conflicts.append({
                        "dependency": dep_name,
                        "required_by": origin,
                        "constraint": spec,
                        "available_version": available,
                        "message": f"{origin} requires {dep_name} {spec}, "
                                   f"but {dep_name} {available or 'unknown'} is available",
                    })

        # 拓扑排序 (Kahn): indegree = 节点的依赖数
        indegree = {n: len(deps) for n, deps in graph.items()}
        queue = deque([n for n, deg in indegree.items() if deg == 0])
        order: list[str] = []
        while queue:
            n = queue.popleft()
            order.append(n)
            for parent, deps in graph.items():
                if n in deps:
                    indegree[parent] -= 1
                    if indegree[parent] == 0:
                        queue.append(parent)

        # 缺失检测: 图中节点对应插件不存在或未安装
        missing, satisfied = [], []
        resolved_names = list(graph.keys())
        if not resolved_names:
            resolved_names = [root_name]
        for name in resolved_names:
            plugin = await self._get(name)
            if plugin is None:
                missing.append({"name": name, "reason": "not_in_market",
                                "message": f"{name} 不在插件市场中"})
            elif not plugin.get("is_installed"):
                missing.append({"name": name,
                                "version": plugin.get("version") or "",
                                "reason": "not_installed",
                                "message": f"{name} 未安装"})
            else:
                satisfied.append({"name": name, "version": plugin.get("version") or ""})

        # 安装顺序: 只含缺失的(依赖先装, 根插件最后)
        missing_names = {m["name"] for m in missing}
        install_order = [n for n in order if n in missing_names]
        if root_name in missing_names and root_name not in install_order:
            install_order.append(root_name)

        return {
            "root": root_name,
            "total": len(resolved_names),
            "order": install_order,
            "satisfied": satisfied,
            "missing": missing,
            "conflicts": conflicts,
            "cycle": cycle,
            "graph": graph,
        }

    @staticmethod
    def check_version_compatible(constraint: str, version: str) -> bool:
        """检查单一版本约束是否满足"""
        return VersionSpec(constraint).matches(version)


__all__ = ["DependencyResolver", "VersionSpec"]
