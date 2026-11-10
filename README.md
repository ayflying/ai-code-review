# AI Code Review

给 Gitea 仓库接入 AI 代码审查：推送后自动检查代码变更、输出中文报告，发现明确风险时发送钉钉通知。默认不阻断 CI，可按仓库开启。

## 1. 添加工作流

从本仓库 **main 分支**复制 [工作流模板](examples/ai-code-review.yml)，放到业务仓库的 `.gitea/workflows/ai-code-review.yml`。

只需复制这一份文件，不用复制 Python 脚本。工作流会自动拉取固定版本的审查器，在业务仓库中执行。

## 2. 配置密钥和模型

在**业务仓库或其所属组织**的 Actions 设置中配置以下内容；只配置到工具仓库不会生效。

**Secrets（密钥）**

| 名称 | 是否必填 | 用途 |
| --- | --- | --- |
| `AI_REVIEW_OPENAI_API_KEY` | 必填 | 主模型密钥；为空时跳过全部审查和通知 |
| `AI_REVIEW_TOOL_READ_TOKEN` | 按需 | 读取本工具仓库的最小只读令牌；任务自带令牌能跨库读取时可不配 |
| `AI_REVIEW_CLAUDE_API_KEY` | 可选 | 主模型失败后使用的备用密钥 |
| `AI_REVIEW_DINGTALK_WEBHOOK` | 可选 | 钉钉机器人的完整 Webhook 地址 |

**Variables（普通变量）**

| 名称 | 是否必填 | 用途 |
| --- | --- | --- |
| `AI_REVIEW_OPENAI_MODEL` | 必填 | 账号可用的准确模型 ID |
| `AI_REVIEW_OPENAI_BASE_URL` | 可选 | 默认 `https://api.openai.com/v1`，不要加 `/responses` |
| `AI_REVIEW_CLAUDE_MODEL` | 使用备用时必填 | 备用模型 ID |
| `AI_REVIEW_CLAUDE_BASE_URL` | 可选 | 默认 `https://api.anthropic.com/v1`，不要加 `/messages` |

密钥、Webhook 和 Git 令牌只能放 Secrets，不能写进代码、文档或普通变量。runner 需预装 Python 3.10+、Bash、Git，并能访问工具仓库和模型服务；不需要安装业务依赖。

## 3. 修改工作流顶部配置

```yaml
env:
  AI_REVIEW_BLOCK_ON_RISK: 'false'  # true：发现风险时任务失败；false：只报告
  # 不指定其他机器人时保留默认 Secret 引用，使用环境已配置的机器人。
  # 更换机器人只改 Secret 名称；禁止填写真实地址，清空值则不通知。
  AI_REVIEW_DINGTALK_WEBHOOK: ${{ secrets.AI_REVIEW_DINGTALK_WEBHOOK }}
  AI_REVIEW_DINGTALK_KEYWORD: 'gitea'  # 与所选机器人的安全关键词一致
  AI_REVIEW_TOOL_REF: 'v1.1.0'  # 固定工具版本，升级时与 SHA 配套修改
  AI_REVIEW_TOOL_SHA: '84d21423b4f28f882addbd533f67f36489a5c38b'  # 版本对应的完整提交 SHA
```

- **只报告**：保持 `AI_REVIEW_BLOCK_ON_RISK: 'false'`。改成 `'true'` 后，发现任何明确风险都会让任务失败；审查或通知失败不按代码风险阻断。
- **钉钉通知**：不填写其他机器人配置时，保留默认 Secret 引用即可使用环境中已配置的 `AI_REVIEW_DINGTALK_WEBHOOK`。要换机器人就引用另一个 Secret；清空值或 Secret 未配置则不通知。安全关键词默认 `gitea`，需与所选机器人一致；当前不支持加签机器人。
- **工具版本**：标签与完整 SHA 必须配套，不要改成 main/latest。工具发布后，业务仓库需要手动升级这两个值。

## 4. 推送并查看结果

提交工作流后推送分支，或在 Actions 中手动运行 **AI Code Review**。

在 **生成中文风险报告** 步骤查看报告：

- 主模型优先，调用失败或报告格式无效时才使用备用模型。
- 有明确风险才发钉钉；无风险、只有待验证事项、审查失败都不发送。
- 钉钉通知成功以机器人返回 `errcode=0` 为准，不能只看 HTTP 成功或 CI 绿色。
- 不要通过引入漏洞或伪造风险测试通知；真实测试消息需明确授权并标注测试用途。

需要阻止合并时，还要在分支保护中将此工作流设为必需检查；它不能撤销已发生的推送。

## 能检查什么

检查本次变更中的安全、权限、逻辑、数据、并发、兼容性和稳定性风险，**不是全仓库扫描，也不能替代测试和人工审查**。

**当前不会自动读取项目说明、AGENTS 或其他规范文档。** 仅在仓库添加规范，不会让审查器自动按规范检查；文档上下文能力尚未接入。

## 使用前注意

- 代码会发送给主、备模型服务，启用前需确认允许外发；敏感文件过滤不保证源码没有密钥。
- 只允许可信人员修改和触发带 Secrets 的工作流；固定工具版本不能隔离恶意工作流。
- 只监听分支 push 和手动运行，不处理 PR 或 tag。手动运行、新分支只审最近一次提交。
- 差异有大小限制，跨文件上下文有限；排除、超限或调用失败会标明覆盖不完整，不代表安全。
- 不执行业务代码、不自动修复或合并。钉钉消息不含原始 diff，重跑可能重复通知。

开发与发布规则见 [开发指南](AGENTS.md)，版本和真实验证状态见 [交接记录](docs/handoff.md)。
