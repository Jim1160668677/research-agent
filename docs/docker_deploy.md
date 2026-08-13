# Docker 容器化部署文档

## 1. 架构

```
┌────────────────────────────┐
│  docker-compose            │
│  ┌──────────────────────┐  │
│  │ api (python:3.12)    │  │  :8010  REST API
│  │  └─ volume: data/    │  │  (SQLite持久化)
│  └──────────────────────┘  │
│  ┌──────────────────────┐  │
│  │ frontend (node:20)   │  │  :5173  Vue开发服务器
│  └──────────────────────┘  │
└────────────────────────────┘
```

## 2. 快速启动

```bash
# 1. 配置环境变量 (可选, 用于LLM)
export OPENAI_API_KEY=sk-xxx
export ANTHROPIC_API_KEY=sk-ant-xxx

# 2. 启动全部服务 (国内网络自动使用清华 apt/pip/npm 镜像)
docker compose up -d --build

# 3. 初始化数据库 (首次, 容器内执行)
docker compose exec api python -m research_agent.init_db

# 4. 验证
curl http://localhost:8010/health
# → {"status": "healthy", "version": "0.1.0"}

# 5. 查看日志
docker compose logs -f api

# 6. 停止
docker compose down
```

> ⚠️ 修改 vite.config.js / docker-compose.yml 后需 `docker compose up -d` (重建容器)，
> `docker compose restart` 不会应用新环境变量。

## 3. 服务说明

### api 服务
- 镜像: `python:3.12-slim` + requirements.txt
- 端口: 8010
- 数据卷: `research-agent-data:/data` (SQLite 持久化)
- 健康检查: 30s 间隔轮询 /health
- 环境变量:
  - `DATABASE_URL=sqlite+aiosqlite:////data/research_agent.db`
  - `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY`
  - `JWT_SECRET` (生产必须修改!)
  - `DEBUG=false`

### frontend 服务
- 镜像: `node:20-alpine`
- 端口: 5173
- 挂载: `./frontend:/app` + 匿名卷 `/app/node_modules` (容器内独立安装 Linux 依赖)
- 容器内 npm 使用 npmmirror 源加速
- Vite 代理 `/api` → `http://api:8010` (compose 服务名, 容器间网络直连)

## 4. 数据持久化

SQLite 数据库存储在命名卷 `research-agent-data` 中:
```bash
# 备份
docker run --rm -v research-agent-data:/data -v $(pwd):/backup alpine \
  tar czf /backup/backup-$(date +%Y%m%d).tar.gz -C /data .

# 恢复
docker run --rm -v research-agent-data:/data -v $(pwd):/backup alpine \
  tar xzf /backup/backup-xxx.tar.gz -C /data
```

## 5. 生产部署建议

1. **修改默认密钥**: `JWT_SECRET` 必须设置为随机长字符串
2. **API Key 通过环境变量注入**, 使用 Docker secrets 更安全:
   ```yaml
   secrets:
     openai_key:
       file: ./secrets/openai_key.txt
   ```
3. **Nginx 反向代理 + HTTPS** 置于前端之前
4. **监控**: 接入 Prometheus + Grafana 或云监控
5. **数据库迁移**: 生产使用 PostgreSQL 时替换 `DATABASE_URL`
6. **健康检查**: 容器编排平台自动重启失败实例

## 6. 常见问题

### Q: 端口被占用
```bash
docker compose ps  # 查看占用
# 修改 docker-compose.yml 端口映射
```

### Q: 数据库重置
```bash
docker compose down -v  # 删除数据卷重建
```

### Q: 前端无法连接API
检查 Vite 代理配置 `frontend/vite.config.js` 中 target 是否指向 `http://localhost:8010`。

### Q: Windows PowerShell 环境变量
```powershell
$env:OPENAI_API_KEY = "sk-xxx"
docker compose up -d --build
```
