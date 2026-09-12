const $ = (id) => document.getElementById(id);
(async () => {
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (!tab?.url || !/^https?:\/\//.test(tab.url)) throw new Error('请打开招聘网站的岗位详情页');
    $('url').value = tab.url;
    const [result] = await chrome.scripting.executeScript({target: {tabId: tab.id}, func: () => window.getSelection()?.toString() || ''});
    $('description').value = result.result || '';
    if (!result.result) $('status').textContent = '尚未选中岗位描述，可直接粘贴。不会自动读取整页聊天或推荐职位。';
  } catch (error) { $('status').textContent = error.message; }
})();
$('export').addEventListener('click', () => {
  try {
    const job = {};
    for (const key of ['title','company','url','description','city']) job[key] = $(key).value.trim();
    for (const key of ['industry','company_size','funding_stage','experience_band','required_education','job_type','work_mode','work_schedule']) job[key] = $(key).value.trim();
    job.min_experience_years = $('min_experience_years').value === '' ? null : Number($('min_experience_years').value);
    for (const key of ['title','company','url','description']) if (!job[key]) throw new Error('请填写岗位名称、公司、链接和描述');
    const url = new URL(job.url);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw new Error('岗位链接格式错误');
    for (const key of ['salary_min','salary_max']) job[key] = $(key).value === '' ? null : Number($(key).value);
    if (job.salary_min !== null && job.salary_max !== null && job.salary_min > job.salary_max) throw new Error('薪资上下限颠倒');
    job.requirements = $('requirements').value.split(/[,，;；\n]/).map(s => s.trim()).filter(Boolean);
    const data = URL.createObjectURL(new Blob([JSON.stringify(job,null,2)], {type:'application/json'}));
    const a = document.createElement('a'); a.href = data; a.download = 'jobpilot-job-' + Date.now() + '.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(data), 1000);
    $('status').textContent = '已导出岗位信息。此扩展不会发送求职消息。';
  } catch(error) { $('status').textContent = error.message; }
});
