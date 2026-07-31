# TA01 模型服务配置

模型服务只能在项目根目录 `.env` 配置。先复制 `.env.example` 为 `.env`，填写：

```dotenv
ALPHADESK_AI_RESEARCH_PROVIDER=openai_compatible
ALPHADESK_AI_BASE_URL=https://your-provider.example/v1
ALPHADESK_AI_API_KEY=your-local-secret
ALPHADESK_AI_MODEL=your-model-name
```

然后重建或重启 `api` 与 `ai_research_worker`。API 和 Worker 必须读取同一组变量。不要添加 `VITE_` 前缀，不要把 `.env` 提交到 Git，也不要在网页、截图、日志或调研问题里粘贴 Key。

本地流程验收可显式使用：

```dotenv
ALPHADESK_AI_RESEARCH_PROVIDER=fake
```

Fake 输出不是真实 AI 分析。默认 `disabled` 会禁用创建按钮。工作台上的“测试模型连接”只发起受控短请求，不返回 Key，也不创建调研任务。

兼容性要求为 OpenAI 风格 Chat Completions 和 JSON Schema 结构化响应。超时、重试、输出 Token、温度及成本参数沿用 [真实 AI Provider](real_ai_provider.md) 的服务端环境配置。
