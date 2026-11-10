# AI Code Review

通用 Gitea Actions 推送风险审查，不绑定项目和语言。默认只输出中文报告，可通过业务 CI 顶部配置发现风险时让任务失败。API 或通知错误仍不按代码风险阻断。需要阻止合并时，另在分支保护中将此工作流设为必需检查。基础设施故障、取消和 runner 不可用仍可能导致工作流异常，不能保证任何情况下均为绿色。

## 文档导航

- [后续开发接手指南](AGENTS.md)：模块职责、关键契约、验证与发布规则；新对话先读。
- [项目交接与验证边界](docs/handoff.md)：当前版本、业务试点分支、真实验证证据及待验证事项。
- [业务工作流模板](examples/ai-code-review.yml)：接入时从 main 复制此模板，只改顶部配置。

## 接入与配置

独立工具仓库：https://gitea.adesk.com/actions/ai-code-review 。只包含通用工具和示例，没有业务代码或凭据。

将 `examples/ai-code-review.yml` 复制到业务仓库的 `.gitea/workflows/ai-code-review.yml`，不再复制 Python 脚本。工作流检出业务仓库后，把工具拉到 runner 临时目录，从业务仓库工作目录执行工具绝对路径，因此 Git diff 始终针对业务仓库而不是工具仓库。工具以 `v1.1.0` 版本拉取，示例顶部同时配置并校验完整提交 SHA，升级时显式更新标签与 SHA，不追随 main/latest。

工具仓库不存业务代码和密钥，但 actions 组织当前为受限可见，匿名克隆会被拒绝。示例通过临时 askpass 注入认证：优先使用业务仓库/组织的 `AI_REVIEW_TOOL_READ_TOKEN` Secret，否则尝试任务自带 `gitea.token`。若任务令牌不具备跨仓库读取权限，必须配置专用最小只读令牌（具备 actions/ai-code-review 仓库读取权限）。凭据不嵌入URL、不保存Git配置；不要把AI Key当作Git凭据，也不要为方便克隆扩大组织可见性。

runner 使用 `ubuntu-latest` 标签，需能下载 checkout 动作、克隆工具及访问模型服务，并预装 Python 3.10+（python3）；只使用标准库，不下载 Python/pip，不安装或运行项目依赖。Secrets/Variables 配置在被审查的业务仓库或其所属组织，不是仅配置在 actions 工具组织；组织间不会自动共享密钥。

### CI 顶部可调参数

- `AI_REVIEW_BLOCK_ON_RISK: 'false'`：只报告；改为 `'true'` 时任何明确风险（high/medium/low）都会在报告和通知完成后使任务失败。仅待验证事项或审查失败不触发风险阻断。不回滚已推送代码；阻止合并需配置分支保护。
- `AI_REVIEW_DINGTALK_WEBHOOK: ${{ secrets.AI_REVIEW_DINGTALK_WEBHOOK }}`：可在顶部改成另一个 Secret 名称以选择机器人；不要把含 access_token 的真实地址明文提交。空值表示不发送通知。
- `AI_REVIEW_DINGTALK_KEYWORD: 'gitea'`：可换成对应机器人的安全关键词，消息标题和正文都会带上；需为非空单行，最多 200 UTF-8 字节。
- `AI_REVIEW_TOOL_REF` / `AI_REVIEW_TOOL_SHA`：审查器标签与完整 SHA 配套修改。

以上参数由各业务仓库自行决定，无需改工具源码。风险策略独立在最后一步执行，不用 job 级 continue-on-error 吞掉阻断结果；模型和通知步骤仍为可容错。

组织或仓库 Actions Secrets：

- `AI_REVIEW_OPENAI_API_KEY`：启动开关，缺失/空白时跳过全部审查，不检出代码、不调用 Claude。
- `AI_REVIEW_CLAUDE_API_KEY`：可选备用密钥。
- `AI_REVIEW_DINGTALK_WEBHOOK`：可选，钉钉自定义机器人的完整 Webhook 地址（包含 access_token），只能配置到 Secrets，不能写进仓库或普通变量。机器人安全关键词须与 CI 顶部配置一致，默认 `gitea`。

