# 简历循环与求职设置（v0.2）

产品主线：求职偏好 + 已确认简历 → BOSS 搜索计划 → 真实岗位 → 岗位匹配与修改建议 → 用户确认 → 简历新版本 → 下一轮。
这个循环本身不发送求职消息，不要求先跑通全自动投递。

## 1. 设置期望条件

简单示例使用 `examples/policy.json`；完整字段见 `examples/policy.full.json`。示例值不是用户实际期望。
每轮生成的 `report.html` 内有“我的求职条件”，可以编辑后导出 `policy-next.json`。

| 条件 | 配置字段 | 本地处理 |
|---|---|---|
| 城市，可多选 | cities | 每个城市生成搜索任务；岗位 city 精确匹配 |
| 目标岗位 | target_titles | 搜索关键词与岗位名匹配 |
| 薪酬下限、上限 | min_monthly_salary / max_monthly_salary | 税前元/月，不混入年终奖 |
| 薪酬匹配方式 | salary_mode | floor：岗位起薪≥下限，不限上限；overlap：与期望区间相交 |
| 行业 | industries | 对岗位 industry 核对 |
| 公司规模 | company_sizes | 对 company_size 核对；标签要与采集值一致 |
| 融资阶段 | funding_stages | 对 funding_stage 核对 |
| 岗位经验区间 | experience_bands | 对 experience_band 核对 |
| 岗位学历要求 | education_requirements | 对 required_education 核对；另与实际学历比较 |
| 用工形式 | job_types | 例如全职/兼职/实习，对 job_type 核对 |
| 办公方式 | work_modes | 例如现场/远程/混合，对 work_mode 核对 |
| 休息安排 | work_schedules | 例如双休，对 work_schedule 核对 |
| 排除公司、内容 | excluded_companies / excluded_terms | 排除；含否定语句时可能保守误排 |
| 优先关键词 | preferred_terms | 同等支持度下优先排序，不增加能力分数 |
| 缺信息怎么办 | unknown_policy | review 待核实；exclude 排除 |

数组为空表示不限。这些设置不会修改候选人的学历或工作年限。
如果岗位提供最低工作年限和学历门槛，还会核对已确认底稿中的 `years_experience` 与 `education_level`。缺失时不能自动当作满足。
城市、行业等字段当前不做隐含同义转换，例如“上海市”和“上海”需要先统一标签。

## 2. 根据简历生成搜索计划

```bash
python -m jobpilot search-plan --profile private/profile.json --policy private/policy.json --out private/search-plan.json
```

搜索关键词来自实际经历标签和你指定的岗位，不会因为某个热门技术而把未具备的能力写入简历。
生成的网页链接只预填 query；城市等条件通过网页控件设置，不能仅凭链接认定已筛选。

## 3. 获取真实岗位

当前可用路径：在 BOSS 查看岗位，使用 `extension/` 选中 JD 导出，或整理成 JSON 后 `import-jobs`。
结构化字段如薪资、城市、行业、学历、工作方式等应如实提供；未知留空，不猜测。

```bash
python -m jobpilot import-jobs private/jobs.json
```

已有真实页面适配后可以运行：

```bash
python -m jobpilot collect-plan --profile private/profile.json --policy private/policy.json --adapter private/boss-verified.json --searches 3 --pages 1 --out private/jobs-round1.json
```

程序会重置上一轮筛选，填写搜索词，操作下拉/菜单/输入控件，回读已选条件，再采集列表。
网页不支持或尚未映射的条件会写入每个岗位的 `web_filter_receipt.local_only`，采集后本地核验。
加 `--strict-web` 时，有已设置条件不能通过网页控件应用就停止。结果会逐搜索保存，避免后续搜索失败丢失前面的数据。

**仓库内 BOSS 适配器仍是占位，未登录真实账号进行筛选验收。**不能直接运行该占位配置就声称已筛到 BOSS 岗位。
适配器 search 配置协议见 `adapters/search.example.json`，其中控件仅为协议演示，不是真实 BOSS 选择器。

## 4. 生成匹配和建议

```bash
python -m jobpilot analyze --profile private/profile.json --policy private/policy.json --top 10
```

输出 cycle_id 和 report.html。打开页面可查看：

- 所有岗位的经历支持度、表达覆盖率、证据、缺口及筛选原因。
- 前 top 个未排除岗位对应的简历预览（不会加入自动投递队列）。
- 具体表述建议、遗漏信息问题、不能靠改写补齐的经验缺口。
- 本轮的求职条件编辑器、下一轮搜索入口和历史对比。

没有 requirements 的岗位会用有限词表提取候选要求，并标为待核实；这不是完整 JD 解析。
有真实模型接口时可增加 `--ai`。最多把前5个候选岗位与已确认事实发送至你配置的接口，生成最多6条待确认草稿。
模型必须引用真实 JD 原句，不能引用不存在的经历；数字和责任升级有保守检查，但仍需人工核对含义。

## 5. 审阅修改并生成新底稿

在 HTML 中查看“原文—建议”，可修改文本，选择采纳/不采纳并勾选事实确认，导出 decisions 文件。
同一经历如果出现多份改写，本轮只采纳一份。经验缺口不能用接受建议转成技能。

```bash
python -m jobpilot revise --cycle 上一步cycle_id --profile private/profile.json --decisions private/decisions.json --out private/profile-v2.json
```

原文件不覆盖；如果底稿已经变更、建议来自其他轮次、重复确认或文件名已存在，会停止并说明原因。
新版本只修改确认过的事实文本/表达版本，保留单位、时间、职责、阶段、学历和关键词。
如果是真实新增或此前漏写的经验，请直接在底稿中补充事实并核对，不通过措辞修改伪造能力提升。

## 6. 重新匹配形成循环

```bash
python -m jobpilot analyze --profile private/profile-v2.json --policy private/policy.json --parent 上一轮cycle_id
python -m jobpilot history
```

只有岗位内容和求职条件相同的共同岗位才直接比较。改了城市、薪资或 JD，报告会明确说明不能把变化全归因于简历。
表达覆盖率只检查已有证据支持的要求是否在当前表述出现；不能通过重复关键词提高经历支持度。
确认后的新底稿仍可用于原有 `prepare` 生成岗位投递包；这一步由用户单独执行，分析循环不会自动开启投递。

## 验证情况

已跑通两个完整演示轮次：同一岗位的表达覆盖率从 75% 到 100%，经历支持度保持 100%，没有增加能力标签。
这些是虚构数据验证，不代表真实面试率提升。测试包含偏好筛选、页面控件回读模拟、版本冲突、旧建议拦截和 HTML 导出事件。
真实 BOSS 页面、模型服务及用户简历仍待接入验收。
