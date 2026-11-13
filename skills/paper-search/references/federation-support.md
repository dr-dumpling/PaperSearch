# 学校订阅下载：各学术身份联盟支持情况

本表说明学校订阅下载能经哪些学术身份联盟登录（截至 2026-11-12）。“支持”是说：用户说出学校名称，程序能查出学校所属的联盟，并在出版社网站上自动选好联盟和学校，走到学校的登录页。登录之后能否下到全文，取决于学校的订阅，以及出版社是否给这所学校开通了学校账号登录。

各国的学术身份联盟通过 eduGAIN 互联，出版社借此认可各国学校的账号；OpenAthens 是跨国的机构登录服务，没有加入本国联盟的学校不少经它登录。

- 配置时只需说出学校名称（中文、英文或当地语言），所属联盟由程序判断，不要问用户是哪个联盟。
- 不在下表任何联盟里、也没有接入 OpenAthens 的学校（只能用校园网、VPN 或图书馆代理访问），暂时无法使用。
- 出版社只给某校开通了 IP、VPN 或机构邮箱方式，或出版社的机构列表里没有这所学校时，程序会写明原因，不再等待。
- 用户问“我的学校能不能用”：先按本表说明学校所属的联盟是否支持，再说明具体能否下到全文要看学校订阅和出版社的开通情况；出版社一侧见 `publisher-support.md`。

符号：✓ 已实测（自动走到学校登录页）；○ 已支持，尚未实测。

## 亚洲

| 地区 | 联盟 | 全称 | 联盟内学校数 | 状态 | 已实测的学校 |
| --- | --- | --- | --- | --- | --- |
| 中国内地、澳门 | CARSI | CERNET 联邦认证与资源共享基础设施（CERNET Authentication and Resource Sharing Infrastructure） | 约 590 | ✓ | 澳门大学、澳门科技大学 |
| 香港 | HKAF | Hong Kong Access Federation | 15 | ✓ | 香港大学、香港中文大学、香港科技大学、香港理工大学 |
| 新加坡 | SGAF | Singapore Access Federation | 13 | ✓ | 新加坡国立大学、南洋理工大学、新加坡管理大学 |
| 日本 | GakuNin（学認） | 学術認証フェデレーション（Academic Access Management Federation in Japan） | 约 170 | ✓ | 东京大学、大阪大学、东北大学、庆应义塾大学、早稻田大学 |
| 韩国 | KAFE | Korean Access Federation | 27 | ✓ | KAIST、延世大学、浦项工科大学、成均馆大学 |
| 马来西亚 | SIFULAN | SIFULAN Malaysian Access Federation | 约 150 | ✓ | 马来西亚理科大学、博特拉大学 |
| 印度 | INFED | INFLIBNET Access Management Federation | 约 390 | ✓ | 印度理工学院德里分校 |
| 土耳其 | YETKİM | YETKİM Identity Federation | 约 170 | ✓ | 哈杰泰佩大学、中东技术大学、海峡大学、伊斯坦布尔大学 |
| 斯里兰卡 | LIAF | LEARN Identity Access Federation | 31 | ✓ | 科伦坡大学 |
| 孟加拉 | TIGERfed | Trust, Identity and Group management for Education and Research Federation | 30 | ✓ | 孟加拉工程技术大学 |
| 巴基斯坦 | PKIFED | Pakistan Identity Federation | 8 | ✓ | COMSATS 大学伊斯兰堡分校、巴基斯坦国立科技大学、真纳大学 |
| 阿曼 | OMREN | OMREN Identity Federation | 约 30 | ○ | — |
| 跨地区 | OpenAthens | OpenAthens 机构登录服务 | — | ✓ | 马来亚大学、朱拉隆功大学、菲律宾大学 Diliman、名古屋大学、台湾大学、阳明交通大学、台湾师范大学 |

- 联盟内学校数取自 eduGAIN 登记的身份提供方数量，一所学校可能登记不止一个。
- OpenAthens 不是某个国家的联盟，是跨国的机构登录服务；学校同时有本国联盟入口时，程序优先用联盟的。
- 台湾没有加入 eduGAIN 的联盟，台湾的学校经 OpenAthens 登录；没有接入 OpenAthens 的台湾学校暂时无法使用。
- 巴基斯坦有一百多所学校经 PERN 全国共用入口登录，联盟名单里只有它们的域名：按校名查不到时，用学校官网域名配置。
- 阿曼 OMREN 交给 eduGAIN 的学校名单目前已过期，阿曼的学校暂时查不到；名单恢复后无需改动即可使用。
- 学校登录服务器连不上，或学校认证服务器拒绝出版社的登录请求时，程序立即结束并说明“学校登录系统出错”；这类情况要由学校处理。

## 美洲

| 地区 | 联盟 | 全称 | 联盟内学校数 | 状态 | 已实测的学校 |
| --- | --- | --- | --- | --- | --- |
| 美国 | InCommon | InCommon Federation | 约 590 | ✓ | 斯坦福大学、麻省理工学院、耶鲁大学、普林斯顿大学、哥伦比亚大学、加州大学伯克利分校、加州大学洛杉矶分校、加州大学旧金山分校、密歇根大学、宾夕法尼亚大学、杜克大学、华盛顿大学、纽约大学、康奈尔大学、约翰斯·霍普金斯大学 |

## 计划中

英国（UK federation）、澳大利亚（AAF）、欧洲各国联盟，之后是 eduGAIN 里的其他国家。
