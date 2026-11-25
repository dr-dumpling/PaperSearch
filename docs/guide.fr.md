# Guide d'utilisation de PaperSearch

L'installation, les clés API et la configuration du téléchargement via l'établissement sont décrites dans le [README](../README.fr.md). Les commandes ci-dessous se lancent aussi directement dans un terminal ou un script ; la sortie est en JSON par défaut.

## Exemples de commandes

```bash
# Chercher des articles (ensemble de sources qui ne demande aucune clé)
paper-search search "machine learning clinical prediction" --sources no-key --max-results 5 --pretty

# Une seule source, par exemple PubMed
paper-search search "SGLT2 inhibitor heart failure" --platform pubmed --max-results 10 --pretty

# Vérifier un DOI
paper-search run get_paper_by_doi --arg doi="10.1038/nature12373" --pretty

# Articles citants ; pour les références, remplacer get_paper_citations par get_paper_references
paper-search run get_paper_citations --arg doi="10.1038/nature12373" --pretty

# Facteur d'impact et rang des revues (clé EasyScholar requise)
paper-search journal-metrics "Nature" "BMJ" --pretty

# Trouver comment les Methods sont rédigées dans le texte des articles (clé Semantic Scholar requise)
paper-search run search_semantic_snippets --arg query="propensity score matching" --arg limit=3 --pretty

# Télécharger un article
paper-search download "<DOI>" --platform crossref

# Télécharger en lot les PDF et les annexes (content : pdf, supplements ou les deux ; sans content, PDF seuls)
paper-search run download_batch --json-args '{"items":[{"doi":"<DOI-1>"},{"doi":"<DOI-2>"}],"content":"pdf,supplements"}'

# Articles non téléchargés et raisons
paper-search failures --format text
```

## Fonctionnement

```text
Demande bibliographique de l'utilisateur
│
├─ Trouver des articles, vérifier DOI/PMID → paper-search search (Crossref, PubMed, OpenAlex, etc.)
│    └─ Références confirmées, texte intégral voulu → voir « Télécharger » ci-dessous
├─ Articles citants, références → paper-search run get_paper_citations / get_paper_references
├─ Facteur d'impact, rang → paper-search journal-metrics (clé EasyScholar requise)
├─ Rédaction des Methods, paramètres → paper-search run search_semantic_snippets (clé Semantic Scholar requise)
│
└─ Télécharger le texte, les annexes → paper-search download / run download_with_fallback / run download_batch
     Une même commande de téléchargement essaie dans l'ordre :
     ├─ ① Accès libre (inclus par défaut) : téléchargement propre à la source, PMC, Unpaywall, API des éditeurs
     ├─ ② Sci-Hub en secours (activé par défaut, désactivable)
     ├─ ③ Téléchargement via l'établissement (extension facultative) : le navigateur se connecte à votre établissement via sa fédération d'identité académique ou OpenAthens, et récupère le PDF et les annexes sur le site de l'éditeur
     ├─ ④ Prépublication arXiv : seulement si aucune version publiée n'a été obtenue avant, et signalée comme prépublication
     ├─ À chaque étape, le DOI et le titre de la première page du fichier sont vérifiés ; s'ils correspondent, il est enregistré et les étapes suivantes ne sont pas essayées
     └─ Rien obtenu → paper-search failures donne la raison
```

### Deux modes de téléchargement

|  | Accès libre (par défaut) | Téléchargement via l'établissement (extension facultative) |
|---|---|---|
| Utilisable directement ? | Dès l'installation | Installation séparée : `paper-search school install` |
| Ce que vous obtenez | Le texte intégral en accès ouvert | Le texte intégral auquel votre établissement est abonné ; aussi les annexes, pour les éditeurs qui ont des règles |
| Comment | Téléchargement direct par le programme, en quelques secondes en général, sans connexion : téléchargement propre à la source, lien PDF des métadonnées, PubMed Central, Unpaywall, API des éditeurs (vos propres clés Elsevier/Springer) ; en dernier, Sci-Hub en secours, activé par défaut | Ouvre Chrome, se connecte à votre établissement via sa fédération d'identité académique ou OpenAthens, et récupère le PDF sur le site de l'éditeur |
| Ce que vous faites | Rien | Vous connecter à votre établissement dans le navigateur ; les vérifications sont passées automatiquement, et une alerte vous guide si une intervention manuelle est nécessaire |

Les deux modes utilisent la même commande de téléchargement : l'accès libre est essayé d'abord ; s'il échoue, le droit d'accès de l'établissement prend le relais, à condition que le téléchargement via l'établissement soit installé.

