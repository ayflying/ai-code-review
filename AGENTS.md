# 后续开发接手指南

## 先读与范围

先读 [README.md](README.md)（配置与行为）和 [docs/handoff.md](docs/handoff.md)（版本、真实验证与未完成事项），再读取目标模块及测试。不要依赖前一个聊天的口头完成声明。

本仓库是通用工具，不绑定 ad-insight。业务仓库仅放工作流，审查器从此仓库拉到 runner 临时目录；执行时当前工作目录必须仍是被审业务仓库。不要把 cwd 改到工具目录后审查工具自身。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| `changes.py` | 只读 Git 对象，确定 before..after，过滤与限制 diff |
| `providers.py` | OpenAI Responses / Claude Messages 请求、主备切换 |
| `report.py` | JSON 风险契约校验、Markdown 渲染，不猜关键词 |
| `notify.py` | 仅风险钉钉通知、地址校验、关键词和回执检查 |
| `run.py` | 编排、脱敏日志、临时报告、has_risk 步骤输出 |
| `examples/ai-code-review.yml` | 业务接入模板、顶部配置、工具认证与固定版本校验、风险策略 |
| `test_*.py` | 无真实密钥/网络的独立契约测试 |

## 关键契约

- OpenAI 密钥为空：全部跳过，包括 Claude 和钉钉。
- OpenAI Responses 优先；失败/无效结构后才切 Claude 原生 Messages。发现风险本身不触发重审。
- 有效 findings 非空才通知；仅待验证事项、调用失败不当作风险。模型不是安全保证。
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

标签不可覆盖或移动。先提交工具实现、测试并创建新版本标签；拿到完整 SHA 后再更新 main 上模板顶部的标签与 SHA、文档及业务仓库工作流。不要只更新标签不改 SHA，也不要追随 main/latest。

工具发布不会自动升级业务仓库；后续只改业务策略参数不需要改工具，但新增工具能力需要显式升级版本。首次发布标签中的模板可能仍指向旧版，接入优先使用 main 中已补齐 SHA 的模板；详见交接文档。
