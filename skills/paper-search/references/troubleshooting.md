# 检索类命令出错时

| 场景                                         | 处理                                                                                                                                                         |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 命令不存在                                   | 提示安装 `npm install -g papersearch`，见 `management-layer.md`                                                                                         |
| API key 或 email 缺失                        | 告诉用户三件事：这个功能要哪个 key；去哪里申请（报错或 `paper-search doctor --format text` 里给的网址）；申请后在自己的终端运行 `paper-search setup <KEY>` 填入，再用 `paper-search config test <KEY>` 确认能用；装了学校订阅下载、用户就在这台电脑前时，也可以运行 `paper-search settings <KEY>` 打开设置窗口让用户填（没装或没有图形界面时它返回错误并给出终端命令）。填好后重跑原来的命令。不要让用户在聊天里发送 key，也不要保存 key |
| Google Scholar 返回 CAPTCHA/429 或异常流量页 | Scholar 是尽力而为的来源，默认 `0.5 RPS`、缓存成功结果，遇到验证页立即停止。等一段时间后用 `--platform googlescholar --max-results 1` 重试；必要时配置有授权的 `GOOGLE_SCHOLAR_PROXY_URL`。它不在 `--sources all` 默认列表中 |
| Google Scholar 仍不可用、又不想配置 key      | 用 `paper-search search "<检索词>" --sources no-key --max-results 5 --pretty`（Crossref、PubMed、Europe PMC、arXiv、OpenReview）                                  |
| 429 限流                                     | 降低 `--max-results`，换平台，或提示配置可选 key                                                                                                             |
| 0 结果                                       | 放宽关键词，换英文同义词，换平台，或用 `--sources` 扩展                                                                                                      |
| 下载失败                                     | 用统一的 `download_with_fallback` 并报告各 attempt；涉及学校权限的失败按 `browser-download.md` 的失败分类处理                                                |
| 用户要求完整正文                             | 先下载 PDF，再交给当前环境可用的 PDF/MinerU 解析流程                                                                                                         |

Scholar 相关配置：`SCHOLAR_RATE_LIMIT_RPS`（默认 `0.5`）、`SCHOLAR_MAX_RETRIES`（默认 `2`）、`SCHOLAR_TIMEOUT_MS`（默认 `15000`）。只往更保守的方向调；不要用于批量抓取或绕过验证。
