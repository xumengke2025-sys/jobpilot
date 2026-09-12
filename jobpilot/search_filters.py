"""Map preferences to observed site controls, then verify selected labels.

No BOSS selectors are guessed here. A tested adapter supplies control mappings.
Unmapped conditions are explicitly marked local-only and checked after capture.
"""
from .preferences import JOB_FIELDS, normalize_policy


def requested_filters(policy, city=None):
    p = normalize_policy(policy)
    result = {k: v for k in JOB_FIELDS if (v := p[k])}
    if city:
        if city not in p["cities"]:
            raise ValueError("搜索城市不属于期望城市")
        result["cities"] = [city]
    if p["min_monthly_salary"] or p["max_monthly_salary"] is not None:
        key = f"floor:{p['min_monthly_salary']:g}" if p["salary_mode"] == "floor" else f"overlap:{p['min_monthly_salary']:g}:{p['max_monthly_salary'] if p['max_monthly_salary'] is not None else 'any'}"
        result["salary"] = [key]
    return result


def apply_search_conditions(page, config, request, policy, strict=False):
    from .browser import check_blocked, unique
    search = config.get("search")
    if not search or not search.get("query") or not search.get("submit"):
        raise ValueError("适配器尚未配置搜索框和搜索按钮，不能模拟筛选")
    requested = requested_filters(policy, request.get("city"))
    filters = search.get("filters", {})
    planned, local_only = [], []
    # Plan and validate the whole request before touching the page.
    for field, values in requested.items():
        control = filters.get(field)
        if not control or any(v not in control.get("options", {}) for v in values) or (len(values) > 1 and not control.get("multiple")):
            local_only.append({"field": field, "values": values, "reason": "网页控件或选项映射未覆盖，需本地再筛"})
            continue
        if control.get("kind") not in ("select", "menu", "fill") or not control.get("selected"):
            raise ValueError("筛选控件配置不完整，缺少操作类型或选中回读定位")
        planned.append((field, values, control))
    if strict and local_only:
        raise ValueError("部分条件未映射到网页筛选：" + ",".join(x["field"] for x in local_only))
    if requested and not search.get("reset_filters"):
        raise ValueError("带筛选的搜索必须配置重置按钮，避免上一轮条件残留")
    check_blocked(page, config)
    if search.get("reset_filters"):
        unique(page, search["reset_filters"]).click()
    query = unique(page, search["query"])
    query.fill(request["query"])
    if query.input_value() != request["query"]:
        raise ValueError("搜索框内容未正确写入")
    unique(page, search["submit"]).click()
    applied = []
    for field, values, control in planned:
        check_blocked(page, config)
        labels = [control["options"][v] for v in values]
        if any(not isinstance(v, str) or not v for v in labels):
            raise ValueError("筛选选项映射必须为页面上实际显示的文本")
        if control["kind"] == "select":
            unique(page, control["locator"]).select_option(label=labels if control.get("multiple") else labels[0])
        elif control["kind"] == "fill":
            if len(labels) != 1:
                raise ValueError("文本筛选框只能接收一个值")
            unique(page, control["locator"]).fill(labels[0])
        else:
            for label in labels:
                unique(page, control["locator"]).click()
                unique(page, {"role": control.get("option_role", "option"), "name": label}).click()
        selected = unique(page, control["selected"])
        # Configured receipt must represent the selected labels, not the whole menu.
        actual = selected.input_value() if control.get("selected_value") else selected.inner_text()
        if any(label not in actual for label in labels):
            raise ValueError("网页没有显示预期的已选筛选条件：" + field)
        applied.append({"field": field, "requested": values, "selected": labels, "mapping": control.get("coverage", "site_band")})
    if search.get("results_ready"):
        unique(page, search["results_ready"]).wait_for(state="visible", timeout=10000)
    check_blocked(page, config)
    return {"query": request["query"], "city": request.get("city", ""), "applied": applied, "local_only": local_only,
            "note": "网页区间与个人条件可能不完全相同；采集后仍需按原始求职设置再筛。"}
