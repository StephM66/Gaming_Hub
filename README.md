<p align="center"><img src="custom_components/gaming_hub/brand/icon@2x.png" alt="Gaming Hub" width="200"></p>

# Gaming Hub

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Version](https://img.shields.io/github/v/release/StephM66/Gaming_Hub?include_prereleases)](https://github.com/StephM66/Gaming_Hub/releases)
[![tests](https://github.com/StephM66/Gaming_Hub/actions/workflows/tests.yml/badge.svg)](https://github.com/StephM66/Gaming_Hub/actions/workflows/tests.yml)
[![Licence MIT](https://img.shields.io/github/license/StephM66/Gaming_Hub)](LICENSE)

Intégration Home Assistant qui réunit les consoles de jeu dans un seul hub : état, jeu en
cours (titre et jaquette), temps de jeu, contrôle parental commun, consommation électrique, et
allumage ou extinction quand la console le permet.

> **Tout passe par Gaming Hub.** Le hub parle lui-même à chaque console, ou au compte de son
> fabricant : aucune autre intégration à installer. Ce qu'il sait faire dépend donc de ce que
> chaque console ou chaque compte permet. Sans aucune modification, seule la **PlayStation 5**
> est entièrement pilotée ; la **Switch**, la **PS4**, la **PS3** et **Steam** sont suivies par
> leur compte, sans allumage ni extinction. Les pilotes plus complets pour la PS3 et la Switch
> **ne fonctionnent qu'avec une console modifiée**, avec les contraintes et les risques décrits
> plus bas. Les tableaux suivants disent exactement ce qui fonctionne, à quelle condition, et
> ce qui a déjà été essayé sur une vraie console.

## Sans modifier la console

| Console | Liaison | Allumer, éteindre | État | Jeu en cours et jaquette | Temps de jeu | Essayé sur console |
|---|---|---|---|---|---|---|
| PlayStation 5 | réseau local, compte PSN facultatif | ✅ allumage, mode repos | ✅ | ✅ via le compte PSN | mesuré par le hub | ✅ |
| Nintendo Switch, Switch 2 | compte Nintendo (celui de l'application Contrôle parental) | ❌ Nintendo ne le permet pas | déduit : allumée tant que son temps de jeu augmente, avec le délai de Nintendo | déduit des minutes ajoutées par Nintendo | compté par Nintendo (jour, semaine, mois ; par jeu et par joueur) | pas encore (API Nintendo simulée) |
| PlayStation 4, PlayStation 3 | compte PlayStation Network | ❌ | allumée tant que le compte y est en ligne | ✅ via le compte PSN | mesuré par le hub | pas encore |
| PC, Steam Deck | compte Steam (clé d'API Steam) | ❌ | en jeu ; Steam ouvert sans jeu = veille | ✅ titre et jaquette (jeux Steam seulement) | temps passé en jeu, mesuré par le hub | ✅ jeu Steam sur PC |
| PC, tous launchers | compte Discord (votre propre bot Discord) | ❌ | en jeu ; Discord ouvert sur le PC sans jeu = veille | ✅ tout jeu que Discord reconnaît (Battle.net, GOG, Epic, Steam…), image si le jeu en donne une | temps passé en jeu, mesuré par le hub | pas encore |

Ce qu'une console ne sait pas faire d'elle-même peut être **complété par une de vos entités**
(options de la console) : l'état, l'allumage, l'extinction, le redémarrage. Par exemple
l'interrupteur qui allume le PC complète le compte Steam. Voir « Compléter une console ».

Le contrôle parental vaut pour toutes ces consoles, par console, par enfant et pour le foyer
(voir « Contrôle parental »). Sans commande d'extinction, il prévient seulement, sauf si une
action est associée (« Blocage parental avec »).

**Non pris en charge** : Xbox et consoles rétro. Gaming Hub ne sait pas encore leur parler
directement, et ne passe pas par une autre intégration. Les consoles ajoutées comme « console
déjà présente dans Home Assistant » avec une version précédente sont à supprimer.

## Consoles modifiées (à vos risques)

Pour qui a **déjà** une console modifiée, deux pilotes natifs vont plus loin. Le hub n'aide pas à
modifier une console et ne le recommande pas.

| | PlayStation 3 | Nintendo Switch |
|---|---|---|
| Sur la console | webMAN MOD, sur un firmware personnalisé (CFW) ou PS3HEN | Atmosphère et Switch Assistant |
| Dans Home Assistant | rien de plus | un broker MQTT (l'App Mosquitto) |
| Contraintes | PS3HEN est à réactiver à chaque allumage, sinon le hub voit la console éteinte ; le CFW n'est possible que sur certains modèles | seulement les Switch de première génération non corrigées (sinon une puce à souder) ; Atmosphère est à relancer depuis un PC après chaque arrêt complet ; pour jouer en ligne il faut démarrer le système d'origine, sans Switch Assistant, et le hub ne voit plus la console |
| Risques | console inutilisable en cas d'erreur, bannissement du PSN | console inutilisable en cas d'erreur, bannissement définitif des services en ligne de Nintendo |
| Ce que le hub y gagne | voir le tableau détaillé : températures, ventilateur, extinction, redémarrage, message à l'écran… | voir le tableau détaillé : batterie, image de l'écran, extinction, redémarrage, message à l'écran… |

Rien d'autre à installer dans Home Assistant : pas d'App, pas de dépendance Python externe. Le
hub remplace PS5-MQTT (App) et intègre lui-même les comptes PlayStation Network, Nintendo,
Steam et Discord.

> **État : 0.6.0.** PS5 validée sur une vraie console : état, jeu et jaquette, compte
> PlayStation Network, allumage et mise en repos. Steam validé avec un vrai compte : un jeu
> Steam lancé sur le PC apparaît aussitôt. Tout le reste n'a été testé que contre des consoles
> et des services simulés : la Switch par le compte Nintendo, la PS4 et la PS3 par le PSN, le
> compte Discord et les pilotes des consoles modifiées. Voir [`docs/TESTS_MATERIEL.md`](docs/TESTS_MATERIEL.md).
> Pour la PS5, les protocoles sont aussi vérifiés octet par octet contre playactor.

## Avertissement

**Gaming Hub est fourni en l'état, sans aucune garantie** : ni de fonctionnement, ni de mise à
jour, ni de maintenance, ni de support. C'est un projet personnel, publié pour qui veut s'en
servir ou le reprendre librement (licence MIT-0, sans même obligation de citer l'auteur).

- Il s'appuie sur des interfaces non officielles (PlayStation Network, Lecture à distance,
  compte Nintendo, webMAN MOD, Switch Assistant) qui peuvent changer et casser une fonction sans
  préavis.
- Il pilote des consoles et utilise vos comptes PlayStation Network, Nintendo, Steam et un bot
  Discord : à utiliser à vos risques.
- Le contrôle parental est une aide, pas une barrière : un enfant peut le contourner (console
  hors réseau, jeu hors ligne…). Le compléter par les contrôles parentaux officiels des consoles.
- Projet indépendant, sans lien avec Sony, Nintendo ou Microsoft. Les marques citées
  appartiennent à leurs propriétaires.

Sécurité et signalement des failles : [`SECURITY.md`](SECURITY.md).

## Tableau détaillé

| | PlayStation 5 | PlayStation 3 (modifiée) | Nintendo Switch (modifiée) |
|---|---|---|---|
| Liaison | réseau local (DDP, Remote Play) + compte PSN | HTTP local (+ compte PSN) | MQTT |
| État éteinte / veille / allumée / en jeu | ✅ | ✅ (pas de veille) | ✅ |
| Allumer | ✅ par le réseau | ❌¹ | ❌¹ |
| Éteindre | ✅ mode repos | ✅ | ✅ extinction complète |
| Jeu en cours et jaquette | ✅ via le compte PSN² | ✅ titre et icône | ✅ titre, jaquette³ |
| Image de l'écran en direct | — | — | ✅ caméra (en jeu) |
| Message à l'écran | — | ✅ | ✅ |
| Boutons | — | redémarrer, quitter le jeu | redémarrer |
| Données de la console | version du système | températures CPU/RSX, ventilateur (vitesse, mode, cible), durée de la partie, mémoire et disque libres, allumée depuis, firmware, réseau, utilisation totale, démarrages | batterie (niveau, santé, température, tension), charge, chargeur, écran, luminosité, volume, sortie audio, manettes par joueur |
| Compte PlayStation Network² | statut, niveau et nombre de trophées, PlayStation Plus | idem | — |
| Contrôle parental du hub | ✅ | ✅ | ✅ |
| Consommation | avec une prise connectée | idem | idem |

1. Une PS3 et une Switch ne s'allument pas par le réseau.
2. La PS5 ne publie pas le jeu en cours sur le réseau local. Le hub le lit sur le compte
   PlayStation Network, comme PS5-MQTT, sans autre intégration (étape facultative à l'ajout).
3. Jaquette par identifiant de titre, depuis un service tiers (`tinfoil.media`), modifiable ou
   désactivable dans les options.

## Pourquoi pas tout en MQTT ?

MQTT est utile quand un programme tourne sur la console ou à côté, comme Switch Assistant sur la
Switch. Le hub s'abonne alors simplement à ses sujets. Pour la PS5 et la PS3, la console répond
elle-même sur le réseau local. Passer par MQTT demanderait un programme intermédiaire de plus
(comme PS5-MQTT) sans rien apporter. Le hub n'impose donc pas de broker : MQTT n'est nécessaire
que pour la Switch.

## Installation

[![Ouvrir dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=StephM66&repository=Gaming_Hub&category=integration)
[![Ajouter une console](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=gaming_hub)

Les deux boutons font les étapes 1 et 3 depuis votre Home Assistant. À la main :

1. HACS → ⋮ → Dépôts personnalisés → `https://github.com/StephM66/Gaming_Hub`, type « Intégration ».
2. Installer **Gaming Hub**, redémarrer Home Assistant.
3. Paramètres → Appareils et services → Ajouter une intégration → **Gaming Hub**, puis choisir la console.

Home Assistant 2025.3 ou plus récent. Le logo s'affiche dans Home Assistant à partir de 2026.3,
qui lit les images fournies par l'intégration (`brand/`).

## Ajouter une console

### PlayStation 5

Sur la PS5 :

- Paramètres → Système → Lecture à distance → **Activer la Lecture à distance**.
- Paramètres → Système → Économie d'énergie → Fonctionnalités disponibles en mode repos →
  **Rester connecté à Internet** et **Activer la mise sous tension de la PS5 depuis le réseau**.

Dans Gaming Hub, l'adresse de la console est proposée si elle répond sur le réseau. Le hub
propose ensuite le **compte PlayStation Network** (facultatif) : il donne le jeu en cours avec sa
jaquette, le statut en ligne, les trophées et PlayStation Plus. Se connecter sur
[playstation.com](https://www.playstation.com), ouvrir
<https://ca.account.sony.com/api/v1/ssocookie> et copier la valeur de `npsso`. Ce jeton dure
environ deux mois ; à son expiration, Home Assistant demande le nouveau (la console continue de
fonctionner en attendant).

Il demande enfin comment obtenir l'appairage nécessaire pour allumer et éteindre :

- **Reprendre l'appairage de PS5-MQTT** : proposé quand `/config/ps5-mqtt/credentials.json`
  existe. Rien à refaire sur la console, et PS5-MQTT peut ensuite être désinstallé.
- **Appairer avec un code PIN** : sur la PS5, Paramètres → Système → Lecture à distance →
  Associer un appareil. Saisir le code à 8 chiffres ; l'identifiant du compte PSN est prérempli
  si le compte a été associé juste avant (sinon, le saisir).
- **Plus tard** : état seulement. L'appairage, comme le compte PSN, se fait ensuite par
  « Reconfigurer ».

Si le compte PSN demande un code d'accès à la connexion sur la console, le renseigner : la mise
en veille passe par une connexion Lecture à distance.

### Nintendo Switch et Switch 2 (compte Nintendo, sans modification)

La console doit être associée à l'application **Contrôle parental Nintendo Switch** (gratuite,
sur téléphone). Le hub n'a besoin d'aucune restriction : il lit seulement ce que la console envoie
à l'application.

1. « Nintendo Switch ou Switch 2 (compte Nintendo, sans modification) ».
2. Ouvrir le lien de connexion affiché et se connecter avec le compte Nintendo de l'application.
   Faire un clic droit sur le bouton rouge du compte (appui long sur téléphone), copier le lien,
   le coller dans Home Assistant.
3. Choisir la console si le compte en a plusieurs.

Ce que le hub en tire :

- **Temps de jeu** aujourd'hui, cette semaine et ce mois-ci, tel que Nintendo le compte. Le
  capteur « Temps de jeu aujourd'hui » liste en attributs les jeux et les joueurs du jour. Ce
  temps sert aussi au contrôle parental du hub et aux statistiques de toutes les consoles.
- **Jeu en cours**, titre et jaquette. Nintendo ne le donne pas directement : le hub prend le jeu
  dont les minutes augmentent. Il apparaît donc avec le délai de synchronisation de la console
  (pas encore mesuré), et disparaît 30 minutes après la dernière minute ajoutée.
- **État** : allumée tant que son temps de jeu augmente, où qu'elle soit jouée (TV, portable,
  Switch Lite), avec le même délai ; éteinte 30 minutes après la dernière minute ajoutée.
  Nintendo ne donne pas l'état réel de la console. Pour un état immédiat, une entité peut
  compléter la console (« État d'après », par exemple l'entrée HDMI du dock) : elle décide alors
  seule, y compris quand la Switch est jouée en portable hors de la TV.
- Version du système, modèle (Switch ou Switch 2).

Limites :

- Nintendo ne permet ni d'allumer ni d'éteindre la console.
- Le compte est lu toutes les minutes. Il est lu, jamais modifié.
- Si Nintendo refuse la session (déconnexion, mot de passe changé), Home Assistant demande de
  se reconnecter.

### PS4 ou PS3 (compte PlayStation Network)

1. « PS4 ou PS3 (compte PlayStation Network) », puis choisir la console.
2. Jeton NPSSO : se connecter sur [playstation.com](https://www.playstation.com), ouvrir
   <https://ca.account.sony.com/api/v1/ssocookie> et copier la valeur de `npsso`.

Ce que le hub en tire, par le compte seul : allumée tant que le compte est en ligne sur cette
console, le jeu en cours avec sa jaquette (son icône pour la PS3), le statut, les trophées et
PlayStation Plus.

Conditions et limites :

- La console doit se connecter au PlayStation Network à son démarrage (connexion automatique),
  et le compte ne doit pas apparaître hors ligne pour les autres.
- Ni allumage ni extinction : le PlayStation Network ne le permet pas.
- Le compte est lu toutes les minutes. Le jeton dure environ deux mois ; à son expiration, Home
  Assistant demande le nouveau.

### PC ou Steam Deck (compte Steam)

1. Créer une clé d'API Web Steam sur <https://steamcommunity.com/dev/apikey>, connecté au compte
   (n'importe quel nom de domaine, par exemple `homeassistant.local`). Steam peut demander une
   confirmation dans son application mobile.
2. Dans le profil Steam, Paramètres de confidentialité → Détails des jeux : **Public**, sinon
   Steam ne transmet pas le jeu.
3. « PC ou Steam Deck (compte Steam) » : coller la clé, puis le compte (lien du profil, nom de
   profil personnalisé ou SteamID64).

Ce que le hub en tire : en jeu, le titre et la jaquette ; Steam ouvert sans jeu, « veille » ;
Steam fermé, éteint. Le temps de jeu ne compte que le temps passé en jeu. Le compte est lu toutes
les 30 secondes.

- **Seulement les jeux Steam** : un jeu non-Steam ajouté à la bibliothèque Steam (GOG, Epic,
  Battle.net, émulateurs…) n'est pas visible. Steam ne le publie plus dans le statut « en jeu »
  (vérifié : seul « En ligne » apparaît), quel que soit le raccourci ou le launcher. Pour ces
  jeux, voir « PC, tous launchers (compte Discord) ».
- **État du PC** : Steam ne sait pas si l'ordinateur est allumé. Un interrupteur ou une autre
  entité qui le sait peut compléter le compte (voir « Compléter une console ») : PC éteint,
  allumé, ou en jeu, et l'allumage et l'extinction par cet interrupteur.

Limites :

- Un compte Steam joué sur plusieurs appareils (PC et Steam Deck) n'en fait qu'un : Steam ne dit
  pas sur lequel on joue.
- Ni allumage ni extinction par Steam (seulement par une entité qui complète la console).
- Si Steam refuse la clé (révoquée ou remplacée), Home Assistant en demande une nouvelle.

### PC, tous launchers (compte Discord)

Discord reconnaît lui-même la plupart des jeux PC, quel que soit le launcher (Battle.net, GOG,
Epic, Steam, émulateurs…), et les affiche « Joue à … » sur les serveurs où se trouve le joueur.
Gaming Hub les lit par un bot Discord à vous, dans un de ces serveurs. Le hub parle lui-même à
Discord : rien d'autre à installer, ni sur le PC ni dans Home Assistant.

1. Sur le [portail des développeurs Discord](https://discord.com/developers/applications) :
   **New Application**, puis **Bot** : **Reset Token** pour copier le jeton du bot, et activer
   **Presence Intent** (Privileged Gateway Intents). Aucune validation par Discord n'est
   nécessaire sous 100 serveurs.
2. **OAuth2 → URL Generator** : cocher **bot**, ouvrir le lien obtenu et ajouter le bot à un
   serveur où se trouve le joueur. Un serveur privé créé pour l'occasion suffit. Le bot n'a
   besoin d'aucune permission.
3. Dans Discord, activer le mode développeur (Paramètres → Avancés), puis clic droit sur le
   joueur → copier son identifiant.
4. « PC, tous launchers (compte Discord) » : coller le jeton du bot et l'identifiant du joueur.
   Le hub vérifie que le Presence Intent est actif et que le bot partage un serveur avec lui.

Ce que le hub en tire : en jeu, le nom du jeu (et une image si le jeu en fournit une à
Discord) ; Discord ouvert sur un ordinateur sans jeu, « veille » ; sinon, éteint. Le
changement arrive dès que Discord le publie, sans interrogation régulière. Le temps de jeu ne
compte que le temps passé en jeu.

Conditions et limites :

- Discord doit être ouvert sur le PC, et le joueur doit partager son activité (paramètres de
  confidentialité de l'activité de Discord). En mode invisible, il paraît hors ligne.
- Seuls les jeux que Discord reconnaît sont vus. Un jeu non reconnu peut être ajouté à la main
  dans les paramètres d'activité de Discord.
- Discord peut aussi afficher un jeu joué sur une console liée au compte Discord : il compterait
  alors pour ce PC.
- Pour un même joueur, Steam et Discord voient tous deux les jeux Steam : n'ajouter que Discord
  évite de compter deux fois le même temps de jeu.
- Un bot peut suivre plusieurs joueurs : le hub n'ouvre qu'une connexion par bot.
- Si Discord refuse le jeton (réinitialisé), Home Assistant en demande un nouveau.

### PlayStation 3 (console modifiée)

Réservé à une PS3 **déjà modifiée** (voir « Consoles modifiées »). Console avec webMAN MOD,
allumée au moment de l'ajout. Saisir son adresse IP (port 80 par
défaut), puis, si on le souhaite, le compte PlayStation Network (statut, trophées). Pour
l'allumage, associer dans les options un script de votre choix, par exemple la TV en HDMI-CEC
(« Contrôle par HDMI » activé sur la PS3).

### Nintendo Switch (console modifiée)

Réservé à une Switch **déjà modifiée** (voir « Consoles modifiées »). Sans modification, voir
« Nintendo Switch et Switch 2 (compte Nintendo) ». Switch sous Atmosphère avec [Switch Assistant](https://github.com/ErSeraph/switch-assistant)
configuré vers le broker MQTT de Home Assistant. Dès que la console publie, Home Assistant
propose de l'ajouter (découverte MQTT). On peut aussi l'ajouter à la main avec l'identifiant
client affiché dans l'application Switch Assistant.

- La commande d'extinction de Switch Assistant est commune à toutes les Switch du même broker.
- Une Switch en veille ne publie plus : le hub la voit éteinte 45 s après le dernier signal.
- La caméra « Écran » montre l'écran en direct pendant les jeux (flux RTSP de Switch Assistant).

## Compléter une console

Dans les options de chaque console, seules les fonctions qu'elle n'a pas d'elle-même sont
proposées. Ce que la console sait faire passe toujours en premier.

| Option | Usage |
|---|---|
| Capteur de puissance | Prise connectée en amont de la console : ajoute « Puissance » et « Énergie ». |
| Consommation existante | Compteur d'énergie de la prise ou d'une entrée à reprendre, capteurs à masquer (voir Consommation). |
| État d'après | Entité qui dit si la console est allumée : interrupteur du PC, ping, entrée HDMI, puissance d'une prise (allumée au-delà de 5 W)… Elle décide allumée ou éteinte ; la console ou son compte donne toujours le jeu. Un interrupteur choisi ici sert aussi à allumer et éteindre. |
| Allumer avec / Éteindre avec | Script, scène, bouton ou interrupteur. |
| Redémarrer avec | Script ou bouton ; ajoute le bouton « Redémarrer ». |
| Blocage parental avec | Activé à la place de l'extinction quand le temps de jeu est écoulé. |
| URL de la jaquette (Switch modifiée) | Modèle avec `{title_id}` ; vide pour désactiver. |

## Contrôle parental

Trois niveaux, avec les mêmes réglages ; la règle la plus stricte l'emporte :

- **par console**, sur l'appareil de la console : vaut pour tous ceux qui y jouent ;
- **par enfant**, sur l'appareil de son profil (voir « Gaming Hub : statistiques, foyer et
  profils ») : son temps sur toutes les consoles ;
- **pour le foyer**, sur l'appareil « Gaming Hub » : le temps de toutes les consoles additionné.

Réglages :

- **Contrôle parental** (interrupteur) : active ou désactive.
- **Temps de jeu quotidien** (minutes, 0 = pas de limite) : compté tant que la console est
  allumée, remis à zéro à minuit. Pour une Switch suivie par le compte Nintendo, c'est le temps
  compté par Nintendo, avec son délai ; pour Steam, le temps passé en jeu.
- **Jeu autorisé à partir de / jusqu'à** : plage horaire (heures identiques = pas de plage ;
  une plage peut passer minuit).
- **Préavis avant la limite** (minutes) : avertissement avant la fin.
- **Quand le temps de jeu est écoulé** : prévenir seulement, ou éteindre la console.

Déroulement :

1. Avertissement « Plus que N min » au début du préavis. Il s'affiche sur l'écran de la PS3 et
   de la Switch.
2. À l'échéance, la console s'éteint (ou l'entité « Blocage parental avec » est activée).
3. Rallumée hors temps de jeu, la console reçoit un message puis s'éteint au bout d'une minute.
   La commande est répétée toutes les 2 minutes tant qu'elle reste allumée.

Pour un enfant ou le foyer, le hub prévient et arrête les consoles où l'enfant joue (toutes les
consoles en jeu pour le foyer), chacune selon ce qu'elle sait faire.

Chaque étape émet l'événement `gaming_hub_parental` (`type` : `warning`, `blocked`, `enforced`)
avec `scope` (`console`, `profile`, `household`), `console` ou `consoles`, `profile`, `reason`,
`remaining` et `message`, par exemple pour prévenir un parent :

```yaml
triggers:
  - trigger: event
    event_type: gaming_hub_parental
actions:
  - action: notify.mobile_app_telephone
    data:
      title: "Gaming Hub"
      message: "{{ trigger.event.data.message }}"
```

Capteurs : « Temps de jeu aujourd'hui », « Temps de jeu restant », « Contrôle parental »
(désactivé, autorisé, bientôt écoulé, bloqué). « Temps de jeu restant » n'existe que si une
limite quotidienne ou une plage horaire est réglée : il apparaît et disparaît avec ces réglages.

## Consommation

Facultative : il faut une prise connectée en amont de la console, à associer dans les options
(« Capteur de puissance »). La console gagne alors « Puissance » (W, celle de la prise) et
« Énergie » (kWh, cumulée), que l'on peut ajouter au tableau de bord Énergie comme appareil
individuel. Sans prise, ces deux capteurs n'existent pas : une estimation serait trop
approximative (les modèles et les jeux varient beaucoup). Dissocier la prise les supprime.

**Ne rien compter deux fois.** Si la prise, ou une entrée créée à partir d'elle (intégrale,
compteur de consommation…), a déjà un compteur d'énergie, les options proposent juste après de
le reprendre (celui de la prise est présélectionné) :

- son historique à long terme passe sur « Énergie » de la console : les graphiques et le tableau
  Énergie gardent le passé, et le compteur de la console continue depuis son total ;
- dans le tableau Énergie, la console le remplace parmi les appareils individuels ;
- les capteurs de la prise et le compteur repris sont masqués (facultatif). Ils réapparaissent
  si la prise est dissociée ou la console supprimée.

L'historique est déplacé, pas copié : le compteur repris continue seul, sans son passé. La
reprise n'a lieu qu'une fois par console.

## Entités par console

| Entité | Remarque |
|---|---|
| `media_player` | état, jeu, jaquette, allumer/éteindre ; en mode repos l'état est `off` et l'attribut `power_state` vaut `standby` |
| Jeu en cours, En jeu | pour les automatisations et l'historique ; sans jeu, « Jeu en cours » vaut « Aucun » |
| Puissance, Énergie | seulement avec une prise connectée associée |
| Temps de jeu aujourd'hui, cette semaine, ce mois-ci | la semaine va du lundi au dimanche ; Switch par le compte Nintendo : temps compté par Nintendo, jeux et joueurs du jour en attributs |
| Temps de jeu restant, Contrôle parental | |
| Contrôle parental, Temps de jeu quotidien, Préavis, plage horaire, action | réglages (catégorie configuration) |
| Message à l'écran, Redémarrer | PS3 et Switch modifiées ; « Redémarrer » aussi avec une entité « Redémarrer avec » |
| Quitter le jeu | PS3 |
| Écran (caméra) | Switch, pendant les jeux |
| Données de la console | voir le « Tableau détaillé » ; les diagnostics rarement utiles (adresse IP, utilisation totale, démarrages, tension batterie) sont créés désactivés |
| PlayStation Network, Niveau de trophées, PlayStation Plus | si le compte PSN est associé (PS5, PS4, PS3) |
| Steam | statut du compte Steam (en ligne, absent, hors ligne…) |
| Discord | statut du compte Discord (en ligne, inactif, ne pas déranger, hors ligne) |

## Gaming Hub : statistiques, foyer et profils

L'appareil « Gaming Hub » se crée tout seul avec la première console. Il réunit :

| Capteur | Valeur | Attributs |
|---|---|---|
| Temps de jeu aujourd'hui | minutes, toutes consoles | minutes par console |
| Temps de jeu cette semaine, ce mois-ci | heures, toutes consoles | heures par console |
| Consoles allumées | nombre | liste des consoles allumées |
| Jeux en cours | titres joués en ce moment (« Aucun » sinon) | jeu par console |
| Contrôle parental, Temps de jeu restant | limite du foyer (temps restant seulement si une limite ou une plage est réglée) | |

Et les réglages du contrôle parental du foyer.

**Profils.** Sur l'entrée « Gaming Hub » (Paramètres → Appareils et services → Gaming Hub),
**Ajouter un profil** : un prénom, puis ce qui appartient à l'enfant :

- ses comptes : comptes Steam et Discord, et comptes PlayStation Network liés à une console ;
- ses joueurs Switch : utilisateurs d'une Switch suivie par le compte Nintendo ;
- les consoles où il joue le plus (« joueur principal »).

Le temps de jeu est attribué automatiquement :

| Source | À qui va le temps | Fiabilité |
|---|---|---|
| Switch (compte Nintendo) | le temps de chaque utilisateur de la Switch va au profil qui l'a | officiel, avec le délai de Nintendo |
| PC, Steam Deck (Steam) | au profil qui a le compte Steam | exact |
| PC (Discord) | au profil qui a le compte Discord | exact, pour les jeux que Discord reconnaît |
| PS5, PS4, PS3 avec compte PSN | le temps où le compte PSN lié est en ligne sur la console va au profil qui l'a | bon |
| Le reste (console sans compte, compte ou joueur non rattaché) | au joueur principal de la console | estimation |
| Rien de défini | « non attribué » : compte seulement pour le foyer | — |

Chaque profil est un appareil avec son temps de jeu (jour, semaine, mois, part de chaque
console), « Joue sur » (console et jeu en ce moment), et son contrôle parental.

Limites : une PS5 partagée reconnaît seulement le compte PSN qui lui est lié ; sur Switch,
l'attribution arrive avec le délai de Nintendo.

Le temps de jeu compte le temps où la console est allumée (Switch : le temps compté par
Nintendo ; Steam : le temps passé en jeu). Les graphiques de statistiques de Home Assistant donnent
ensuite les totaux par jour, semaine ou mois sur la durée.

## Architecture

```text
custom_components/gaming_hub/
  protocols/   protocoles sans Home Assistant : ddp (PS5), remoteplay (PS5), psn (compte
               PlayStation Network), nintendo (compte Nintendo), steam (compte Steam),
               discord (compte Discord, par un bot),
               webman (PS3 modifiée), switch_assistant (Switch modifiée)
  drivers/     un pilote par type : ps5, nintendo, steam, playstation (PS4 et PS3 par le
               PSN), ps3 et switch (consoles modifiées)
  coordinator  état du pilote + compte PSN + entités qui complètent la console + temps de
               jeu (par identité), énergie, contrôle parental de la console
  household    foyer et profils : attribution du temps de jeu, contrôle parental commun
  presence     allumée ou non, d'après l'entité choisie pour compléter une console
  parental     règles du contrôle parental (pures, testées sans Home Assistant)
  usage        temps de jeu (jour, semaine, mois) et énergie cumulée
  consumption  reprise du compteur d'énergie d'une prise (historique, tableau Énergie)
  summary      statistiques de toutes les consoles (appareil « Gaming Hub »)
  config_flow  ajout par type, découverte MQTT des Switch, appairage PS5, options
```

Ajouter une console revient à écrire un pilote : `async_fetch()` renvoie un `ConsoleSnapshot`
(alimentation, jeu, image, attributs), et les commandes disponibles sont déclarées. Le contrôle
parental, la consommation et les entités communes viennent du hub.

## Signaler un problème, contribuer

- Bug ou idée : [issues](https://github.com/StephM66/Gaming_Hub/issues/new/choose), en joignant
  les diagnostics de la console (secrets et identifiants masqués).
- Faille de sécurité : en privé, voir [`SECURITY.md`](SECURITY.md).
- Code, nouvelle console, publication d'une version : [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Développement

```sh
python3.13 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest            # protocoles, logique, flux de configuration et entités
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

- `tests/test_protocol_ps5.py` : chiffrement et messages comparés à des vecteurs produits par
  playactor (`tools/remoteplay_vectors.js`), puis séquences complètes contre une PS5 simulée.
- `tests/test_protocol_psn.py` : compte PlayStation Network contre une API Sony simulée (jeton NPSSO, renouvellement, présence, trophées).
- `tests/test_nintendo.py` : compte Nintendo contre une API simulée (connexion, renouvellement), puis jeu déduit, temps de jeu et reconnexion dans Home Assistant.
- `tests/test_steam.py` : compte Steam contre une API simulée, puis l'appareil dans Home Assistant.
- `tests/test_discord.py` : présences Discord, API et Gateway simulées (connexion, reprise, jeton refusé), puis l'appareil dans Home Assistant.
- `tests/test_household.py` : attribution du temps par profil, profils, limite du foyer, consoles complétées par une entité.
- `tests/test_protocol_ps3_switch.py` : page webMAN reconstituée depuis le source de webMAN MOD, sujets Switch Assistant.
- `tests/test_logic.py` : contrôle parental, temps de jeu, énergie.
- `tests/test_config_flow.py`, `tests/test_entities.py` : intégration dans un vrai Home Assistant (MQTT simulé).

Logo : source vectorielle `docs/logo.svg`, rendue en `brand/icon.png` (256 px) et
`brand/icon@2x.png` (512 px) par `tools/render_logo.sh` (Chromium et ImageMagick).

Crédits et licences des projets étudiés ou portés : [`NOTICE.md`](NOTICE.md).
