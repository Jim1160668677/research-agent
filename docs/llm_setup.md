# LLM 接入、诊断与密钥管理

## 支持矩阵

| Provider | 环境变量 | 默认模型 | 接入方式 |
|---|---|---|---|
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-v4-pro` | OpenAI-compatible Python SDK |
| Agnes | `AGNES_API_KEY` | `agnes-2.0-flash` | `agnes-ai-cli@^0.1.0`（CLI-first） |
| OpenAI | `OPENAI_API_KEY` | `gpt-4o` | 官方 Python SDK |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-5` | 官方 Python SDK |
| Google | `GOOGLE_API_KEY` | `gemini-1.5-pro` | 官方 Python SDK |

DeepSeek 当前接口依据：[官方 API 文档](https://api-docs.deepseek.com/)。Agnes 需要 Node.js 20+；Windows 使用 `npx.cmd`，不要直接调用会受 execution policy 影响的 `npx.ps1`。

## 桌面配置

启动桌面程序后进入“AI 模型配置”：

1. 选择 Provider 和模型；
2. 保存 API Key；密钥按当前用户加密存储；
3. 先运行“本地检查”，确认凭据和外部运行时；
4. 再运行“真实检查”，这会产生一个最小网络调用和少量 token；
5. 检查成功后设为共享默认模型。Chat、科研智能体和多智能体汇总都会读取该偏好。

系统不会允许尚未配置 Key 的 Provider 成为默认模型。

## 环境变量

```ini
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-pro
AGNES_API_KEY=
AGNES_MODEL=agnes-2.0-flash
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
```

用户数据库中的 Key 优先于环境变量。API 只返回掩码，日志不输出明文凭据。

## API

```http
GET    /api/v1/llm/status
GET    /api/v1/llm/keys
POST   /api/v1/llm/keys
DELETE /api/v1/llm/keys/{provider}
PUT    /api/v1/llm/preference
POST   /api/v1/llm/providers/{provider}/health?live=false
POST   /api/v1/llm/providers/{provider}/health?live=true
POST   /api/v1/llm/chat
GET    /api/v1/llm/chat/status
```

保存 DeepSeek Key：

```json
{"provider":"deepseek","api_key":"<secret>","name":"课题组账户"}
```

设置默认模型：

```json
{"provider":"deepseek","model":"deepseek-v4-pro"}
```

## 可靠性语义

- 显式连接/读取/写入/总超时；
- 对限流、超时、网络和可恢复上游错误做有限次数指数抖动重试；
- 对鉴权、无效请求、无效模型和无效 CLI 输出不盲目重试；
- 响应记录 attempts 与 latency_ms；
- LLM 调用加入进程级 RuntimeCoordinator，避免与工作流/外部任务无限争抢资源；
- 用户 Key 与偏好贯穿 ChatEngine、ResearchAgent 和 CoordinatorAgent；
- 未配置模型时 ResearchAgent 可回退规则响应，显式 `/llm/chat` 则返回可操作错误。

## Agnes 运维

兼容范围为 `agnes-ai-cli >=0.1.0,<0.2.0`。适配器以参数数组启动子进程，不经过 shell；Key 只注入该子进程环境。Windows 提示词在 CLI 传输层转换为单行角色分隔格式，防止批处理把换行解析为命令边界。

手动真实 smoke（会调用模型）：

```powershell
$env:AGNES_API_KEY = "<secret>"
python scripts/smoke_agnes_live.py
```

成功输出只含正文、Provider、模型、重试次数、延迟和 usage，不含 Key。

## 测试

离线契约测试不会读取宿主机的真实 Provider 环境变量，也不会产生模型费用。真实 smoke 与 DeepSeek live health 必须显式配置 Key 后单独运行。完整记录见 [P4 验收报告](p4_co_scientist_model_sync_acceptance.md)。

