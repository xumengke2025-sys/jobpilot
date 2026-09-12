# JobPilot · 简历与岗位 AI 助手

以已确认的工作经历为依据，筛选岗位、生成定制简历与招呼语，通过本机浏览器执行可追踪的投递队列。

**当前版本：0.3.0。已加入 BOSS / 猎聘分平台搜索、真实字段标准化、跨平台岗位去重和市场高频要求；两个平台的真实账号页面筛选与投递仍待验收。**
提供 Python 命令行工具、Edge/Chrome 岗位采集扩展，以及本地 HTML 建议审阅和求职设置页面，没有独立服务器后台。
没有你的真实简历，示例全部为虚构数据，不得作为真实申请材料。

## 新主线：用岗位要求改进简历

1. **设置求职条件**：平台、城市/区县、月薪/年薪/薪资月数、行业、公司规模、经验、学历、办公方式、招聘者活跃度、发布时间、福利和排除项等。
2. **根据简历找岗位**：从已确认经历和目标岗位生成 BOSS/猎聘分平台搜索组合，按城市展开；配置过页面控件后可模拟网页筛选。
3. **先筛选再诊断**：不合条件的岗位排除，未知信息转待核实；对候选岗位给出支持证据和经验缺口。
4. **针对市场和 JD 给建议**：跨平台重复职位只计一个岗位簇；先看重复出现的要求，再展示逐岗位原文、建议表述、理由与引用。
5. **确认生成新版本**：在本地审阅页编辑/选择建议，导出确认文件；源简历不覆盖。
6. **重新匹配并比较**：保留每轮岗位、条件和版本，只比较内容与规则未变的共同岗位。

这里区分“经历支持度”和“表达覆盖率”。改写能改善表达，但不会凭空增长工作能力；两种分数均不是录用概率。

不需要模型 Key 或招聘账号即可看完整演示：

```bash
python examples/demo_loop.py
```

命令会生成两轮本地报告，用的是虚构示例，不会访问 BOSS 或发送消息。实际操作见 [简历循环与求职设置说明](docs/RESUME_ASSISTANT.md)。

## 已实现与边界

| 能力 | 状态 |
|---|---|
| TXT、文本型 PDF、DOCX 原文提取 | 已实现；扫描件需先 OCR，提取后人工校对 |
| 浏览器选中岗位文本、整理并导出 JSON | 已实现；支持平台、地点细分、薪资原文、公司/招聘者字段及技能要求 |
| 按页面配置批量采集岗位列表 | 通用执行器已实现；真实站点定位器待实测 |
| 平台、城市/区县、月薪/年薪/薪资月数、行业、规模、融资、经验学历、福利、发布时间与招聘者活跃度等过滤 | 已实现；可在报告页编辑并导出下一轮设置 |
| BOSS/猎聘字段标准化与跨平台重复岗位簇 | 已实现；保留各来源链接和沟通状态，市场频次去重 |
| 多岗位市场高频要求 | 已实现；区分已写清、已有证据未写清和无证据缺口 |
| 逐项技能证据、缺口、匹配覆盖率 | 已实现；不是录用概率；不把词义相近当能力相同 |
| 按岗位选经历、排序、替换已确认表达 | 已实现；可选 OpenAI 兼容模型，默认离线规则 |
| 根据 JD 提改写建议、人工确认、新版本再匹配 | 已实现；含每轮记录和本地审阅页 |
| 模拟网页设置筛选条件 | 控件映射执行器已实现，含选中结果回读和薪资粗区间防漏选；BOSS/猎聘控件仍待真实页面验证 |
| HTML 简历预览、浏览器打印 PDF | 已实现 |
| DOCX 简历输出 | 可选依赖实现；版式需针对真实简历复核 |
| 逐岗位附件版本绑定与校验 | 已实现 DOCX；仅上传当前绑定附件 |
| 浏览器填写、上传、点击、回执检查 | 通用执行器已实现；通过模拟定位器合同测试 |
| BOSS、猎聘自动投递 | **适配文件为占位，未通过真实账号测试，不能开箱即用** |
| 跨进程岗位去重、投递过程记录、异常停机 | 已实现；结果不明不自动重试 |
| 全天后台运行、自动回 HR、新问题自动回答 | 未实现 |

## 先用演示数据跑通（无需 API Key）

