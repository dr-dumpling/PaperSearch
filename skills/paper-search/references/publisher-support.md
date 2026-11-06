# 机构下载：各出版社支持情况

本表只适用于机构下载（可选扩展），说明它在哪些出版社网站上能走通（截至 2026-11-05，含工作区尚未发布的适配）。“能走通”是说：用户学校订阅了这篇文章、出版社有这所学校的登录路线时，程序能自己取到本文的 PDF。学校有没有订阅，看实际的下载结果。开放获取的文章通常先由开放下载拿到，用不到这张表。

- 支持按网站算，不按期刊算：同一网站上的期刊共享规则，实际结果以目标文章为准。
- 程序按 DOI 实际跳转到的网站判断属于哪一行。DOI 前缀只是线索，期刊换了出版社时前缀不变（例如 ARD 的 `10.1136` 文章现在在 Elsevier）。
- 用户问“某本期刊能不能下”：先按这张表说明程序能不能走通，再说明学校订阅要以实际下载为准；不要凭这张表断定学校有或没有权限。

符号：✓ 实测取得；✓OA 只实测过开放获取文章；○ 已有规则，尚无文件下载成功记录；— 没有补充材料规则（返回 `supplements_not_supported`，正文不受影响）。

## 有专门规则的出版社

| 出版社 | 网站 | 常见 DOI 前缀 | 正文 | 补充材料 |
| --- | --- | --- | --- | --- |
| Elsevier | ScienceDirect（期刊文章、书籍章节） | `10.1016` | ✓ | ✓ |
| Elsevier | 期刊自有网站（cell.com、thelancet.com、gastrojournal.org、jacc.org 等） | `10.1016`、`10.1053` | ✓ | ✓ |
| ASH（Blood、Blood Advances） | ScienceDirect、ashpublications.org | `10.1182/blood.`、`10.1182/bloodadvances.` | ✓OA | ✓ |
| Wiley | onlinelibrary.wiley.com 及学会子域名（agupubs、acsjournals、physoc 等） | `10.1002`、`10.1111` | ✓ | ✓ |
| Springer Nature | SpringerLink、nature.com、BMC、SpringerOpen | `10.1007`、`10.1038`、`10.1186` | ✓ | ✓ |
| Oxford Academic（OUP） | academic.oup.com | `10.1093` | ✓ | ✓ |
| Wolters Kluwer（LWW） | Ovid、journals.lww.com | `10.1097`、`10.2106` | ✓ | ✓ |
| Taylor & Francis | tandfonline.com | `10.1080` | ✓ | ✓ |
| Sage | journals.sagepub.com | `10.1177` | ✓ | ✓ |
| NEJM | nejm.org 及 evidence、ai、catalyst 子域名 | `10.1056` | ✓ | ✓ |
| ASCE | ascelibrary.org | `10.1061` | ✓ | ✓ |
| ACS | pubs.acs.org | `10.1021` | ✓ | ✓ |
| JAMA Network | jamanetwork.com | `10.1001` | ✓OA | ✓ |
| Neurology（AAN） | neurology.org | `10.1212` | ✓OA | ✓ |
| AHA journals | ahajournals.org | `10.1161` | ✓OA | ✓ |
| Science | science.org（Science、Science Advances 等） | `10.1126` | ✓OA | ✓ |
| PNAS | pnas.org | `10.1073` | ✓ | ✓ |
| ACM Digital Library | dl.acm.org | `10.1145` | ✓ | ✓ |
| World Scientific | worldscientific.com | `10.1142` | ✓OA | ✓ |
| Karger | karger.com | `10.1159` | ✓ | ✓ |
| RSC | pubs.rsc.org | `10.1039` | ✓OA | ✓ |
| IEEE | ieeexplore.ieee.org | `10.1109` | ✓ | ✓ |
| Thieme | thieme-connect.com / .de | `10.1055` | ✓ | ✓ |
| BMJ | bmj.com 及各子刊网站 | `10.1136` | ○ | — |
| AIP Publishing | pubs.aip.org | `10.1063` | ✓OA | ✓ |
| Royal Society | royalsocietypublishing.org | `10.1098` | ✓OA | ✓ |
| APS（Physical Review） | journals.aps.org | `10.1103` | ✓OA | ✓ |
| IOP Publishing | iopscience.iop.org | `10.1088` | ✓OA | ✓ |
| Optica | opg.optica.org | `10.1364` | ✓OA | ✓ |
| Annual Reviews | annualreviews.org | `10.1146` | ✓OA | ✓ |
| AMS | journals.ametsoc.org | `10.1175` | ✓OA | ✓ |
| Dove Medical Press | dovepress.com | `10.2147` | ✓ | ✓ |
| MDPI | mdpi.com | `10.3390` | ✓OA | ✓ |
| Frontiers | frontiersin.org | `10.3389` | ✓OA | ✓ |
| PLOS、Copernicus | 各自网站 | `10.1371`、`10.5194` | ✓ | ✓ |

## 没有专门规则的网站

DOI 跳转到表外的网站时，程序按通用规则尝试：找机构登录入口、选 CARSI 和学校、取页面声明的 PDF，保存前同样核对身份。没有补充材料规则。

| 结果 | 网站 |
|---|---|
| 正文实测取得 | Cambridge University Press（cambridge.org）、American Physiological Society（journals.physiology.org）、ASM（journals.asm.org）、De Gruyter Brill（degruyterbrill.com）、ADA（diabetesjournals.org）、RSNA（pubs.rsna.org） |
| 机构列表里没有 CARSI | AACR（aacrjournals.org） |
| 找不到机构登录入口（`generic_institution_entry_missing`） | Emerald（emerald.com） |

`generic_institution_entry_missing` 归“暂不支持的网站”：告诉用户这类网站还没有规则，可以把这篇报告给维护者补规则，或在校园网下下载。

## 不支持的平台

返回 `unsupported_platform` 或 `unsupported_publisher`，不打开浏览器或很快结束：只在 ClinicalKey 上的内容；知网、万方、维普；DOI 无法解析、直接指向 PDF 文件或落到 Crossref 多重解析页。告诉用户这类来源不支持，不说成没有权限。

## 和学校有关的常见结果

这些结果说明的是“用户学校在这家出版社的情况”，不是程序故障：

- `institution_federation_unavailable`：出版社的机构列表里找不到 CARSI 或用户的学校，即这家出版社没有这所学校的登录路线。程序立即结束；建议在校园网或学校 VPN 下下载。
- `institution_not_registered`：认证应用或入口未注册，或与当前认证渠道不兼容，属于外部认证配置问题；核查入口，不把它当作学校没有论文订阅。
- `idp_no_return_to_publisher`：学校登录后停在学校自己的网站，没回到出版社，通常也是学校没开通。
- `entitlement_missing`：出版社认出了学校，判定本篇不在订阅内。只说本篇、当前学校没有权限，不推断整个出版社。
- `no_entitlement`：用户在进度窗口里标过“本刊无权限”或“出版社无权限”，之后同刊或同出版社直接跳过；查看或撤销见 `browser-download.md`。