- Pour quelques dizaines à quelques centaines d'articles, un seul `download_batch` suffit : chaque article essaie d'abord les voies ouvertes, et celui dont le texte n'est pas obtenu passe aussitôt au téléchargement via l'établissement, les deux avançant en même temps ; la connexion à l'établissement est demandée quelques secondes après le début. À la fin, `paper-search failures` classe les articles non téléchargés en cinq catégories : pas d'accès (avec les éléments de preuve, comme le texte exact de la page), action requise (connexion, vérification, attente), cause externe (problème du site, de l'établissement ou du réseau), non pris en charge (règles à ajouter dans PaperSearch, avec l'emplacement des captures d'écran) et motif inconnu.
- Pour les articles arXiv, la version publiée est cherchée d'abord ; la prépublication n'est téléchargée que si rien n'a été obtenu. Le résultat indique `version: "preprint"` et, s'il est connu, le DOI de la version publiée.
- Pour ne pas utiliser Sci-Hub, mettez `"useSciHub": false` dans `download_with_fallback` / `download_batch`.
- Pour chaque PDF, le DOI et le titre de la première page sont vérifiés ; un fichier qui ne correspond pas ne compte pas comme réussi et est mis de côté, à vérifier.

### Résultats du téléchargement

Chaque téléchargement crée un dossier `<AAAAMMJJ-HHmmss>_PaperSearchDownload` dans le dossier de téléchargement, qui contient tous les articles de ce téléchargement : les PDF sont placés directement dans ce dossier ; un article dont on a récupéré les annexes a son propre dossier, avec le texte et son `supplements/` (noms de fichiers d'origine conservés) ; les articles sans annexes restent des PDF à plat. Le texte est nommé « abréviation de la revue_année-mois_titre » (année et mois de première publication) ; les PDF de même nom reçoivent automatiquement un court numéro et ne s'écrasent pas ; si deux articles ont le même nom, `_2` est ajouté au nom du dossier du second. Pour les articles qui ont posé problème ou sont à vérifier, les journaux de diagnostic et les captures d'écran ne vont pas dans le dossier de téléchargement mais dans les journaux d'exécution de PaperSearch (`~/.local/share/paper-search-cli/runs/`, supprimés au bout de 30 jours), pour chercher la cause d'un problème ; ils peuvent contenir des informations de connexion, ne les transmettez à personne. Une revue ou une année manquante est notée « 未知期刊 » ou « 未知年份 » (revue inconnue, année inconnue). Le JSON renvoyé par la commande indique l'emplacement réel de chaque fichier.

## Sources de recherche

| Catégorie | Sources | Clé API requise |
|---|---|---|
| Métadonnées académiques générales | Crossref, OpenAlex, Semantic Scholar, Google Scholar | Aucune (la recherche d'extraits de texte de Semantic Scholar en demande une) |
| Biomédecine | PubMed, PubMed Central, Europe PMC | Aucune (une clé PubMed relève les limites) |
| Prépublications et actes de conférence | arXiv, bioRxiv, medRxiv, OpenReview, IACR ePrint | Aucune |
| Informatique et ingénierie | DBLP, ACM, USENIX | Aucune |
| Accès ouvert et archives | CORE, OpenAIRE, Unpaywall | Un e-mail pour Unpaywall ; facultative pour CORE et OpenAIRE |
| Éditeurs et bases de citations | ScienceDirect, Scopus, Springer Nature, IEEE Xplore, Web of Science | Chacune sa clé (ScienceDirect et Scopus partagent la clé Elsevier) |
| Indicateurs de revues | EasyScholar | Requise |

- Les sources sans clé couvrent déjà les articles des grands éditeurs ; une clé ajoute la recherche propre à l'éditeur.
- Une seule source avec `--platform`, plusieurs avec `--sources a,b,c` ; `--sources no-key` est l'ensemble qui ne demande aucune clé (Crossref, PubMed, Europe PMC, arXiv, OpenReview).
- Google Scholar est lu depuis ses pages web et déclenche facilement des vérifications ; il n'est pas dans `--sources all` : utilisez `--platform googlescholar` si besoin.
- Quand plusieurs sources renvoient le même article, elles sont fusionnées par DOI ; si une prépublication arXiv est explicitement liée au DOI de sa version publiée, l'enregistrement publié est conservé.
- Sci-Hub n'est pas une source de recherche ; il sert seulement de secours par DOI lors du téléchargement.

## Agent Skill

Le Skill est publié avec le paquet npm (`skills/paper-search/`), entièrement en anglais ; il commence par un schéma de la logique générale et lit au besoin ces fichiers de référence : routage des fonctions et voies du téléchargement en accès libre, conventions des commandes, installation et usage du téléchargement via l'établissement, [tableau des éditeurs](../skills/paper-search/references/publisher-support.md), dépannage. Il indique seulement à l'IA comment appeler `paper-search` ; il ne conserve ni clé, ni cookie, ni compte.

Pour installer le Skill seul (Node.js 22 ou plus récent requis), lancez cette commande et choisissez vos outils d'IA :

```bash
npx skills add dr-dumpling/PaperSearch -g
```

À la première utilisation, si l'IA voit que la commande `paper-search` n'est pas encore installée, elle vous le demande d'abord et ne l'installe qu'avec votre accord.

Pour installer vous-même la commande et le Skill dans un terminal, sans passer par l'IA, une ligne suffit (exemple avec Claude Code) :

```bash
npm install -g papersearch && paper-search skills update --targets claude
```

```bash
paper-search skills status --pretty
paper-search skills update
```

Sans `--targets`, seuls les emplacements où le Skill est déjà installé sont vérifiés et mis à jour ; aucune copie n'est ajoutée ailleurs. `--targets` accepte `codex`, `claude`, `cursor`, `gemini`, `antigravity`, `agents` (dossier partagé `~/.agents/skills/`). Pour les autres outils d'IA qui lisent des dossiers de Skills, copiez le Skill du paquet dans leur dossier de Skills : `npm root -g` affiche le dossier npm global, et le Skill du paquet se trouve dans son sous-dossier `papersearch/skills/paper-search/` ; copiez le dossier entier avec `references/`, et recopiez-le depuis la nouvelle version à chaque mise à jour. Après l'installation, ouvrez une nouvelle session d'IA pour l'utiliser.

- `--targets all` synchronise vers tous les emplacements intégrés. La mise à jour écrase les fichiers gérés par le paquet, déplace dans le dossier de sauvegarde `skill-backups` les fichiers installés par une ancienne version et que la nouvelle n'utilise plus, et garde les fichiers que vous avez ajoutés vous-même au dossier du Skill.
- Au premier lancement après une mise à niveau de PaperSearch, le Skill installé se met à jour automatiquement ; les anciens fichiers remplacés sont sauvegardés dans `~/.local/share/paper-search-cli/skill-backups/`. Pour désactiver cette mise à jour automatique : `paper-search config set PAPER_SEARCH_SKILL_AUTO_UPDATE false`. Si le Skill installé est plus récent que le programme en ligne de commande (par exemple un nouveau Skill installé d'abord depuis GitHub), il n'est pas remplacé par l'ancien ; la ligne de commande rappelle une fois par jour de lancer `npm install -g papersearch@latest`.
- Si le téléchargement via l'établissement est installé, la première fois qu'il sert après une mise à niveau, l'extension se met d'abord à jour automatiquement (une ligne l'indique dans le terminal), puis le téléchargement continue. Pour désactiver : `paper-search config set PAPER_SEARCH_SCHOOL_AUTO_UPDATE false`, puis lancez vous-même `paper-search school update`.
- `paper-search doctor` affiche l'emplacement et l'état de version du Skill dans les cibles d'installation intégrées.

## Toutes les commandes

| Commande | Usage |
|---|---|
| `paper-search search` | Rechercher les métadonnées d'articles |
| `paper-search journal-metrics` | Indicateurs de revues (EasyScholar) |
| `paper-search download` | Télécharger le PDF d'un article vérifié |
| `paper-search run <outil>` | Appeler précisément un outil, paramètres avec `--arg` ou `--json-args` |
| `paper-search failures` | Récapituler les raisons des échecs de téléchargement |
| `paper-search update check` | Vérifier s'il existe une nouvelle version |
| `paper-search update install` | Mettre à jour vers la nouvelle version (ou cliquer sur « Mettre à jour vers … » dans la page « À propos » de la fenêtre Réglages, qui met à jour tous les composants en une fois) |
| `paper-search school` | Installer, vérifier, mettre à jour ou désinstaller le téléchargement via l'établissement |
| `paper-search setup` / `config` | Configurer les clés, le Skill et l'extension |
| `paper-search settings` | Ouvrir la fenêtre Réglages : dossier de téléchargement, attente et alertes, clés API (requiert le téléchargement via l'établissement et une interface graphique) |
| `paper-search uninstall` | Désinstaller : liste d'abord ce qui sera supprimé (téléchargement via l'établissement et état de connexion, journaux d'exécution, configuration et clés API, Skill dans chaque outil d'IA), puis supprime tout en une fois après confirmation ; les articles téléchargés ne sont pas touchés ; `--dry-run` liste sans supprimer |
| `paper-search doctor` | Bilan de santé : configuration, fonctions disponibles, état du Skill et de l'extension |
| `paper-search skills` | État, différences et mise à jour du Skill |
| `paper-search smoke` | Autotest hors ligne ou réel |
| `paper-search tools` | Lister tous les noms d'outils et leurs paramètres |

Les commandes renvoient du JSON par défaut ; `--pretty` le met en forme, `--format text` produit un rapport lisible. Liste complète : `paper-search tools --pretty` ou les [conventions des commandes](../skills/paper-search/references/cli-contract.md).

## Autres réglages

Modifiez-les avec `paper-search config set <réglage> <valeur>`, ou lancez `paper-search setup <réglage>`.

| Réglage | Rôle | Par défaut |
|---|---|---|
| `DEFAULT_DOWNLOAD_PATH` | Dossier où sont enregistrés par défaut les articles téléchargés | `./downloads` dans le dossier courant de la commande ; modifiable aussi dans les réglages de la capsule de progression |
| `UNPAYWALL_EMAIL`, `CROSSREF_MAILTO` | E-mail de contact pour Unpaywall (recherche par DOI de PDF en accès ouvert) et pour l'accès prioritaire de Crossref | Généré automatiquement si laissé vide dans `paper-search setup` ; peut aussi se saisir dans la fenêtre Réglages |
| `GOOGLE_SCHOLAR_PROXY_URL` | Proxy de sortie pour Google Scholar ; si les accès directs sont bloqués à répétition, utilisez un proxy autorisé | Non défini |
| `PAPER_SEARCH_SKILL_AUTO_UPDATE` | `false` : après une mise à niveau, le Skill installé n'est plus mis à jour automatiquement | Activé |
| `PAPER_SEARCH_SCHOOL_AUTO_UPDATE` | `false` : après une mise à niveau, l'extension du téléchargement via l'établissement n'est plus mise à jour automatiquement ; lancez vous-même `paper-search school update` | Activé |
| `PAPER_SEARCH_UPDATE_NOTIFY` | `false` : plus d'avis de nouvelle version | Activé |
| `PAPER_SEARCH_SCHOOL_DECLINED` | `true` : l'IA ne propose plus d'elle-même d'installer le téléchargement via l'établissement (elle le règle elle-même si vous avez dit non) ; pour l'installer, demandez-le simplement | Non défini |
| `PAPER_SEARCH_SCHOOL_ENABLED` | Interrupteur du téléchargement via l'établissement | Réglé automatiquement par `paper-search school install` |

## Dépannage

| Problème | Que faire |
|---|---|
| Commande `paper-search` introuvable | Réinstallez avec `npm install -g papersearch` |
| `EEXIST` à l'installation, ou passage depuis l'ancien paquet `paper-search-cli` | D'abord `npm uninstall -g paper-search-cli`, puis installez `papersearch` ; configuration, Skill, connexion à l'établissement et historique des téléchargements sont conservés |
| Une fonction ne marche pas | `paper-search doctor --format text` pour voir ce qui manque, puis `paper-search setup` pour le configurer |
| Les articles sur abonnement ne se téléchargent pas | `paper-search school status --format text` pour vérifier que le téléchargement via l'établissement est installé ; `paper-search failures --format text` pour la raison de chaque article |
| Une source limite le débit | Réduisez `--max-results`, configurez sa clé, ou changez de source |
| Google Scholar affiche une page de vérification | Attendez un moment avant de réessayer, ou utilisez `--sources no-key` |
| L'IA lit un ancien Skill | `paper-search skills status --pretty`, puis `paper-search skills update` ; ouvrez une nouvelle session d'IA |
| Se connecter d'abord à l'établissement, ou tester la connexion | `paper-search school login --doi <DOI d'un article auquel votre établissement est abonné>` : le navigateur dédié s'ouvre, connectez-vous sur la page de connexion de l'établissement |
| Mettre à jour ou désinstaller le téléchargement via l'établissement | `paper-search school update` ; `paper-search school uninstall` |
| Désinstaller PaperSearch | `paper-search uninstall`, puis après confirmation `npm uninstall -g papersearch` |
| PowerShell sous Windows bloque `npm` | Utilisez `npm.cmd`, ou lancez la commande dans l'invite de commandes |
| Signaler un échec de téléchargement | Utilisez le modèle de ticket « Download failure », en indiquant la version, le système, le site et le DOI ; `paper-search failures --export ./failure-report.zip` exporte les échecs enregistrés ; avant de joindre l'archive, vérifiez que le `summary.md` et les captures d'écran qu'elle contient ne comportent pas d'informations personnelles |
| Comment mettre à niveau | `npm install -g papersearch@latest` ; au premier lancement après la mise à niveau, le Skill installé se met à jour automatiquement |
