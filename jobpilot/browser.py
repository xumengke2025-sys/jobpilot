"""Local visible-browser runner. No private APIs or CAPTCHA bypass.

Site selector configs are supplied after live-page validation. Shipped BOSS and
Liepin configs are deliberately marked unverified, not advertised as working.
"""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .core import digest, read_json, validate_job


def guard_url(url, config):
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or p.hostname not in config["allowed_hosts"]:
        raise ValueError("页面已离开适配器允许的域名，停止操作")


def locate(page, spec):
    if not isinstance(spec, dict):
        raise ValueError("缺少定位配置")
    if "css" in spec:
        return page.locator(spec["css"])
    if "role" in spec:
        return page.get_by_role(spec["role"], name=spec["name"], exact=True)
    if "label" in spec:
        return page.get_by_label(spec["label"], exact=True)
    raise ValueError("定位配置需要 css、role/name 或 label")


def unique(page, spec):
    loc = locate(page, spec)
    loc.wait_for(state="attached", timeout=10000)
    if loc.count() != 1:
        raise ValueError("页面元素不唯一，停止而不是选择第一个")
    return loc


def check_blocked(page, config):
    guard_url(page.url, config)
    for spec in config.get("stop_when_visible", []):
        loc = locate(page, spec)
        if loc.count() and loc.first.is_visible():
            raise ValueError("出现登录、验证或平台限制，需要人工处理")


def validate_adapter(c):
    if not c.get("allowed_hosts") or not c.get("identity"):
        raise ValueError("适配器必须有域名白名单与岗位身份定位")
    steps = c.get("steps", [])
    for i, s in enumerate(steps):
        if s.get("op") not in ("fill", "upload", "click", "verify"):
            raise ValueError("不支持的页面操作")
        if not s.get("locator"):
            raise ValueError("操作缺少定位器")
        if s["op"] in ("fill", "upload") and s.get("source") not in ("greeting", "resume.docx", "resume.pdf"):
            raise ValueError("只能填写或上传当前岗位绑定的内容")
        if s["op"] == "upload" and s["source"] == "greeting":
            raise ValueError("上传操作必须选择简历附件")
        if s["op"] == "verify":
            if s.get("state") not in ("contacted", "message_sent", "attachment_sent", "submitted"):
                raise ValueError("回执状态不合法")
            if not s.get("contains"):
                raise ValueError("回执必须检查内容")
    if not steps or steps[-1]["op"] != "verify":
        raise ValueError("投递流程必须以页面回执检查结束")


def receipt_text(step, bundle):
    value = step["contains"]
    return bundle["greeting"] if value == "$greeting" else value


def run_one(page, config, bundle, directory, store, execute=False):
    validate_adapter(config)
    job, jid = bundle["job"], bundle["job"]["id"]
    guard_url(job["url"], config)
    if execute and config.get("verified") is not True:
        raise ValueError("该平台适配器未经页面验证，不能执行投递")
    if execute and bundle["assessment"]["status"] != "matched":
        raise ValueError("该岗位没有通过筛选")
    page.goto(job["url"], wait_until="domcontentloaded", timeout=30000)
    check_blocked(page, config)
    for field in ("company", "title"):
        actual = unique(page, config["identity"][field]).inner_text().strip()
        if actual != job[field].strip():
            raise ValueError(f"{field} 与投递目标不一致")
    # Read-only mode does not even populate fields; filling/uploading can auto-save.
    if not execute:
        return {"status": "preview", "job_id": jid, "steps": config["steps"]}
    # Validate every attachment before any field entry or other side effect.
    for s in config["steps"]:
        if s["op"] == "upload":
            path = Path(directory) / s["source"]
            expected = bundle.get("attachment_hashes", {}).get(s["source"])
            if not expected or not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("附件缺失或与绑定版本不一致，请重新生成投递包")
    store.claim(jid)
    mutated = False
    try:
        # Old success banners or previously sent messages must never count as this run's receipt.
        for s in config["steps"]:
            if s["op"] == "verify":
                loc = locate(page, s["locator"])
                if loc.count() == 1 and loc.is_visible() and receipt_text(s, bundle) in loc.inner_text():
                    raise ValueError("已存在同内容回执，停止以避免重复发送")
        for index, s in enumerate(config["steps"]):
            check_blocked(page, config)
            loc = unique(page, s["locator"])
            if s["op"] == "verify":
                # Poll the visible receipt, not the click promise or a private API response.
                expected = receipt_text(s, bundle)
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    check_blocked(page, config)
                    if loc.is_visible() and expected in loc.inner_text():
                        break
                    page.wait_for_timeout(250)
                else:
                    raise ValueError("未看到对应内容的页面回执")
                store.event(jid, s["state"], f"步骤 {index+1}：页面回执已核对")
                continue
            # Write ahead of each side effect. A crash is not treated as permission to retry.
            store.event(jid, "uncertain", f"步骤 {index+1} 即将执行 {s['op']}，未核对回执")
            mutated = True
            if s["op"] == "fill":
                if s["source"] != "greeting":
                    raise ValueError("填写只能使用招呼语")
                loc.fill(bundle["greeting"])
            elif s["op"] == "upload":
                path = Path(directory) / s["source"]
                expected = bundle.get("attachment_hashes", {}).get(s["source"])
                if not expected or not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError("附件缺失或与绑定版本不一致，请重新生成投递包")
                loc.set_input_files(str(path.resolve()))
            else:
                loc.click()
        return {"status": store.application(jid)["status"], "job_id": jid}
    except Exception:
        store.event(jid, "uncertain" if mutated else "needs_review", "页面操作中止；请检查事件记录与实际聊天，不自动重试")
        raise


