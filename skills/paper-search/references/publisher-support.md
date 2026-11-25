# School download: publisher support

The "Full text" and "Supplementary files" columns of this table apply only to the school download (school subscription downloads): they say on which publisher sites it works (as of 2026-11-08). "Works" means: when the user's school subscribes to the article and the publisher has a login route for this school, the program can get this article's PDF by itself. Whether the school subscribes is shown by the actual download result. Open-access articles are usually got first by open download and do not need this table.

- Support is per site, not per journal: journals on one site share its rules; the actual result depends on the target article.
- The program decides the row by the site the DOI actually redirects to. A DOI prefix is only a clue: when a journal changes publisher, its prefix stays the same (for example, ARD's `10.1136` articles are now on Elsevier).
- When the user asks "can journal X be downloaded": first say from this table whether the program can work through it, then say that the school's subscription is decided by the actual download; do not conclude from this table that the school has or lacks access.

Symbols: ✓ tested and got; ✓OA tested only with open-access articles; ○ has rules, but no successful file download on record yet; — no dedicated supplementary-file rules: the general rules fetch the files in the article page's supplementary section whose addresses contain this article's DOI; when none are got, it returns `supplements_not_supported`, and the full text is not affected.

## Publishers with dedicated rules

| Publisher | Site | Common DOI prefixes | Full text | Supplementary files |
| --- | --- | --- | --- | --- |
| Elsevier | ScienceDirect (journal articles, book chapters) | `10.1016` | ✓ | ✓ |
| Elsevier | Journals' own sites (cell.com, thelancet.com, ard.eular.org, oarsijournal.com, gastrojournal.org, jacc.org, etc.) | `10.1016`, `10.1053` | ✓ | ✓ |
| ASH (Blood, Blood Advances, etc.) | ScienceDirect, ashpublications.org | `10.1182` (`10.1182/blood.`, `10.1182/bloodadvances.` via Elsevier) | ✓OA | ✓ |
| Wiley | onlinelibrary.wiley.com and society subdomains (agupubs, acsjournals, physoc, etc.) | `10.1002`, `10.1111` | ✓ | ✓ |
| Springer Nature | SpringerLink, nature.com, BMC, SpringerOpen | `10.1007`, `10.1038`, `10.1186` | ✓ | ✓ |
| Oxford Academic (OUP) | academic.oup.com | `10.1093` | ✓ | ✓ |
| Wolters Kluwer (LWW) | Ovid, journals.lww.com | `10.1097`, `10.2106` | ✓ | ✓ |
| Taylor & Francis | tandfonline.com | `10.1080` | ✓ | ✓ |
| Sage | journals.sagepub.com | `10.1177` | ✓ | ✓ |
| NEJM | nejm.org and its evidence, ai and catalyst subdomains | `10.1056` | ✓ | ✓ |
| ASCE | ascelibrary.org | `10.1061` | ✓ | ✓ |
| ACS | pubs.acs.org | `10.1021` | ✓ | ✓ |
| JAMA Network | jamanetwork.com | `10.1001` | ✓OA | ✓ |
| Neurology (AAN) | neurology.org | `10.1212` | ✓OA | ✓ |
| AHA journals | ahajournals.org | `10.1161` | ✓OA | ✓ |
| Science | science.org (Science, Science Advances, etc.) | `10.1126` | ✓OA | ✓ |
| PNAS | pnas.org | `10.1073` | ✓ | ✓ |
| ACM Digital Library | dl.acm.org | `10.1145` | ✓ | ✓ |
| World Scientific | worldscientific.com | `10.1142` | ✓ | ✓ |
| Karger | karger.com | `10.1159` | ✓ | ✓ |
| RSC | pubs.rsc.org | `10.1039` | ✓OA | ✓ |
| IEEE | ieeexplore.ieee.org | `10.1109` | ✓ | ✓ |
| Thieme | thieme-connect.com / .de | `10.1055` | ✓ | ✓ |
| BMJ | bmj.com and the specialty journals' sites | `10.1136` | ✓ | ✓ |
| AIP Publishing | pubs.aip.org | `10.1063` | ✓OA | ✓ |
| Royal Society | royalsocietypublishing.org | `10.1098` | ✓OA | ✓ |
| APS (Physical Review) | journals.aps.org | `10.1103` | ✓OA | ✓ |
| IOP Publishing | iopscience.iop.org | `10.1088` | ✓ | ✓ |
| Optica | opg.optica.org | `10.1364` | ✓OA | ✓ |
| Annual Reviews | annualreviews.org | `10.1146` | ✓OA | ✓ |
| AMS | journals.ametsoc.org | `10.1175` | ✓OA | ✓ |
| Dove Medical Press | dovepress.com | `10.2147` | ✓ | ✓ |
| MDPI | mdpi.com | `10.3390` | ✓OA | ✓ |
| Frontiers | frontiersin.org | `10.3389` | ✓OA | ✓ |
| PLOS, Copernicus | their own sites | `10.1371`, `10.5194` | ✓ | ✓ |

AIP, Optica and Royal Society keep supplementary files on Figshare; the program fetches the files through the Figshare links on the article page. When the page has no Figshare link: for AIP pages that state there are no supplementary files, an empty list is returned; Optica returns `supplements_not_supported`, which does not say whether this article has attachments. Figshare resources that are neither marked as belonging to this article nor linked from the article page with "supplementary" wording (datasets mentioned only in the data availability statement) are not downloaded, and do not count as supplementary-file failures.

## Sites without dedicated rules

When a DOI redirects to a site outside the table, the program tries the general rules: find the institutional login entry, choose the school's federation and the school, and fetch the PDF the page declares, checking identity before saving as usual. There are no supplementary-file rules.

| Result | Sites |
|---|---|
| Full text tested and got | Cambridge University Press (cambridge.org), American Physiological Society (journals.physiology.org), ASM (journals.asm.org), De Gruyter Brill (degruyterbrill.com), ADA (diabetesjournals.org), RSNA (pubs.rsna.org) |
| No CARSI in the institution list | AACR (aacrjournals.org) |
| No institutional login entry found (`generic_institution_entry_missing`) | Emerald (emerald.com) |

`generic_institution_entry_missing` belongs to "待适配" (Pending support), with the reason "网站暂未适配" (Site not adapted yet): tell the user this kind of site has no rules yet; they can report this paper to the maintainers so rules get added, or download it on the campus network.

## Unsupported platforms

These return `unsupported_platform` or `unsupported_publisher`, without opening the browser, or end quickly: content only on ClinicalKey or EM-Consulte (including ScienceDirect articles stating access via ClinicalKey, with no PDF); CNKI (知网), Wanfang (万方), VIP (维普); DOIs that cannot be resolved, point directly at a PDF file, or land on a Crossref multiple-resolution page. Tell the user this kind of source is not supported; do not call it no access.

## Common school-related results

These results describe "the user's school at this publisher", not a program fault:

- `institution_federation_unavailable`: the publisher's institution list lacks the federation of the user's school, or this school, meaning this publisher has not enabled a route for the school. AMS (journals.ametsoc.org) has only member login, with institutions accessing by the school's network address; it also ends this way. The program ends at once; suggest downloading on the campus network or school VPN.
- `institution_not_registered`: this login entry of the school and this publisher are not connected (as the publisher's or the school's login system says); there is no access through this entry, and it goes under "没权限" (No access); the school's other entries, the campus network or VPN may still work; do not treat it as the school having no subscription to the paper.
- `idp_no_return_to_publisher`: after school sign-in it stays on the school's own site and never returns to the publisher; usually also a school that has not been enabled.
- `entitlement_missing`: the publisher recognized the school and decided this article is not in the subscription. Say only that this article has no access with the current school; do not infer anything about the whole publisher.
- `no_entitlement`: marked with `paper-search-school entitlements set` as no access for this journal or publisher; afterwards the same journal or publisher is skipped directly; view or undo it with `paper-search-school entitlements` (`list` / `clear <key>`).