安装 Python 3.11 或更新版本。下载本项目，终端进入项目目录：

```bash
python -m jobpilot import-jobs examples/jobs.json
python -m jobpilot prepare --profile examples/profile.json --policy examples/policy.json
python -m jobpilot status
```

Windows 中 `python` 不可用时可换为 `py -3`。从 prepare 输出的 `resume` 路径打开 HTML。
结果应有 1 个 matched、1 个 needs_review、1 个 rejected。
演示链接使用 `.invalid` 域名，不会产生实际申请。

## 安装可选能力

建议使用虚拟环境：

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS/Linux 使用 source .venv/bin/activate
python -m pip install -e ".[browser,documents]"
python -m playwright install chromium
```

生成 Word 简历：

```bash
python -m jobpilot prepare --profile private/profile.json --policy private/policy.json --docx
```

## 处理自己的简历

1. 把真实文件放 `private/`，不要放进 `examples/`。
2. 提取原文：`python -m jobpilot extract private/resume.pdf --out private/resume.txt`。
3. 参照 `examples/profile.json` 整理底稿，核对工作单位、职位、时间、事实与项目阶段。
4. 每条事实分配稳定 ID；只给已经确认的能力加 `keywords`。
5. `approved_variants` 放你认可的同义改写。模型只能选原文或这些版本，无法自行编造改写。
6. 将 `confirmed` 设为 true，表明底稿已经人工核对。

项目阶段：`production` 已落地、`pilot` 试点、`prototype` 原型、`research` 研究规划。
完整工作时间线保存在 `employment`，项目优先级可调整，任职时间不改。
没有数字成果就不补数字，没有实际使用过技术就不加该关键词。

## 收集岗位

### 无需适配站点：浏览器采集扩展

1. Edge 扩展管理页打开开发人员模式，点击“加载解压缩的扩展”，选择本项目 `extension/` 文件夹。
2. 打开真实岗位详情页，选中岗位描述，点击 JobPilot 扩展。
3. 填写并核对平台、岗位名、公司名、城市/区县、页面薪资原文、经验学历、招聘者类型/活跃度及 requirements。`20-30K·13薪` 可保留原文，程序会解析周期和薪资月数。
4. 导出 JSON，然后运行 `python -m jobpilot import-jobs 下载的岗位文件.json`。

该扩展只读取你选中的文本与当前链接，不读取 Cookie、不访问后台接口、不发送消息。
不同岗位分别导入，或合并为 JSON 数组。岗位 ID 会移除平台已知的导航跟踪参数；公司、岗位名、城市和 JD 原文均一致时生成保守的跨平台岗位簇，但各平台链接和沟通记录分别保留。

### 自动采集：需先验证页面配置

参照 `adapters/example-ats.json` 的 collect 配置提供列表卡片、岗位链接、详情字段与翻页按钮定位器。

```bash
python -m jobpilot login https://www.zhipin.com/
python -m jobpilot collect "真实搜索结果链接" --adapter private/boss-verified.json --pages 1 --out private/jobs.json
```

程序仅从当前可见页面读取内容。城市/薪资未知不猜测，采集后需要核对 requirements 与结构化字段，再导入。
登录在本机独立浏览器内手动完成，不向聊天发送密码、验证码或 Cookie。

## 岗位匹配与定制

复制 `examples/policy.json` 到 `private/policy.json` 并填写平台、城市、最低月薪、目标职位、排除公司。
月薪过滤按招聘区间的**下限**比较；不把上限视为承诺待遇。年薪、日薪、时薪不会被静默换算成月薪；只有页面明确写出“13薪”等月数时才生成对应年薪区间。
默认 score 是岗位 requirements 中有经历关键词支持的覆盖率。
岗位 `min_experience_years`、`required_education` 与简历 `years_experience`、`education_level` 可进行结构化核验；未提供或无法识别时转待核实。采集文本仍需核对完整性。
`excluded_terms` 是保守字符串过滤，含否定语句的岗位可能被误排，需要检查结果。

每个投递包包括：

- `resume.html`：针对岗位排序的简历；可浏览器打印为 PDF。
- `resume.docx`：启用 `--docx` 后生成。
- `greeting.txt`：由岗位名和已确认经历组成的开场白。
- `match.json`：覆盖率、匹配证据与缺口。
- `bundle.json`：岗位、底稿摘要哈希、筛选条件哈希、附件哈希。

模型可选。在 PowerShell 中设置自己的接口，不把真实 Key 写入仓库：

```powershell
$env:JOBPILOT_API_BASE="https://api.deepseek.com"
$env:JOBPILOT_API_KEY="你在本机填写的密钥"
$env:JOBPILOT_MODEL="deepseek-chat"
python -m jobpilot prepare --profile private/profile.json --policy private/policy.json --ai --docx
```

`--ai` 会把经历事实（含组织/项目名称）和岗位描述发往你指定的模型接口；姓名、联系方式不包含在模型请求中。
AI 返回未经允许的经历、关键词或版本编号时生成失败，不降级成随意改写。
`prepare --ai` 只选择已确认表达；`analyze --ai` 可提出新的改写草稿，但只有通过 `revise` 确认后才进入新版底稿。

## 自动投递

**BOSS、猎聘适配器目前留空，需要有登录账号后的页面验证。**
这不是安装步骤遗漏。验证码、附件选择、沟通跳转等不同账号/页面可能不同，不能靠猜 CSS 就宣称支持。
适配完成需满足：

1. identity 定位到当前岗位的准确公司名和岗位名，不使用整页“包含”判断。
2. 填写/上传仅引用当前 bundle 中的 greeting 和绑定的 resume.docx。
3. 点击前后的聊天目标一致；聊天页切换时需针对该站点增加目标复核。
4. 有可见回执，并明确它代表 contacted、message_sent、attachment_sent 还是 submitted。
5. stop_when_visible 覆盖登录失效、验证码、操作频繁、平台限制。
6. 完成真实页面验证后才设置 verified=true。仅修改布尔值不能完成适配。

先执行只读核对（不填写、不上传、不点击）：

```bash
python -m jobpilot run --adapter private/boss-verified.json --limit 3
```

准备好实际材料与范围后，在本机明确执行一个批次：

```bash
python -m jobpilot run --adapter private/boss-verified.json --limit 3 --daily-limit 10 --execute
```

参数 3 和 10 是本地运行上限，不是平台保证额度。遇到异常整个批次停止。
不要同时运行 boss-helper 的自动发送和本项目执行器，否则两个工具之间无法共享去重记录。
不建议同时启动多个批次；每岗位有原子领取，每日上限目前按启动时事件数核算。

状态按平台区分。BOSS 的 contacted、message_sent、attachment_sent 分别表示进入目标会话、发出本次消息和发出对应附件；猎聘还可使用 submitted 表示看到本次投递成功回执。两者均可继续记录 replied、interview、offer、rejected、closed。
uncertain 代表结果不确定，不是发送失败，不会自动再次发送。用 `events JOB_ID` 核对经过，再查看平台实际记录。
此版未提供一键重置不确定任务，防止误操作重复申请。

```bash
python -m jobpilot status --csv output/applications.csv
python -m jobpilot events 岗位ID
```

## 与 boss-helper 的关系

本项目参考其分步筛选和招呼语流程，但没有复制代码或私有接口调用。
它可作为独立的 BOSS 沟通工具；本项目补充简历事实底稿、版本绑定和真实状态记录。
当前**没有**自动同步两个工具的投递历史或直接控制 boss-helper。
不把 boss-helper 的“建立沟通成功”当作“附件已发送”。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖事实真实性约束、过滤、HTML 转义、原子领取、重复执行、错公司、旧回执、未知发送结果。
浏览器测试使用模拟定位器，不代表 BOSS/猎聘线上端到端测试通过。平台字段和流程依据见 [BOSS直聘与猎聘的平台行为模型](docs/PLATFORM_BEHAVIOR.md)。

## GitHub 上线

建议新建私有仓库 `jobpilot`，不勾选 README、license 或 .gitignore。
上传本项目源代码，真实材料、output、data、browser-profile 和 .env 均已忽略。

```bash
git init -b main
git add .
git commit -m "Initial JobPilot implementation"
git remote add origin https://github.com/你的用户名/jobpilot.git
git push -u origin main
```

也可使用 GitHub CLI：`gh repo create jobpilot --private --source=. --remote=origin --push`。
仓库创建与推送使用你自己的 GitHub 登录；项目不收集 GitHub Token。