def login(url, profile_dir):
    from playwright.sync_api import sync_playwright
    if urlsplit(url).scheme != "https":
        raise ValueError("请使用平台 HTTPS 登录地址")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(Path(profile_dir).resolve()), headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(url)
            input("请在本机浏览器完成登录，然后回到终端按回车保存会话并关闭浏览器：")
        finally:
            ctx.close()


def collect(url, config, profile_dir, pages=1, search_request=None, policy=None, strict_filters=False):
    """Read public/authorized visible job pages. No hidden endpoint scraping."""
    from playwright.sync_api import sync_playwright
    guard_url(url, config)
    if not 1 <= pages <= 20:
        raise ValueError("本次读取页数应在 1 到 20 之间")
    c = config.get("collect")
    if not c:
        raise ValueError("该适配器尚未配置岗位列表采集；可用扩展或 JSON 导入")
    results = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(Path(profile_dir).resolve()), headless=False)
        try:
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded")
            filter_receipt = None
            if search_request is not None:
                from .search_filters import apply_search_conditions
                filter_receipt = apply_search_conditions(page, config, search_request, policy or {}, strict_filters)
            for n in range(pages):
                check_blocked(page, config)
                cards = page.locator(c["card_css"])
                cards.first.wait_for(state="visible")
                urls = []
                for card in cards.all():
                    href = card.locator(c["link_css"]).get_attribute("href")
                    from urllib.parse import urljoin
                    if href:
                        urls.append(urljoin(page.url, href))
                for href in urls:
                    guard_url(href, config)
                    detail = ctx.new_page()
                    try:
                        detail.goto(href, wait_until="domcontentloaded")
                        check_blocked(detail, config)
                        job = {key: unique(detail, spec).inner_text().strip() for key, spec in c["detail"].items()}
                        from .preferences import parse_monthly_salary
                        salary_min, salary_max = parse_monthly_salary(job.get("salary_text", ""))
                        job.update(url=detail.url, requirements=[], salary_min=salary_min, salary_max=salary_max)
                        if filter_receipt is not None:
                            job["web_filter_receipt"] = filter_receipt
                        job = validate_job(job)
                        results[job["id"]] = job
                    finally:
                        detail.close()
                if n + 1 < pages:
                    unique(page, c["next"]).click()
                    page.wait_for_timeout(2000)
        finally:
            ctx.close()
    return list(results.values())


def execute_queue(store, config, profile_dir, limit=5, daily_limit=10, execute=False):
    from playwright.sync_api import sync_playwright
    if not 1 <= limit <= 50 or not 1 <= daily_limit <= 50:
        raise ValueError("批次和每日上限应在 1 到 50 之间；这不是平台承诺额度")
    validate_adapter(config)
    if execute and config.get("verified") is not True:
        raise ValueError("适配器尚未验证，禁止实际发送")
    today = datetime.now(timezone.utc).date().isoformat()
    used = store.db.execute("SELECT COUNT(*) FROM events WHERE status='running' AND created_at LIKE ?", (today + "%",)).fetchone()[0]
    if execute:
        limit = min(limit, max(0, daily_limit - used))
    queue = [r for r in store.applications() if r["status"] == "matched"]
    results = []
    if not limit:
        return results
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(Path(profile_dir).resolve()), headless=False)
        try:
            page = ctx.new_page()
            for row in queue:
                bundle = read_json(row["bundle_path"])
                if digest(bundle) != row["bundle_hash"]:
                    raise ValueError("投递包发生变更，需要重新生成")
                if urlsplit(bundle["job"]["url"]).hostname not in config["allowed_hosts"]:
                    continue
                results.append(run_one(page, config, bundle, Path(row["bundle_path"]).parent, store, execute))
                if len(results) >= limit:
                    break
                if execute:
                    page.wait_for_timeout(max(10, config.get("interval_seconds", 15)) * 1000)
        finally:
            ctx.close()
    return results
