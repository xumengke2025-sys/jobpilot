# 简历循环与求职设置（v0.3）

产品主线：求职偏好 + 已确认简历 → BOSS/猎聘分平台搜索计划 → 真实岗位 → 去重后的市场要求与逐岗位匹配 → 修改建议 → 用户确认 → 简历新版本 → 下一轮。
这个循环本身不发送求职消息，不要求先跑通全自动投递。

## 1. 设置期望条件

简单示例使用 `examples/policy.json`；完整字段见 `examples/policy.full.json`。示例值不是用户实际期望。
每轮生成的 `report.html` 内有“我的求职条件”，可以编辑后导出 `policy-next.json`。

| 条件 | 配置字段 | 本地处理 |
|---|---|---|
| 平台 | platforms | `boss`、`liepin`；为空时搜索计划同时生成两类任务，匹配时不限制来源 |
| 城市、区域/商圈 | cities / districts | 每个平台、每个城市生成搜索任务；岗位字段分别核对 |
| 目标岗位 | target_titles | 搜索关键词与岗位名匹配 |
| 月薪下限、上限 | min_monthly_salary / max_monthly_salary | 税前元/月；日薪、时薪、年薪不转换为月薪 |
| 年薪下限、薪资月数 | min_annual_salary / min_salary_months | 只有页面明确年薪或“13薪”等月数时判断，未知转待核实 |
| 薪酬匹配方式 | salary_mode | floor：岗位起薪≥下限，不限上限；overlap：与期望区间相交 |
| 行业 | industries | 对岗位 industry 核对 |
| 公司规模 | company_sizes | 对 company_size 核对；标签要与采集值一致 |
| 融资阶段 | funding_stages | 对 funding_stage 核对 |
| 岗位经验区间 | experience_bands | 对 experience_band 核对 |
| 岗位学历要求 | education_requirements | 对 required_education 核对；另与实际学历比较 |
| 用工形式 | job_types | 例如全职/兼职/实习，对 job_type 核对 |
| 办公方式 | work_modes | 例如现场/远程/混合，对 work_mode 核对 |
| 休息安排 | work_schedules | 例如双休，对 work_schedule 核对 |
| 企业性质、招聘者类型 | company_natures / recruiter_types | 区分企业 HR、Boss 与猎头；未知不猜测 |
| 必须福利 | required_benefits | 岗位福利全部包含时通过；字段缺失转待核实 |
| 发布时间、招聘者活跃度 | max_job_age_days / max_recruiter_inactive_days | 使用采集到的明确日期或天数；不从模糊宣传文字猜测 |
| 仍在招聘 | active_jobs_only | `true` 时暂停/关闭岗位排除，未知转待核实 |
| 风险信号 | exclude_risk_flags | 可选择 `fee`、`training_loan`、`financial_task`、`off_platform_contact`、`pyramid_scheme`；默认仅提示复核 |
| 高频要求门槛 | market_min_jobs | 至少多少个去重岗位簇出现才称为高频，默认 2 |
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
生成结果按平台和城市拆分，每个任务都带 `interaction_model`、操作回执说明和逐项筛选覆盖范围。BOSS 链接可预填 query；猎聘入口可能需要页面执行器填写关键词。城市等条件通过已验证网页控件设置，不能仅凭链接认定已筛选。

## 3. 获取真实岗位

当前可用路径：在 BOSS 或猎聘查看岗位，使用 `extension/` 选中 JD 导出，或整理成 JSON 后 `import-jobs`。
扩展会根据域名预选平台，并允许记录区县/商圈、页面薪资原文、薪资月数、企业信息、学历经验、福利、招聘者身份/活跃度、发布日期和岗位状态。未知留空，不猜测。

```bash
python -m jobpilot import-jobs private/jobs.json
```

已有真实页面适配后可以运行：

```bash
python -m jobpilot collect-plan --profile private/profile.json --policy private/policy.json --adapter private/boss-verified.json --searches 3 --pages 1 --out private/jobs-boss-round1.json
python -m jobpilot collect-plan --profile private/profile.json --policy private/policy.json --adapter private/liepin-verified.json --searches 3 --pages 1 --out private/jobs-liepin-round1.json
```

程序只执行与适配器 `platform` 相同的搜索任务。它会重置上一轮筛选，填写搜索词，操作下拉/菜单/输入控件，回读已选条件，再采集列表。
网页不支持或尚未映射的条件会写入每个岗位的 `web_filter_receipt.local_only`，采集后本地核验。
如果实现精确薪酬条件需要同时选择多个网页区间，但该控件只能单选，程序会跳过网页薪酬筛选，避免漏掉仍符合要求的更高薪职位。
加 `--strict-web` 时，有已设置条件不能通过网页控件应用就停止。结果会逐搜索保存，避免后续搜索失败丢失前面的数据。

**仓库内 BOSS 和猎聘适配器仍是占位，未登录真实账号进行筛选验收。**不能直接运行占位配置就声称已经筛到真实岗位。
适配器 search 配置协议见 `adapters/search.example.json`，其中控件和薪资区间仅为协议演示，不是真实平台选择器。

## 4. 生成匹配和建议

```bash
python -m jobpilot analyze --profile private/profile.json --policy private/policy.json --top 10
```

输出 cycle_id 和 report.html。打开页面可查看：

- 所有岗位的经历支持度、表达覆盖率、证据、缺口及筛选原因。
- 来源平台、薪资原文/周期、地点细分、字段完整度、风险复核信号和跨平台重复岗位簇。
- 按去重岗位簇计算的高频要求：已写清、已有证据但表述不明显、现有底稿无证据。
- 前 top 个未排除岗位对应的简历预览（不会加入自动投递队列）。
- 具体表述建议、遗漏信息问题、不能靠改写补齐的经验缺口。
- 本轮的求职条件编辑器、下一轮搜索入口和历史对比。

没有 requirements 的岗位会用有限词表提取候选要求，并标为待核实；这不是完整 JD 解析。重复发布在市场频次中只计一次，但两条来源记录不会合并，因此 BOSS 沟通和猎聘投递仍能分别追踪。
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
61 项测试已覆盖分平台搜索、平台来源绑定、薪资周期与月数、统招学历核对、网页薪资区间防漏选、跨平台岗位簇和市场频次。
真实 BOSS/猎聘登录页面、模型服务及用户简历仍待接入验收。平台依据与边界见 [平台行为模型](PLATFORM_BEHAVIOR.md)。
