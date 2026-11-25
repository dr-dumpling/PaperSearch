# School subscription downloads: academic identity federation support

This table says through which academic identity federations school subscription downloads can sign in (as of 2026-11-14). "Supported" means: when the user names the school, the program can find the school's federation, choose the federation and the school on the publisher's site automatically, and reach the school's login page. Whether the full text can be downloaded after sign-in depends on the school's subscriptions, and on whether the publisher has enabled school-account login for this school.

The academic identity federations of each country are interconnected through eduGAIN, through which publishers accept the accounts of schools in each country; OpenAthens is a cross-national institutional login service, through which many schools that are not in their national federation sign in.

- When configuring, only the school name is needed (in Chinese, English or the local language); the program works out the federation; do not ask the user which federation it is.
- Schools in none of the federations below and not connected to OpenAthens (with access only through the campus network, a VPN or a library proxy) cannot use it for now.
- When a publisher has enabled only IP, VPN or institutional email access for a school, or its institution list lacks this school, the program states the reason and does not wait.
- When the user asks "can my school use it": first say from this table whether the school's federation is supported, then that whether the full text can be downloaded depends on the school's subscriptions and on what the publisher has enabled; for the publisher side, see `publisher-support.md`.

Symbols: ✓ tested (reaches the school login page automatically); ○ supported, not tested yet.

Listed by continent and region: Asia (East Asia, Southeast Asia, South Asia, Central Asia, West Asia) → Europe (Western, Northern, Central, Southern and Eastern Europe) → the Americas (North America; Latin America and the Caribbean) → Oceania → Africa.

## Asia

