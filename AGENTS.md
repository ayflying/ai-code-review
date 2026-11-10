# 后续开发接手指南

## 先读与范围

先读 [README.md](README.md)（配置与行为）和 [docs/handoff.md](docs/handoff.md)（版本、真实验证与未完成事项），再读取目标模块及测试。不要依赖前一个聊天的口头完成声明。

本仓库是通用工具，不绑定 ad-insight。业务仓库仅放工作流，审查器从此仓库拉到 runner 临时目录；执行时当前工作目录必须仍是被审业务仓库。不要把 cwd 改到工具目录后审查工具自身。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| `changes.py` | 只读 Git 对象，确定 before..after，过滤与限制 diff |
| `providers.py` | OpenAI Responses / Claude Messages 请求、单批结构校验与主备切换 |
| `batch_review.py` | 每批规范预算、独立审查、结果去重汇总及时间启动预算 |
| `review_context.py` | 从被审提交 Git 对象读取有限文档与 Skill，不读工作区、不执行脚本 |
| `report.py` | JSON 契约与规范原文引用校验、区分明确问题/建议/待确认 |
| `notify.py` | 审查事项钉钉通知、地址校验、关键词和回执检查 |
| `run.py` | 稳定入口 v1：无参数生成报告、--policy 应用最终策略；脱敏日志与 has_risk 输出 |
| `settings.py` | 扩展 JSON 非密钥配置白名单和风险阻断策略 |
| `examples/ai-code-review.yml` | 业务接入模板、顶部配置、工具认证与版本选择、风险策略 |
| `test_*.py` | 无真实密钥/网络的独立契约测试 |

## 关键契约

- OpenAI 密钥为空：全部跳过，包括 Claude 和钉钉。
- OpenAI Responses 优先；失败/无效结构后才切 Claude 原生 Messages。发现风险本身不触发重审。
- 有效 findings（代码风险/明确违反规范）、suggestions 或 verification 任一非空都通知；建议和待确认不当作风险，不触发风险阻断。调用失败不伪装成模型结论。模型不是安全保证。
- 项目文档和 Skill 仅作为不可信规则参考，不运行其中脚本；规范问题必须引用已加载文档的路径、行号和匹配原文。
- 脚本正常返回 0；风险写到 GITHUB_OUTPUT 的 has_risk。是否失败由业务工作流最后一步按顶部开关决定，默认关闭。
- 不用 job 级 continue-on-error，否则吞掉已开启的风险阻断；报告/通知失败不能伪装为安全结论。
- 不执行业务源码、安装业务依赖、自动修复、自动合并或修改生产。
- API Key、Webhook、Git 令牌只能通过 Secrets 注入，不写源码、文档、日志、提交或普通变量。不要保存真实机器人地址。
- 不更改 actions 组织可见性来绕过跨库认证；使用任务令牌或专用最小只读 Secret。
- 不自动向群发送虚构风险做测试。真实投递需用户明确授权并区分测试内容和实际风险。
- 所有可触发带 Secrets 工作流的写入者必须可信；拉取独立工具不是完整的不可信提交隔离方案。

## 开发与验证

先检查 git status，避免混入他人改动。代码定位优先 CodeGraph，随后读源码。保持职责拆分和清晰边界注释，不复制共享实现。

```text
python -m unittest discover -s . -p "test_*.py" -v
python -m ruff check .
git diff --check
```

Windows 若无全局 Python，可使用本机现有 `D:\git\sonow\ad-insight\backend\.venv\Scripts\python.exe`，但它不是本项目运行时依赖。CI 依赖预装 Python 3.10+、Bash、Git 和网络。

测试通过不代表 Gitea 真实运行或钉钉投递通过。新行为补契约测试；工作流策略还应在真实 runner 核验。中文提交，精确暂存本次文件并 push。

## 发布规则

用户已改为一次接入、自动更新策略：业务工作流默认跟随工具 main，后续只更新本仓库代码，不为功能升级反复修改模板或业务工作流。只在必须变更 Actions 平台/运行环境/新增 Secrets 接线时才说明迁移边界，不承诺任意未来能力零迁移。

保持启动协议 v1 兼容：Python 3.10+ 标准库、run.py 无参数生成报告、run.py --policy 最终判断、has_risk 步骤输出、现有 Secrets/Variables 名称。新非密钥参数通过 AI_REVIEW_OPTIONS_JSON 白名单扩展，密钥不能走 JSON。风险策略放工具端，不能使用容错吞掉最终阻断。

标签不可覆盖或移动；为回退保留不可变发布标签。默认自动更新不再要求模板同步版本；需要锁定时由用户在后台 Variables 设置 AI_REVIEW_TOOL_REF 为发布标签。不再提供 TOOL_SHA 配置和校验，仅在日志记录实际提交 SHA。v1.2.0 及更早不支持 --policy，不能用稳定入口直接回退到这些标签。工具仓库 main 写入者必须可信，更新会直接影响接入仓库后续 CI。
