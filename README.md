<p align="center"><img src="custom_components/gaming_hub/brand/icon@2x.png" alt="Gaming Hub" width="200"></p>

# Gaming Hub

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Version](https://img.shields.io/github/v/release/StephM66/Gaming_Hub?include_prereleases)](https://github.com/StephM66/Gaming_Hub/releases)
[![tests](https://github.com/StephM66/Gaming_Hub/actions/workflows/tests.yml/badge.svg)](https://github.com/StephM66/Gaming_Hub/actions/workflows/tests.yml)
[![Licence MIT](https://img.shields.io/github/license/StephM66/Gaming_Hub)](LICENSE)

Intégration Home Assistant qui réunit les consoles de salon dans un seul hub : allumage et
extinction, jeu en cours (titre et jaquette), contrôle parental commun, consommation électrique.

## Une seule chose à installer

Dans Home Assistant, **Gaming Hub suffit**. Il remplace PS5-MQTT (App) et l'intégration PS3, et
intègre lui-même le compte PlayStation Network. Pas d'App, pas d'autre intégration, pas de
dépendance Python externe. Chaque console est un appareil du hub.

| | Dans Home Assistant | Sur la console |
|---|---|---|
| PlayStation 5 | Gaming Hub | rien (Lecture à distance activée dans les paramètres) |
| PlayStation 3 | Gaming Hub | webMAN MOD (CFW ou PS3HEN) |
| Nintendo Switch | Gaming Hub + un broker MQTT (l'App Mosquitto) | Switch Assistant (Atmosphère) |
| Xbox et autres (facultatif) | Gaming Hub + l'intégration de la console | — |

Ce qui reste est imposé par les consoles, pas par le hub :

- une PS3 d'origine ne dialogue pas sur le réseau : webMAN MOD est ce qui lui donne une interface ;
- une Switch d'origine non plus : Switch Assistant tourne sur la console et ne parle que MQTT,
  d'où le broker (Mosquitto, l'App standard de Home Assistant) ;
- pour la Xbox, que je n'ai pas pu tester faute de console, le hub s'appuie sur une entité
  existante (intégration Xbox officielle) en attendant un pilote natif.

> **État : 0.2.0, à valider sur console.** Les protocoles sont testés contre des consoles et des
> serveurs simulés et, pour la PS5, octet par octet contre playactor (le moteur de PS5-MQTT).
> Aucun essai n'a encore été fait sur une vraie console : voir [`docs/TESTS_MATERIEL.md`](docs/TESTS_MATERIEL.md).

## Avertissement

**Gaming Hub est fourni en l'état, sans aucune garantie** : ni de fonctionnement, ni de mise à
jour, ni de maintenance, ni de support. C'est un projet personnel, publié pour qui veut s'en
servir ou le reprendre librement (licence MIT-0, sans même obligation de citer l'auteur).

- Il s'appuie sur des interfaces non officielles (PlayStation Network, Lecture à distance,
  webMAN MOD, Switch Assistant) qui peuvent changer et casser une fonction sans préavis.
- Il pilote des consoles et utilise votre compte PlayStation Network : à utiliser à vos risques.
- Le contrôle parental est une aide, pas une barrière : un enfant peut le contourner (console
  hors réseau, jeu hors ligne…). Le compléter par les contrôles parentaux officiels des consoles.
- Projet indépendant, sans lien avec Sony, Nintendo ou Microsoft. Les marques citées
  appartiennent à leurs propriétaires.

Sécurité et signalement des failles : [`SECURITY.md`](SECURITY.md).

## Ce que fait chaque console

| | PlayStation 5 | PlayStation 3 | Nintendo Switch | Xbox et autres |
|---|---|---|---|---|
| Liaison | réseau local (DDP, Remote Play) + compte PSN | HTTP local (+ compte PSN) | MQTT | entité source |
| État éteinte / veille / allumée / en jeu | ✅ | ✅ (pas de veille) | ✅ | ✅ |
| Allumer | ✅ par le réseau | script¹ | script¹ | ✅ si la source le permet |
| Éteindre | ✅ mode repos | ✅ | ✅ extinction complète | ✅ si la source le permet |
| Jeu en cours et jaquette | ✅ via le compte PSN² | ✅ titre et icône | ✅ titre, jaquette³ | ✅ |
| Image de l'écran en direct | — | — | ✅ caméra (en jeu) | — |
| Message à l'écran | — | ✅ | ✅ | — |
| Boutons | — | redémarrer, quitter le jeu | redémarrer | — |
| Données de la console | version du système | températures CPU/RSX, ventilateur (vitesse, mode, cible), durée de la partie, mémoire et disque libres, allumée depuis, firmware, réseau, utilisation totale, démarrages | batterie (niveau, santé, température, tension), charge, chargeur, écran, luminosité, volume, sortie audio, manettes par joueur | — |
| Compte PlayStation Network² | statut, niveau et nombre de trophées, PlayStation Plus | idem | — | idem (PS4) |
| Contrôle parental du hub | ✅ | ✅ | ✅ (+ suspension Nintendo⁴) | ✅ |
| Consommation | avec une prise connectée | idem | idem | idem |

1. Une PS3 et une Switch ne s'allument pas par le réseau. On associe un script, un bouton ou un
   interrupteur dans les options : HDMI-CEC via la TV, Bluetooth, pousse-bouton (SwitchBot…).
2. La PS5 ne publie pas le jeu en cours sur le réseau local. Le hub le lit sur le compte
   PlayStation Network, comme PS5-MQTT, sans autre intégration (étape facultative à l'ajout).
3. Jaquette par identifiant de titre, depuis un service tiers (`tinfoil.media`), modifiable ou
   désactivable dans les options.
4. Facultatif : avec l'intégration officielle
   [Contrôle parental Nintendo Switch](https://www.home-assistant.io/integrations/nintendo_parental_controls/),
   le hub peut activer la suspension du jeu au lieu d'éteindre la console (option « Blocage parental avec »).

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

Home Assistant 2025.2 ou plus récent. Le logo s'affiche dans Home Assistant à partir de 2026.3,
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

### PlayStation 3

Console avec webMAN MOD, allumée au moment de l'ajout. Saisir son adresse IP (port 80 par
défaut), puis, si on le souhaite, le compte PlayStation Network (statut, trophées). Pour
l'allumage, associer un script dans les options : la TV en HDMI-CEC (« Contrôle par HDMI »
activé sur la PS3), une manette Bluetooth émulée, ou un pousse-bouton.

### Nintendo Switch

Switch sous Atmosphère avec [Switch Assistant](https://github.com/ErSeraph/switch-assistant)
configuré vers le broker MQTT de Home Assistant. Dès que la console publie, Home Assistant
propose de l'ajouter (découverte MQTT). On peut aussi l'ajouter à la main avec l'identifiant
client affiché dans l'application Switch Assistant.

- La commande d'extinction de Switch Assistant est commune à toutes les Switch du même broker.
- Une Switch en veille ne publie plus : le hub la voit éteinte 45 s après le dernier signal.
- La caméra « Écran » montre l'écran en direct pendant les jeux (flux RTSP de Switch Assistant).

### Xbox et autres consoles

« Xbox ou autre console déjà présente dans Home Assistant », puis choisir le type (Xbox,
PlayStation 4, PC / Steam Deck, console rétro, autre) et l'entité source :

- un **lecteur multimédia** : intégration [Xbox](https://www.home-assistant.io/integrations/xbox/),
  [PlayStation 4](https://www.home-assistant.io/integrations/ps4/), Android TV… Le hub reprend
  l'état, le jeu, la jaquette et l'allumage/extinction. Pour une PS4, le compte PlayStation
  Network peut être associé comme pour la PS5 ;
- un **interrupteur**, un capteur binaire, un `input_boolean` ou un `device_tracker` : allumée ou éteinte ;
- un **capteur de puissance** : allumée au-delà d'un seuil, pratique pour une console rétro sur prise connectée.

Le type ne sert qu'au fabricant et au modèle affichés.

## Options (toutes consoles)

| Option | Usage |
|---|---|
| Capteur de puissance | Prise connectée en amont de la console : ajoute « Puissance » et « Énergie ». |
| Consommation existante | Compteur d'énergie de la prise ou d'une entrée à reprendre, capteurs à masquer (voir Consommation). |
| Allumer avec / Éteindre avec | Script, scène, bouton ou interrupteur qui remplace la commande native. |
| Blocage parental avec | Activé à la place de l'extinction quand le temps de jeu est écoulé. |
| URL de la jaquette (Switch) | Modèle avec `{title_id}` ; vide pour désactiver. |

## Contrôle parental

Le même pour toutes les consoles, réglé sur chaque appareil :

- **Contrôle parental** (interrupteur) : active ou désactive.
- **Temps de jeu quotidien** (minutes, 0 = pas de limite) : compté tant que la console est
  allumée, remis à zéro à minuit.
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

Chaque étape émet l'événement `gaming_hub_parental` (`type` : `warning`, `blocked`, `enforced`)
avec `console`, `reason`, `remaining` et `message`, par exemple pour prévenir un parent :

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
(désactivé, autorisé, bientôt écoulé, bloqué).

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
| Jeu en cours, En jeu | pour les automatisations et l'historique |
| Puissance, Énergie | seulement avec une prise connectée associée |
| Temps de jeu aujourd'hui, Temps de jeu restant, Contrôle parental | |
| Contrôle parental, Temps de jeu quotidien, Préavis, plage horaire, action | réglages (catégorie configuration) |
| Message à l'écran, Redémarrer | PS3 et Switch |
| Quitter le jeu | PS3 |
| Écran (caméra) | Switch, pendant les jeux |
| Données de la console | voir le tableau « Ce que fait chaque console » ; les diagnostics rarement utiles (adresse IP, utilisation totale, démarrages, tension batterie) sont créés désactivés |
| PlayStation Network, Niveau de trophées, PlayStation Plus | si le compte PSN est associé (PS5, PS3, PS4) |

## Architecture

```text
custom_components/gaming_hub/
  protocols/   protocoles sans Home Assistant : ddp (PS5), remoteplay (PS5), psn (compte
               PlayStation Network), webman (PS3), switch_assistant (Switch)
  drivers/     un pilote par type : ps5, ps3, switch, linked (Xbox et autres)
  coordinator  état du pilote + entités liées + temps de jeu, énergie, contrôle parental
  parental     règles du contrôle parental (pures, testées sans Home Assistant)
  usage        temps de jeu du jour et énergie cumulée
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
- `tests/test_protocol_ps3_switch.py` : page webMAN reconstituée depuis le source de webMAN MOD, sujets Switch Assistant.
- `tests/test_logic.py` : contrôle parental, temps de jeu, énergie.
- `tests/test_config_flow.py`, `tests/test_entities.py` : intégration dans un vrai Home Assistant (MQTT simulé).

Logo : source vectorielle `docs/logo.svg`, rendue en `brand/icon.png` (256 px) et
`brand/icon@2x.png` (512 px) par `tools/render_logo.sh` (Chromium et ImageMagick).

Crédits et licences des projets étudiés ou portés : [`NOTICE.md`](NOTICE.md).
