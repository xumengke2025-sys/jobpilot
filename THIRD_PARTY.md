# 参考项目与依赖

- [Ocyss/boss-helper](https://github.com/Ocyss/boss-helper)，检查版本 `09df246`。
  参考岗位筛选、AI 评分、招呼语与日志的工作流程。本项目没有复制其源码、私有 API 调用、聊天协议或图片资源。
  上游 README 对用途另有说明，若将来直接复用代码，需再次核对许可。
- [Microsoft Playwright](https://github.com/microsoft/playwright)，浏览器自动化依赖，Apache-2.0。
- [python-docx](https://github.com/python-openxml/python-docx)，可选 DOCX 导出依赖，MIT。
- [pypdf](https://github.com/py-pdf/pypdf)，可选 PDF 文本提取依赖，BSD-3-Clause。

上述依赖安装时保留各自许可。本源码包不包含第三方依赖或浏览器二进制。
页面操作遵循 Playwright 官方 [输入操作文档](https://playwright.dev/python/docs/input)；会话隔离参考 [认证文档](https://playwright.dev/python/docs/auth)。
