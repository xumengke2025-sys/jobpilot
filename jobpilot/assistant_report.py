"""Self-contained local review page. Exports decisions; never transmits resumes."""
import html
import json


def preferences_form(policy):
    from .preferences import LIST_FIELDS
    e = lambda value: html.escape(str(value), quote=True)
    fields = "".join(f'<label>{e(label)}（逗号分隔）<input data-policy="{key}" value="{e(", ".join(policy.get(key, [])))}"></label>' for key, label in LIST_FIELDS.items())
    floor_selected = "selected" if policy["salary_mode"] == "floor" else ""
    overlap_selected = "selected" if policy["salary_mode"] == "overlap" else ""
    review_selected = "selected" if policy["unknown_policy"] == "review" else ""
    exclude_selected = "selected" if policy["unknown_policy"] == "exclude" else ""
    checked = "checked" if policy.get("active_jobs_only") else ""
    optional = lambda key: e(policy.get(key) if policy.get(key) is not None else "")
    return f'''<h2>我的求职条件</h2><details><summary>查看或修改城市、薪酬及其他条件</summary><p>此处显示本轮使用的设置。修改后导出设置文件，再用于下一轮搜索和分析；本页已有结果不会被改写。</p><div class="preferences">{fields}
<label>期望月薪下限（税前元/月）<input id="policy-min" type="number" min="0" value="{policy['min_monthly_salary']}"></label>
<label>期望月薪上限（未知可留空）<input id="policy-max" type="number" min="0" value="{e(policy.get('max_monthly_salary') if policy.get('max_monthly_salary') is not None else '')}"></label>
<label>期望年薪下限（税前元/年，0 表示不限）<input id="policy-annual" type="number" min="0" value="{policy.get('min_annual_salary', 0)}"></label>
<label>最低薪资月数（例如 13；可留空）<input id="policy-months" type="number" min="1" max="24" value="{optional('min_salary_months')}"></label>
<label>岗位最长发布天数（可留空）<input id="policy-age" type="number" min="0" value="{optional('max_job_age_days')}"></label>
<label>招聘者最长未活跃天数（可留空）<input id="policy-inactive" type="number" min="0" value="{optional('max_recruiter_inactive_days')}"></label>
<label>市场高频要求最少岗位簇数<input id="policy-market-min" type="number" min="1" max="50" value="{policy.get('market_min_jobs', 2)}"></label>
<label>薪酬筛选方式<select id="policy-salary-mode"><option value="floor" {floor_selected}>岗位起薪不低于下限（不限制上限）</option><option value="overlap" {overlap_selected}>岗位区间与期望区间有重叠</option></select></label>
<label>关键信息未知时<select id="policy-unknown"><option value="review" {review_selected}>转为待核实</option><option value="exclude" {exclude_selected}>排除</option></select></label>
<label>最低经历支持度（0—100）<input id="policy-score" type="number" min="0" max="100" value="{policy['min_score']}"></label>
<label class="confirm"><input id="policy-active" type="checkbox" {checked}> 只保留确认仍在招聘的岗位</label></div>
<p>空白表示不限。经验区间是岗位筛选条件，不会修改你的实际工作年限。优先关键词只用于同分排序。</p><button id="download-policy">导出下一轮求职设置</button><p id="policy-message" role="status"></p></details>'''