Actions Variables（可以用实例全局变量；密钥禁止放普通变量）：

- `AI_REVIEW_OPENAI_BASE_URL`：默认 `https://api.openai.com/v1`，不含 `/responses`。
- `AI_REVIEW_OPENAI_MODEL`：必填，账号可用的准确模型 ID。
- `AI_REVIEW_CLAUDE_BASE_URL`：默认 `https://api.anthropic.com/v1`，不含 `/messages`。
- `AI_REVIEW_CLAUDE_MODEL`：备用模型 ID。

OpenAI 使用 Responses API，禁止存储响应（store=false）；Claude 使用原生 Messages API。地址只允许 HTTPS，不跟随重定向。OpenAI 超时、HTTP错误、空文本、结构异常或不完整响应时切换 Claude。发现高风险不属于调用失败，不会触发重审。模型与服务端数据保留政策由实际供应商决定，store=false 不等于零保留。

## 报告与覆盖范围

在 Actions → AI Code Review → 生成中文风险报告步骤查看日志。另在 runner 临时目录写 `ai-code-review-report.md`，临时文件不保证持久保存，不依赖 GitHub 专属制品 API。

普通 push 审查 before..after，包含多提交；手动运行和新分支只审 HEAD 相对第一父提交（根提交相对空树），报告明确标注范围。before 对象不可用时报告未完成，不偷换为上一提交。只监听分支 push，不监听 tag，不处理 PR。每文件带 8 行上下文，不自动读取相关文件，因此跨文件风险可能漏报。

最多考虑 60 个文件、每文件 30KB、总 diff 100KB；二进制、环境文件、常见私钥、凭据目录、依赖目录、锁文件等不发给模型；超限/排除明确标记覆盖不完整。单文件 diff 超过 2MB 或路径清单超过上限时报告未完成。路径过滤不能保证业务源码中没有密码，代码可能包含敏感数据；启用前必须允许代码外发给主、备两家服务。不要把 AI 结论当作测试、安全扫描或人工审查的替代。

## 钉钉风险通知

模型必须返回 JSON 总结、风险 findings 和待验证事项，脚本校验后生成中文 Markdown。仅 findings 存在有效风险条目时发送；无风险、只有待验证事项、审查失败、缺 OpenAI 密钥均不通知。不用自然语言关键词猜测有无风险；结果格式异常触发备用服务。

消息包含顶部配置的关键词（默认 `gitea`）、仓库、提交、CI 链接和报告；超长报告按 UTF-8 字节截断并引导查看完整日志。只允许 `https://oapi.dingtalk.com/robot/send` 地址，不跟随重定向；不发送原始 diff。机器人的关键字安全模式由群管理员配置，若另有加签要求需另行接入，当前不支持签名密钥。通知属于额外向群内分享代码风险信息，请确保群成员具备查看权限。

钉钉 HTTP 成功不代表投递成功，必须检查 errcode=0；失败仅记录固定提示，不打印 Webhook、令牌和服务错误正文、不影响 CI。不自动重试以避免重复发送；手动重新运行 CI 可能重复通知。不发送虚构风险做线上测试；本地使用 mock 验证风险、无风险、拒绝和网络异常路径。

## 信任边界

本方案在当前 push 的工作流和审查脚本中使用 Secrets，要求所有有权推送并触发该工作流的人可信。它不执行业务代码，但不能阻止有写权限的人修改工作流来取走密钥；组织级密钥也有相同边界。需要对不可信提交隔离时，应使用独立受信 CI 控制面或外部 webhook 审查服务，而不是仅靠提示词或分支保护。建议独立审查密钥、额度上限、可信 HTTPS 网关、限制出网。

模型输出作为不可信文本：不执行命令、不自动修复、不自动评论；输出加行前缀防 Actions 日志命令注入，隐藏当前配置的两把 API Key。其他源码敏感值无法保证自动识别。

## 本地验证

```text
python -m unittest discover -s . -p "test_*.py" -v
python -m ruff check .
```

单测不访问网络、无真实密钥；真实联通与备用接口测试需要在 Gitea 上实际运行，不能用 mock 成功替代。