### East Asia

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| China mainland, Macao | CARSI | CERNET 联邦认证与资源共享基础设施（CERNET Authentication and Resource Sharing Infrastructure） | about 590 | ✓ | 澳门大学, 澳门科技大学 |
| Hong Kong | HKAF | Hong Kong Access Federation | 15 | ✓ | 香港大学, 香港中文大学, 香港科技大学, 香港理工大学 |
| Japan | GakuNin（学認） | 学術認証フェデレーション（Academic Access Management Federation in Japan） | about 170 | ✓ | 东京大学, 大阪大学, 东北大学, 庆应义塾大学, 早稻田大学 |
| South Korea | KAFE | Korean Access Federation | 27 | ✓ | KAIST, 延世大学, 浦项工科大学, 成均馆大学 |
| China mainland (research institutes) | CSTCloud | 中国科技云联盟（CSTCloud Federation） | 10 | ✓ | 中国科学院上海应用物理研究所 (via the CSTCloud passport), 北京协和医学院 (via PUMC's unified identity authentication) |

- CSTCloud (中国科技云联盟) serves research institutes and similar institutions in China mainland; schools that are also in CARSI sign in through CARSI. For research institutes that sign in through a shared entry, give both the institution's name and its website domain when configuring.
- Taiwan has no federation in eduGAIN; schools in Taiwan sign in through OpenAthens; schools in Taiwan that are not connected to OpenAthens cannot use it for now.

### Southeast Asia

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| Singapore | SGAF | Singapore Access Federation | 13 | ✓ | 新加坡国立大学, 南洋理工大学, 新加坡管理大学 |
| Malaysia | SIFULAN | SIFULAN Malaysian Access Federation | about 150 | ✓ | 马来西亚理科大学, 博特拉大学 |

- Schools in Thailand, the Philippines and elsewhere mostly sign in through OpenAthens (see "Cross-regional"); Thailand's federation ThaiIDF has only two national entries, and the list it gives eduGAIN has expired for now, so it is not supported yet.

### South Asia

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| India | INFED | INFLIBNET Access Management Federation | about 390 | ✓ | 印度理工学院德里分校 |
| Sri Lanka | LIAF | LEARN Identity Access Federation | 31 | ✓ | 科伦坡大学 |
| Bangladesh | TIGERfed | Trust, Identity and Group management for Education and Research Federation | 30 | ✓ | 孟加拉工程技术大学 |
| Pakistan | PKIFED | Pakistan Identity Federation | 8 | ✓ | COMSATS 大学伊斯兰堡分校, 巴基斯坦国立科技大学, 真纳大学 |

- Over a hundred schools in Pakistan sign in through PERN's shared national entry, and the federation list has only their domains: when the school name finds nothing, configure it with both the school name and the school website's domain.

### Central Asia

No usable federation yet: Kyrgyzstan's KRENA has only one account entry of the federation's own and no school entries; Tajikistan's federation is not formally running yet; Kazakhstan and Uzbekistan have no federation.

### West Asia

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| Turkey | YETKİM | YETKİM Identity Federation | about 170 | ✓ | 哈杰泰佩大学, 中东技术大学, 海峡大学, 伊斯坦布尔大学 |
| Saudi Arabia | Maeen | Maeen Identity Federation | 36 | ○ | — |
| Cyprus | CyNet | CyNet Identity Federation | 10 | ✓ | 塞浦路斯大学, 塞浦路斯技术大学 |
| Israel | IUCC | IUCC Identity Federation | 1 shared entry | ✓ | 特拉维夫大学, 希伯来大学 |
| Iran | IRFED | IRFED | 2 | ○ | — |
| Azerbaijan | AzScienceNet | AzScienceNet Identity Federation | 2 | ○ | — |
| Oman | OMREN | OMREN Identity Federation | about 30 | ○ | — |

- Israel's universities sign in through IUCC's shared entry, and the federation list has only their domains: give both the school name and the school website's domain when configuring.
- Saudi universities can be chosen automatically on publisher sites, but in tests from abroad, some schools' login servers could not be reached and some schools had not enabled the publisher, so no login page for entering an account has been reached yet.
- The federations of Iran and Azerbaijan each have only one school; publishers have not necessarily enabled federation login for these schools; the program states the reason.
- The school list that Oman's OMREN gives eduGAIN has expired for now, so Omani schools cannot be found at the moment; once the list is restored, they work with no change.
- The federations of Armenia and Georgia list only the entries of network operators, research institutes and libraries, with no school entries; Lebanon's federation is not formally running yet.

## Europe

### Western Europe

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| United Kingdom | UK federation | UK Access Management Federation | about 690 | ✓ | 牛津大学, 剑桥大学, 帝国理工学院, 伦敦大学学院, 伦敦国王学院, 爱丁堡大学, 伦敦政治经济学院 |
| Ireland | Edugate | Edugate | 41 | ✓ | 都柏林圣三一学院, 都柏林大学 |
| France | RENATER | Fédération Éducation-Recherche | about 310 | ✓ | 巴黎西岱大学, 巴黎-萨克雷大学, 斯特拉斯堡大学 |
| Netherlands | SURFconext | SURFconext | about 200 | ✓ | 阿姆斯特丹大学, 莱顿大学, 乌得勒支大学, 代尔夫特理工大学 |
| Belgium | Belnet | Belnet Federation | 58 | ✓ | 根特大学, 鲁汶天主教大学, 布鲁塞尔自由大学 |
| Luxembourg | eduID Luxembourg | eduID Luxembourg | 12 | ✓ | 卢森堡大学 |

- Dutch schools all sign in through SURFconext's central hub; the program passes through it automatically.
- Schools in France, the Netherlands and Belgium can be configured with their local-language names; when a publisher finds nothing under one name, the program searches again with the school's other names.

### Northern Europe

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| Denmark (incl. Iceland, Greenland) | WAYF | WAYF – Where Are You From | 71 | ✓ | 哥本哈根大学, 奥胡斯大学, 丹麦技术大学, 冰岛大学 |
| Sweden | SWAMID | Swedish Academic Identity Federation | 53 | ✓ | 卡罗林斯卡学院, 隆德大学, 乌普萨拉大学, 瑞典皇家理工学院 |
| Finland | Haka | Haka Identity Federation | 40 | ✓ | 阿尔托大学, 坦佩雷大学 |
| Norway | Feide | Feide | 1 national entry | ○ | — |

- Danish schools all sign in through WAYF's hub; the program passes through it automatically.
- Norwegian schools all sign in through Feide's shared national entry, and the federation list has only the schools' domains: give both the school name and the school website's domain when configuring. Elsevier offers Norwegian universities IP access only, and the institution lists of Springer Nature and Oxford University Press lack Feide; the program states the reason; IOP lists several "Feide" entries of the same name through OpenAthens, and the user chooses one.
- 坦佩雷大学 is listed together with 坦佩雷应用科学大学 as "Tampere Universities" in the federation list; when the school name finds nothing, add the website domain when configuring.

### Central Europe

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| Germany | DFN-AAI | DFN-AAI（德国科研网身份联盟） | about 390 | ✓ | 慕尼黑大学, 慕尼黑工业大学, 海德堡大学, 柏林夏里特医学院, 柏林洪堡大学 |
| Switzerland | Switch edu-ID | Switch edu-ID（SWITCHaai） | 63 | ✓ | 苏黎世联邦理工学院, 苏黎世大学, 洛桑联邦理工学院, 日内瓦大学 |
| Austria | ACOnet | ACOnet Identity Federation | 84 | ✓ | 维也纳大学, 维也纳技术大学 |
| Poland | PIONIER.Id | PIONIER.Id | 93 | ✓ | 华沙大学, 雅盖隆大学, 华沙理工大学 |
| Czechia | eduID.cz | eduID.cz | about 220 | ✓ | 布拉格查理大学, 马萨里克大学, 布拉格捷克理工大学 |
| Slovakia | safeID | safeID | 33 | ✓ | 布拉迪斯拉发考门斯基大学, 斯洛伐克理工大学 |
| Hungary | eduId.hu | eduId.hu | 81 | ✓ | 罗兰大学, 塞梅尔维斯大学, 德布勒森大学 |

- Most Swiss schools sign in through Switch edu-ID, whose school login page is on the edu-ID site; the program recognizes it as usual.

### Southern Europe

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| Spain | SIR | Servicio de Identidad de RedIRIS | about 180 | ✓ | 马德里康普顿斯大学, 巴塞罗那大学, 马德里自治大学, 瓦伦西亚大学 |
| Portugal | RCTSaai | RCTSaai | about 110 | ✓ | 里斯本大学, 波尔图大学, 科英布拉大学 |
| Italy | IDEM | IDEM GARR AAI | about 170 | ✓ | 博洛尼亚大学, 罗马第一大学, 米兰大学, 帕多瓦大学 |
| Greece | GRNET | GRNET AAI Federation | 53 | ✓ | 雅典国立卡波迪斯特里亚大学, 塞萨洛尼基亚里士多德大学, 雅典国立理工大学 |
| Malta | RiċerkaNET | RiċerkaNET Identity Federation | 1 | ✓ | 马耳他大学 (Cambridge University Press) |
| Slovenia | ArnesAAI | ArnesAAI | 21 | ✓ | 卢布尔雅那大学, 马里博尔大学 |
| Croatia | AAI@EduHr | AAI@EduHr | 1 national entry | ✓ | 萨格勒布大学 (Springer Nature, via the national entry) |
| Serbia | iAMRES | iAMRES | 19 | ✓ | 诺维萨德大学, 贝尔格莱德大学化学学院 |
| Montenegro | IDeduME | IDeduME | 3 | ✓ | 黑山大学 (Cambridge University Press) |
| North Macedonia | AAIEduMk | AAIEduMk | 4 | ✓ | 斯科普里圣西里尔和美多德大学 |
| Albania | RASH | RASH | 2 | ○ | — |
| Bulgaria | BIF | Bulgarian Identity Federation | 21 | ○ | — |
| Romania | RoEduNetID | RoEduNetID | 24 | ✓ | 布加勒斯特大学, 雅西大学 |

- Spanish schools all sign in through SIR's hub; the program passes through it automatically.
- Croatian schools all sign in through the shared national entry AAI@EduHr: give both the school name and the school website's domain when configuring.
- 贝尔格莱德大学 has no university-wide login entry; each faculty is listed separately; when configuring, the program lists the faculties for the user to choose.
- 马耳他大学, 萨格勒布大学, 地拉那大学, 索非亚大学, 索非亚技术大学: Elsevier offers them IP access only; the program states the reason; 黑山大学 has only its staff entry registered in eduGAIN, and Elsevier's institution list lacks it. 马耳他大学 and 黑山大学 on Cambridge University Press, and 萨格勒布大学 on Springer Nature, reach the school login page.
- Albania, Bulgaria: besides Elsevier, six more publishers were tried; Springer Nature's institution list lacks the schools of these two countries, and the others showed a human-verification page on the test computer or did not select the school, so the school login page has not been reached yet.

### Eastern Europe

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| Estonia | TAAT | TAAT | 13 | ✓ | 塔尔图大学, 塔林理工大学 |
| Latvia | LAIFE | Latvian Academic Identity Federation | 19 | ✓ | 拉脱维亚大学 |
| Lithuania | LITNET FEDI | LITNET FEDI | 22 | ✓ | 维尔纽斯大学, 考纳斯理工大学, 立陶宛健康科学大学 |
| Belarus | FEBAS | FEBAS | 3 | ○ | — |
| Ukraine | PEANO | PEANO | 8 | ✓ | 切尔诺夫策国立大学, 哈尔科夫理工学院 |
| Moldova | LEAF | LEAF | 4 | ○ | — |

- More than ten schools in Latvia (including 里加理工大学 and 里加斯特拉金什大学) sign in through LAIFE's shared entry: give both the school name and the school website's domain when configuring; Elsevier offers these two IP access only.
- 塔林理工大学 is written "TalTech" in the federation list; it can be found by this short name or by the old domain `ttu.ee`.
- The login server of 白俄罗斯国立大学 cannot be reached from abroad; the program ends at once and says "学校登录系统出错" (School login error); 摩尔多瓦国立大学 has IP access only on Elsevier, and can be selected on Cambridge University Press, but in tests the school-selection page did not accept the choice, so the school login page has not been reached yet.

## The Americas

### North America

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| United States | InCommon | InCommon Federation | about 590 | ✓ | 斯坦福大学, 麻省理工学院, 耶鲁大学, 普林斯顿大学, 哥伦比亚大学, 加州大学伯克利分校, 加州大学洛杉矶分校, 加州大学旧金山分校, 密歇根大学, 宾夕法尼亚大学, 杜克大学, 华盛顿大学, 纽约大学, 康奈尔大学, 约翰斯·霍普金斯大学 |
| Canada | CAF | Canadian Access Federation（Fédération canadienne d'accès） | 108 | ✓ | 多伦多大学, 不列颠哥伦比亚大学, 阿尔伯塔大学, 滑铁卢大学, 麦吉尔大学 (IEEE), 麦克马斯特大学 (IEEE), 渥太华大学 (IEEE) |

- The Americas and Oceania were tested on Springer Nature, except where noted in brackets: on the test computer, Elsevier showed a human-verification page as soon as an article opened.
- 渥太华大学 signs in on IEEE through its login page on OpenAthens; the program recognizes it as usual.

### Latin America and the Caribbean

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| Mexico | FENIX | Federación Nacional de Identidades Mexicanas | 5 | ✓ | 科利马大学 |
| Brazil | CAFe | Comunidade Acadêmica Federada | about 340 | ✓ | 圣保罗大学, 坎皮纳斯州立大学, 里约热内卢联邦大学, 米纳斯吉拉斯联邦大学, 南大河州联邦大学 |
| Chile | COFRe | Comunidad Federada REUNA | 11 | ○ | — |
| Colombia | COLFIRE | COLFIRE（RENATA 身份联盟） | 2 | ○ | — |
| Ecuador | MINGA | MINGA（CEDIA 身份联盟） | 85 | ○ | — |

- The federation lists of Brazil and Ecuador put an abbreviation before the school name or a code after it: when configuring, give the school name (in the local language) and the English name; the program searches publishers with them.
- 墨西哥国立自治大学 appears in the list only as "UNAM": configure it with this short name or the school website's domain. 瓦尔帕莱索天主教大学 has separate entries for staff and for students, and 圣保罗州立大学 is written in full in the list; ask the user to confirm when configuring.
- 智利天主教大学, 塔尔卡大学, 佩雷拉技术大学, the schools of Ecuador, 墨西哥国立自治大学, 瓜达拉哈拉大学: the institution lists of Springer Nature and IEEE lack them; ACS showed a human-verification page on the test computer, or its institution list lacks them too; Cambridge University Press did not reach the school-selection page in tests. The school login page has not been reached yet.
- The Caribbean has no federation; Costa Rica's federation is not formally running yet; the Latin American regional federation FIEL lists only RedCLARA's own entry, with no school entries.

## Oceania

### Australia and New Zealand

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| Australia | AAF | Australian Access Federation | 40 | ✓ | 墨尔本大学, 悉尼大学, 澳大利亚国立大学, 昆士兰大学, 莫纳什大学, 新南威尔士大学, 西澳大学 |
| New Zealand | Tuakiri | Tuakiri New Zealand Access Federation | 17 | ✓ | 奥克兰大学, 奥塔哥大学, 惠灵顿维多利亚大学, 坎特伯雷大学 |

- AAF gives only some of its members to eduGAIN; schools not given cannot be found, and the program says this school may not be connected to an academic identity federation. 阿德莱德大学 is listed under its new name after the merger, "Adelaide University"; when the old name finds nothing, add the school website's domain when configuring.
- 悉尼大学 lists only the library's OpenAthens entry on Springer Nature, and sign-in goes to the school's login page on OpenAthens; the program recognizes it as usual.
- Several New Zealand schools have login pages hosted by Tuakiri; the program recognizes them as usual.
- Melanesia, Micronesia and Polynesia have no federation.

## Africa

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| Uganda | RIF | RENU Identity Federation | about 480 | ○ | — |
| Kenya | RAFIKI | Kenyan Identity Federation - RAFIKI | 7 | ○ | — |
| Tanzania | TERNET IF | TERNET Identity Federation | 15 | ○ | — |
| Malawi | MAREN | MAREN Identity Federation | 11 | ○ | — |
| Zambia | FIDERN | FIDERN | 3 | ○ | — |
| Nigeria | NgRENID | NgREN Identity Federation | 60 | ○ | — |
| Ghana | GARNET | GARNET Identity Federation | 20 | ○ | — |
| Burkina Faso | eduID.bf | Burkina Faso Identity Federation | 13 | ○ | — |
| Togo | eduID.tg | eduID.tg | 11 | ○ | — |
| Morocco | eduIDM | eduIDM.ma | 6 | ○ | — |
| South Africa | SAFIRE | South African Identity Federation | 35 | ○ | — |

- The African federations are supported but not tested yet: schools can be found by name, but whether the school login page can be reached on publisher sites has not been tried.
- South African schools all sign in through SAFIRE's hub; the program passes through it automatically.
- Moroccan schools are listed in the federation list by abbreviation (UIT, UM5, etc.) and Arabic name, and French school names find nothing: configure them with the abbreviation or the school website's domain.
- The school list that Malawi's MAREN gives eduGAIN does not pass validation at present, so Malawian schools cannot be found for now; once the list is restored, they work with no change.
- The federations of Ethiopia, Somalia and Algeria list only the entries of network operators or research institutions, with no school entries; the list of Nigeria's other federation, eduID.ng, cannot be fetched; the regional federation eduID.africa has only one school; the federations of Botswana, Mali and Mozambique are not formally running yet.

## Cross-regional

| Region | Federation | Full name | Schools in federation | Status | Schools tested |
| --- | --- | --- | --- | --- | --- |
| Cross-regional | OpenAthens | OpenAthens 机构登录服务 | — | ✓ | 马来亚大学, 朱拉隆功大学, 菲律宾大学 Diliman, 名古屋大学, 台湾大学, 阳明交通大学, 台湾师范大学 |

- OpenAthens is not a country's federation but a cross-national institutional login service; when a school also has an entry in its national federation, the program uses the federation's first.

## Notes

- The number of schools in a federation is the number of identity providers registered in eduGAIN; one school may register more than one.
- When the school login server cannot be reached, or the school's authentication server refuses the publisher's login request, the program ends at once and says "学校登录系统出错" (School login error); the school has to fix this.
- When the school login server has not registered this publisher (the page shows Unsupported Request, Metadata not found, etc.), the program ends at once and says the school has not enabled this publisher.

## When school login fails

- First tell the user truthfully the reason the program gives (how to handle each reason: see `browser-download.md` and `school-setup.md`). When the publisher has enabled only IP, VPN or institutional email access for this school, or its institution list lacks this school, the school or the publisher has to enable it; nothing can be changed on the program's side.
- Ask the user for feedback in these cases, so the maintainers can add federations or fix rules: the school cannot be found when configuring, or the reply is `federation_not_supported`; the school's federation is supported, but a download did not reach the school login page (it stopped on the publisher's school-selection page, chose another school, or the school login page was not recognized); and the actual results with federations marked "○" in this table: success or failure, both are welcome.
- How to give feedback: open an Issue on GitHub with the "学校登录不上 / 想支持我的学校 · School sign-in problem or school request" template (`https://github.com/dr-dumpling/PaperSearch/issues/new?template=school-login.yml`), stating the school's name and website domain, the country or region, and the program's reply when configuring; when sign-in fails, also the publisher, the DOI of an article the user has access to, the page where it stopped, and the reason the program gave. The user may attach a failure record package they have checked (`paper-search failures --export ./failure-report.zip --doi <DOI>`).
- Never ask the user for their account, password, student number or verification code, and do not put addresses with login parameters, cookies or raw diagnostic files into the feedback.
