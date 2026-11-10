# AI Code Review

给 Gitea 仓库接入 AI 代码审查：推送后按项目文档和 Skill 规范检查代码及文件变更，输出中文报告。有问题、建议或待确认事项都会发钉钉。默认不阻断 CI，可按仓库开启。

## 1. 添加工作流

把本仓库的 [examples/ai-code-review.yml](examples/ai-code-review.yml) 文件复制到需要审查的项目中，保存为：

```text
你的项目/.gitea/workflows/ai-code-review.yml
```

如果 `.gitea/workflows` 目录不存在，先创建。源文件请使用本仓库 main 分支的版本。

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
  AI_REVIEW_BLOCK_ON_RISK: 'false'  # true：代码风险/明确违反规范时失败；建议和待确认不阻断
  # 不指定其他机器人时保留默认 Secret 引用，使用环境已配置的机器人。
  # 更换机器人只改 Secret 名称；禁止填写真实地址，清空值则不通知。
  AI_REVIEW_DINGTALK_WEBHOOK: ${{ secrets.AI_REVIEW_DINGTALK_WEBHOOK }}
  AI_REVIEW_DINGTALK_KEYWORD: 'gitea'  # 与所选机器人的安全关键词一致
  AI_REVIEW_TOOL_REF: 'v1.2.0'  # 固定工具版本，升级时与 SHA 配套修改
  AI_REVIEW_TOOL_SHA: '3c84bbbbac5c001d5415b843639d38f48ca1c8a0'  # 版本对应的完整提交 SHA
```

- **只报告**：保持 `AI_REVIEW_BLOCK_ON_RISK: 'false'`。改成 `'true'` 后，明确代码风险或违反项目规范会让任务失败；纯建议、待确认、审查或通知失败不触发风险阻断。
- **钉钉通知**：不填写其他机器人配置时，保留默认 Secret 引用即可使用环境中已配置的 `AI_REVIEW_DINGTALK_WEBHOOK`。要换机器人就引用另一个 Secret；清空值或 Secret 未配置则不通知。安全关键词默认 `gitea`，需与所选机器人一致；当前不支持加签机器人。
- **工具版本**：标签与完整 SHA 必须配套，不要改成 main/latest。工具发布后，业务仓库需要手动升级这两个值。

## 4. 推送并查看结果

提交工作流后推送分支，或在 Actions 中手动运行 **AI Code Review**。

在 **生成中文风险报告** 步骤查看报告：

- 主模型优先，调用失败或报告格式无效时才使用备用模型。
- 报告分为明确问题、改进建议、待确认事项；任一有内容都会发钉钉。全部为空或模型审查失败不发送。
- 钉钉通知成功以机器人返回 `errcode=0` 为准，不能只看 HTTP 成功或 CI 绿色。
- 不要通过引入漏洞或伪造风险测试通知；真实测试消息需明确授权并标注测试用途。

需要阻止合并时，还要在分支保护中将此工作流设为必需检查；它不能撤销已发生的推送。

## 能检查什么

检查本次变更中的安全、权限、逻辑、数据、并发、兼容性和稳定性风险，**不是全仓库扫描，也不能替代测试和人工审查**。

### 项目规范放在哪里

把规范提交到被审项目，CI 自动读取，不需要额外配置：

| 位置 | 内容 |
| --- | --- |
| 根目录 `README.md`、`AGENTS.md`、`CONTRIBUTING.md` | 项目说明和开发要求 |
| 变更文件所在目录及其上级的 `AGENTS.md`、`README.md` | 模块专用规则 |
| `.agents/skills/`、`.claude/skills/`、`.skills/`、`skills/` 下的 `SKILL.md` | 项目自带 Skill 说明 |
| `docs/` 下的 Markdown 文档 | 补充规范和设计说明 |

明确违规会附上规范路径、行号和原文；不确定或规范冲突则列为待确认。只读取被审提交中的文件，不执行 Skill 脚本，也不递归读取 Skill 引用的其他文件。

按表格顺序优先加载，最多尝试 20 份文档、每份 12KB、合计 60KB；仅支持 UTF-8 普通文件，超限整份跳过。日志列出已加载、缺失或跳过的文档，不能保证覆盖全部规范。规范和代码会一起发送给模型。

## 使用前注意

- 代码会发送给主、备模型服务，启用前需确认允许外发；敏感文件过滤不保证源码没有密钥。
- 只允许可信人员修改和触发带 Secrets 的工作流；固定工具版本不能隔离恶意工作流。
- 只监听分支 push 和手动运行，不处理 PR 或 tag。手动运行、新分支只审最近一次提交。
- 差异有大小限制，跨文件上下文有限；排除、超限或调用失败会标明覆盖不完整，不代表安全。
- 不执行业务代码、不自动修复或合并。钉钉消息不含原始 diff，重跑可能重复通知。

开发与发布规则见 [开发指南](AGENTS.md)，版本和真实验证状态见 [交接记录](docs/handoff.md)。