def render_report(r):
    e = lambda value: html.escape(str(value), quote=True)
    jobs = {j["job"]["id"]: j for j in r["jobs"]}
    labels = {"matched": "建议关注", "needs_review": "待核实", "rejected": "已排除"}
    rows = []
    for row in r["jobs"]:
        job, a, expression = row["job"], row["assessment"], row["expression"]
        evidence = "；".join(k + " → " + ", ".join(v) for k, v in a["evidence"].items()) or "暂无"
        missing = "、".join(a["missing"]) or "暂无已识别缺口"
        reasons = "；".join(a["unknown"] + a["rejected_reasons"])
        preview = f'<a href="{e(row["resume_preview"])}" target="_blank" rel="noopener">查看该岗位简历</a>' if row.get("resume_preview") else ""
        expr = "—" if expression["score"] is None else str(expression["score"]) + "%"
        source = "候选词，待核对" if row["requirements_origin"] == "inferred_partial" else "导入的岗位要求"
        place = " · ".join(v for v in (job.get("city"), job.get("district"), job.get("business_district")) if v) or "城市未知"
        salary = job.get("salary_text") or (f'{job.get("salary_min", 0):g}–{job.get("salary_max", 0):g} 元/月' if job.get("salary_min") is not None and job.get("salary_max") is not None else "薪资未知")
        platform = {"boss": "BOSS直聘", "liepin": "猎聘", "other": "其他来源"}.get(job.get("source_platform"), job.get("source_platform", "其他来源"))
        risks = "；".join(flag["label"] for flag in job.get("risk_flags", []))
        quality = f'字段完整度 {row.get("completeness", {}).get("score", 0)}%'
        rows.append(f'<tr><td><a href="{e(job["url"])}" target="_blank" rel="noopener noreferrer">{e(job["title"])}</a><small>{e(platform)} · {e(job["company"])} · {e(place)}</small><small>{e(salary)} · {e(job.get("experience_band") or "经验未知")} · {e(job.get("required_education") or "学历未知")}</small>{preview}</td><td>{a["score"]}%<small>{e(source)} · {e(quality)}</small></td><td>{expr}</td><td>{labels[a["status"]]}<small>{e(reasons)}</small>{f"<small class='risk'>风险复核：{e(risks)}</small>" if risks else ""}</td></tr><tr class="detail"><td colspan="4"><b>匹配证据：</b>{e(evidence)}<br><b>缺口：</b>{e(missing)}</td></tr>')
    cards = []
    for s in r["suggestions"]:
        job = jobs[s["job_id"]]["job"]
        kind = {"rewrite": "表达修改", "clarify": "补充说明", "gap": "经验缺口"}[s["kind"]]
        quote = f'<blockquote>岗位原句：{e(s["requirement_quote"])}</blockquote>' if s["requirement_quote"] else ""
        if s["kind"] == "gap":
            editor = '<p class="notice">这项不能通过改写获得。若确有遗漏经历，请在底稿里单独补充并核对。</p>'
            options = '<option value="">暂不处理</option><option value="reject">记录为不采纳</option>'
        else:
            editor = f'<div class="versions"><div><label>当前表述</label><p class="before">{e(s["before"])}</p></div><div><label for="text-{s["id"]}">建议表述（可编辑）</label><textarea id="text-{s["id"]}" rows="5">{e(s["after"])}</textarea></div></div><label class="confirm"><input type="checkbox" id="confirm-{s["id"]}"> 我确认修改符合实际经历，未增加能力、责任或成果</label>'
            options = '<option value="">暂不处理</option><option value="accept">采纳此修改</option><option value="reject">不采纳</option>'
        ai = "AI 草稿，待核对" if s["source"] == "ai_draft" else "已确认表述" if s["source"] == "approved_variant" else "规则诊断"
        scope = f'高频要求：{s.get("market_cluster_count", 1)}/{s.get("market_total_clusters", 0)} 个岗位簇' if s.get("scope") == "recurring" else "单岗位要求，谨防过度改写"
        cards.append(f'<article data-id="{s["id"]}"><div class="cardtop"><span class="tag">{kind}</span><small>{ai} · {e(s["fact_id"] or "无对应经历")} · {e(scope)}</small></div><h3>{e(job["title"])} · {e(job["company"])}</h3><p>{e(s["reason"])}</p>{quote}<p>{e(s["question"])}</p>{editor}<label>本条处理方式 <select id="action-{s["id"]}">{options}</select></label></article>')
    search = "".join(f'<li><span class="tag">{e(q["platform_name"])}</span><a href="{e(q["url"])}" target="_blank" rel="noopener noreferrer">{e(q["query"])}</a><small>{e(q.get("city") or "城市不限")} · 依据 {e(", ".join(q["evidence_ids"]))}</small><small>网页可缩小 {sum(x["coverage"].startswith("site") for x in q["filters"])} 项；本地复核 {sum(x["coverage"] != "site_exact" for x in q["filters"])} 项</small></li>' for q in r["search_plan"]["queries"])
    market_labels = {"expressed": "已有证据且已写清", "supported_hidden": "已有证据但表述不明显", "gap": "现有底稿无证据"}
    market_rows = "".join(f'<tr><td>{e(item["term"])}</td><td>{item["verified_cluster_count"]} 个已核对 / {item["cluster_count"]} 个识别</td><td>{e("、".join(item["platforms"]))}</td><td>{e(market_labels[item["state"]])}</td></tr>' for item in r["market"]["recurring_requirements"])
    market_table = f'<table><thead><tr><th>高频要求</th><th>岗位簇</th><th>来源</th><th>简历状态</th></tr></thead><tbody>{market_rows}</tbody></table>' if market_rows else '<p>当前没有足够已核对岗位达到高频门槛；保留单岗位诊断，但不据此批量堆关键词。</p>'
    platform_notes = "".join(f'<li><b>{e(item["name"])}</b>：{e(item["action_note"])}</li>' for item in r["search_plan"]["platforms"])
    comparison = '<p>这是第一轮。确认修改后，以本轮作为 parent 再分析，可对比相同岗位上的变化。</p>'
    if r["comparison"]:
        c = r["comparison"]
        cr = "".join(f'<tr><td>{e(x["title"])}</td><td>{x["capability_before"]}% → {x["capability_after"]}%</td><td>{e(x["expression_before"])} → {e(x["expression_after"])}</td></tr>' for x in c["comparable_jobs"])
        comparison = f'<p>{e(c["note"])}</p><table><thead><tr><th>共同岗位</th><th>经历支持度</th><th>表达覆盖率（%）</th></tr></thead><tbody>{cr}</tbody></table><p>因岗位或规则变化而不直接比较：{len(c["changed_job_or_policy"])} 个。</p>'
    payload = json.dumps({"cycle_id": r["id"], "profile_hash": r["profile_hash"], "suggestions": [{"id": s["id"], "kind": s["kind"], "fact_id": s["fact_id"]} for s in r["suggestions"]]}, ensure_ascii=False).replace("<", "\\u003c")
    script = """
document.getElementById('download-policy').addEventListener('click', () => {
  try {
    const p = {};
    document.querySelectorAll('[data-policy]').forEach(input => {
      p[input.dataset.policy] = input.value.split(/[,，;；\\n]/).map(v=>v.trim()).filter(Boolean);
    });
    p.min_monthly_salary = Number(document.getElementById('policy-min').value);
    const max = document.getElementById('policy-max').value;
    p.max_monthly_salary = max === '' ? null : Number(max);
    p.min_annual_salary = Number(document.getElementById('policy-annual').value);
    const months = document.getElementById('policy-months').value;
    p.min_salary_months = months === '' ? null : Number(months);
    const age = document.getElementById('policy-age').value;
    p.max_job_age_days = age === '' ? null : Number(age);
    const inactive = document.getElementById('policy-inactive').value;
    p.max_recruiter_inactive_days = inactive === '' ? null : Number(inactive);
    const marketMin = document.getElementById('policy-market-min').value;
    p.market_min_jobs = marketMin === '' ? 2 : Number(marketMin);
    p.active_jobs_only = document.getElementById('policy-active').checked;
    p.min_score = Number(document.getElementById('policy-score').value);
    p.salary_mode = document.getElementById('policy-salary-mode').value;
    p.unknown_policy = document.getElementById('policy-unknown').value;
    if (!Number.isFinite(p.min_monthly_salary) || p.min_monthly_salary < 0 || !Number.isFinite(p.min_annual_salary) || p.min_annual_salary < 0 || !Number.isFinite(p.min_score) || p.min_score < 0 || p.min_score > 100 || !Number.isInteger(p.market_min_jobs) || p.market_min_jobs < 1 || p.market_min_jobs > 50 || (p.max_monthly_salary !== null && (!Number.isFinite(p.max_monthly_salary) || p.max_monthly_salary < p.min_monthly_salary)) || (p.min_salary_months !== null && (!Number.isInteger(p.min_salary_months) || p.min_salary_months < 1 || p.min_salary_months > 24))) throw new Error('请检查薪酬区间、样本门槛和分数。');
    const url=URL.createObjectURL(new Blob([JSON.stringify(p,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='policy-next.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    document.getElementById('policy-message').textContent='已导出设置。下一轮用 --policy 指定这个文件。';
  } catch(error) {document.getElementById('policy-message').textContent=error.message;}
});
const data = JSON.parse(document.getElementById('review-data').textContent);
document.getElementById('download').addEventListener('click', () => {
  const decisions = [], facts = new Set();
  try {
    for (const s of data.suggestions) {
      const action = document.getElementById('action-' + s.id).value;
      if (!action) continue;
      const d = {suggestion_id:s.id, action};
      if (action === 'accept') {
        if (facts.has(s.fact_id)) throw new Error('同一经历请选择一条改写，其余暂不处理。');
        facts.add(s.fact_id);
        const confirmed = document.getElementById('confirm-' + s.id).checked;
        const text = document.getElementById('text-' + s.id).value.trim();
        if (!confirmed || !text) throw new Error('请填写改写并勾选事实确认。');
        Object.assign(d, {confirmed, text});
      }
      decisions.push(d);
    }
    if (!decisions.length) throw new Error('请至少处理一条建议。');
    const blob = new Blob([JSON.stringify({cycle_id:data.cycle_id, profile_hash:data.profile_hash, decisions}, null, 2)], {type:'application/json'});
    const url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = 'decisions-' + data.cycle_id + '.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    document.getElementById('message').textContent = '确认文件已导出。运行 revise 生成新简历，再运行 analyze 开始下一轮。';
  } catch(error) { document.getElementById('message').textContent = error.message; }
});
"""
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>JobPilot · 简历与岗位诊断</title>
<style>
:root{{color-scheme:light}}*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f1;color:#24372f;font:15px/1.7 system-ui,'Microsoft YaHei',sans-serif}}main{{max-width:1100px;margin:auto;padding:42px 28px 110px}}h1{{font-size:32px;margin:8px 0}}h2{{font-size:22px;margin-top:36px}}h3{{font-size:17px}}a{{color:#236959}}small{{display:block;color:#66736c;font-size:12px}}.eyebrow{{letter-spacing:2px;color:#4c7464}}.summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:12px;margin:26px 0}}.summary div,article{{background:#fff;border:1px solid #dfe5db;border-radius:12px;padding:20px}}.summary b{{display:block;font-size:30px}}.notice{{background:#e8eee4;padding:12px 16px;border-radius:7px}}.risk{{color:#9a4c2f}}table{{border-collapse:collapse;width:100%;background:white}}th,td{{text-align:left;padding:14px;vertical-align:top;border-bottom:1px solid #e2e7df}}th{{font-size:13px;color:#607565}}.detail td{{font-size:13px;background:#fafbf8;padding-top:0}}article{{margin:16px 0}}.cardtop{{display:flex;gap:12px;align-items:center}}.tag{{display:inline-block;background:#e7efe8;border-radius:20px;padding:3px 12px;font-size:12px;margin-right:6px}}.versions{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}textarea{{width:100%;font:inherit;border:1px solid #bdccc1;border-radius:8px;padding:12px;resize:vertical}}.before{{background:#f3f5f1;padding:12px;border-radius:8px;white-space:pre-wrap}}label{{font-size:13px}}.confirm{{display:block;margin:12px 0}}select{{padding:8px;border:1px solid #bdccc1;border-radius:6px;background:white}}blockquote{{border-left:3px solid #8bac97;margin:12px 0;padding-left:14px;color:#53675a}}.search{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;list-style:none;padding:0}}.search li{{border-left:2px solid #aac2b1;padding-left:12px}}footer{{position:sticky;bottom:0;background:#f3f5f1ed;border-top:1px solid #dce3d7;padding:15px 28px;text-align:center}}button{{background:#275f4c;color:white;border:0;border-radius:7px;padding:12px 24px;font:inherit;cursor:pointer}}#message{{font-size:13px;margin:6px 0}}@media(max-width:700px){{main{{padding:24px 14px}}.versions{{grid-template-columns:1fr}}.summary{{grid-template-columns:repeat(2,1fr)}}.search{{grid-template-columns:1fr}}table{{font-size:12px}}td,th{{padding:8px}}}}
</style><main><span class="eyebrow">JOBPILOT / RESUME ASSISTANT</span><h1>用岗位要求，检查简历怎么改</h1><p>{e(r['profile']['name'])} · 分析轮次 {e(r['id'])}</p>
<p class="notice">本页使用已导入的岗位。经历支持度依据已确认能力，表达覆盖率检查这些能力是否写清楚；两者都不是录用概率。所有修改待你确认。</p>
<div class="summary"><div><small>已分析岗位</small><b>{r['summary']['total']}</b></div><div><small>建议关注</small><b>{r['summary']['matched']}</b></div><div><small>待核实</small><b>{r['summary']['needs_review']}</b></div><div><small>已排除</small><b>{r['summary']['rejected']}</b></div><div><small>风险待核查</small><b>{r['summary']['risk_flagged']}</b></div><div><small>重复岗位簇</small><b>{r['summary']['duplicate_clusters']}</b></div></div>
{preferences_form(r['policy'])}<style>.preferences{{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:16px 0}}.preferences input,.preferences select{{display:block;width:100%;padding:9px;border:1px solid #bdccc1;border-radius:6px;font:inherit;background:white}}details{{background:white;padding:16px;border:1px solid #dfe5db;border-radius:10px}}summary{{cursor:pointer}}@media(max-width:700px){{.preferences{{grid-template-columns:1fr}}}}</style>
<h2>平台流程差异</h2><ul>{platform_notes}</ul>
<h2>跨岗位市场信号</h2><p>{e(r['market']['note'])} 当前样本：{r['market']['candidate_jobs']} 个候选岗位、{r['market']['distinct_job_clusters']} 个去重岗位簇；高频门槛为 {r['market']['minimum_clusters']} 个岗位簇。</p>{market_table}
<h2>下一轮去哪里找</h2><p>{e(r['search_plan']['note'])}</p><ul class="search">{search}</ul>
<h2>哪些岗位值得关注</h2><table><thead><tr><th>岗位与公司</th><th>经历支持度</th><th>表达覆盖率</th><th>处理建议</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>具体修改建议</h2>{''.join(cards) or '<p>暂无可改写项。若尚无岗位，请先导入真实岗位；已有描述充分时，不为制造建议而改写。</p>'}
<h2>与上一轮相比</h2>{comparison}
<p>本页不会修改源简历，也不会向招聘者发送消息。确认文件仅保存在本机；原简历与每轮报告保留。</p></main>
<footer><button id="download">导出本轮修改确认</button><p id="message" role="status">选择建议、编辑表述并确认事实，再导出。</p></footer>
<script type="application/json" id="review-data">{payload}</script><script>{script}</script></html>'''
