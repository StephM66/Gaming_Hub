<p align="center"><img src="custom_components/gaming_hub/brand/icon@2x.png" alt="Gaming Hub" width="200"></p>

# Gaming Hub

Intégration Home Assistant qui réunit les consoles de salon dans un seul hub : allumage et
extinction, jeu en cours (titre et jaquette), contrôle parental commun, consommation électrique.

Une seule intégration, pas d'App (add-on), pas de dépendance Python externe. Chaque console est
une entrée de configuration et un appareil. Le hub parle directement aux consoles quand c'est
possible. Sinon, il reprend une entité déjà présente dans Home Assistant (Xbox, PS4,
PlayStation Network, prise connectée…).

> **État : 0.1.0, à valider sur console.** Les protocoles sont testés contre des consoles
> simulées et, pour la PS5, octet par octet contre playactor (le moteur de PS5-MQTT). Aucun
> essai n'a encore été fait sur une vraie console : voir [`docs/TESTS_MATERIEL.md`](docs/TESTS_MATERIEL.md).

## Ce que fait chaque console

| | PlayStation 5 | PlayStation 3 | Nintendo Switch | Xbox et autres |
|---|---|---|---|---|
| Prérequis | Lecture à distance activée | webMAN MOD (CFW ou PS3HEN) | Switch Assistant (Atmosphère) + MQTT | une entité HA (Xbox, PS4, prise…) |
| Liaison | réseau local (DDP, Remote Play) | HTTP local | MQTT | entité source |
| État éteinte / veille / allumée / en jeu | ✅ | ✅ (pas de veille) | ✅ | ✅ |
| Allumer | ✅ par le réseau | script¹ | script¹ | ✅ si la source le permet |
| Éteindre | ✅ mode repos | ✅ | ✅ extinction complète | ✅ si la source le permet |
| Jeu en cours et jaquette | via l'intégration PlayStation Network² | ✅ titre et icône | ✅ titre, jaquette³ | ✅ |
| Message à l'écran | — | ✅ | ✅ | — |
| Redémarrer | — | ✅ | ✅ | — |
| Capteurs propres | version du système | CPU, RSX, ventilateur, firmware | batterie, charge, manettes | — |
| Contrôle parental du hub | ✅ | ✅ | ✅ (+ suspension Nintendo⁴) | ✅ |
| Consommation | mesurée ou estimée | mesurée ou estimée | mesurée ou estimée | mesurée ou estimée |

1. Une PS3 et une Switch ne s'allument pas par le réseau. On associe un script, un bouton ou un
   interrupteur dans les options : HDMI-CEC via la TV, Bluetooth, pousse-bouton (SwitchBot…).
2. La PS5 ne publie pas le jeu en cours sur le réseau local. L'intégration officielle
   [PlayStation Network](https://www.home-assistant.io/integrations/playstation_network/) le
   fournit, et le hub le reprend (option « Source du jeu en cours »).
3. Jaquette par identifiant de titre, depuis un service tiers (`tinfoil.media`), modifiable ou
   désactivable dans les options.
4. Avec l'intégration officielle
   [Contrôle parental Nintendo Switch](https://www.home-assistant.io/integrations/nintendo_parental_controls/),
   le hub peut activer la suspension du jeu au lieu d'éteindre la console (option « Blocage parental avec »).

## Pourquoi pas tout en MQTT ?

MQTT est utile quand un programme tourne sur la console ou à côté, comme Switch Assistant sur la
Switch. Le hub s'abonne alors simplement à ses sujets. Pour la PS5 et la PS3, la console répond
elle-même sur le réseau local. Passer par MQTT demanderait un programme intermédiaire de plus
(comme PS5-MQTT) sans rien apporter. Le hub n'impose donc pas de broker : MQTT n'est nécessaire
que pour la Switch.

## Installation

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
demande ensuite comment obtenir l'appairage nécessaire pour allumer et éteindre :

- **Reprendre l'appairage de PS5-MQTT** : proposé quand `/config/ps5-mqtt/credentials.json`
  existe. Rien à refaire sur la console, et PS5-MQTT peut ensuite être désinstallé.
- **Appairer avec un code PIN** : sur la PS5, Paramètres → Système → Lecture à distance →
  Associer un appareil. Saisir le code à 8 chiffres et l'identifiant numérique du compte PSN.
  Si l'intégration PlayStation Network est configurée, l'identifiant est prérempli.
- **Plus tard** : état seulement. L'appairage se fait ensuite par « Reconfigurer ».

Si le compte PSN demande un code d'accès à la connexion sur la console, le renseigner : la mise
en veille passe par une connexion Lecture à distance.

Pour le jeu en cours et la jaquette, configurer l'intégration PlayStation Network, puis choisir
son lecteur « PlayStation 5 » comme « Source du jeu en cours » dans les options du hub.

### PlayStation 3

Console avec webMAN MOD, allumée au moment de l'ajout. Saisir son adresse IP (port 80 par
défaut). Pour l'allumage, associer un script dans les options : la TV en HDMI-CEC
(« Contrôle par HDMI » activé sur la PS3), une manette Bluetooth émulée, ou un pousse-bouton.

### Nintendo Switch

Switch sous Atmosphère avec [Switch Assistant](https://github.com/ErSeraph/switch-assistant)
configuré vers le broker MQTT de Home Assistant. Dès que la console publie, Home Assistant
propose de l'ajouter (découverte MQTT). On peut aussi l'ajouter à la main avec l'identifiant
client affiché dans l'application Switch Assistant.

- La commande d'extinction de Switch Assistant est commune à toutes les Switch du même broker.
- Une Switch en veille ne publie plus : le hub la voit éteinte 45 s après le dernier signal.

### Xbox et autres consoles

« Xbox ou autre console déjà présente dans Home Assistant », puis choisir le type (Xbox,
PlayStation 4, PC / Steam Deck, console rétro, autre) et l'entité source :

- un **lecteur multimédia** : intégration [Xbox](https://www.home-assistant.io/integrations/xbox/),
  [PlayStation 4](https://www.home-assistant.io/integrations/ps4/), PlayStation Network,
  Android TV… Le hub reprend l'état, le jeu, la jaquette et l'allumage/extinction ;
- un **interrupteur**, un capteur binaire, un `input_boolean` ou un `device_tracker` : allumée ou éteinte ;
- un **capteur de puissance** : allumée au-delà d'un seuil, pratique pour une console rétro sur prise connectée.

Le type ne sert qu'au fabricant affiché et aux puissances estimées par défaut.

## Options (toutes consoles)

| Option | Usage |
|---|---|
| Capteur de puissance | Puissance mesurée (prise connectée), qui remplace l'estimation. |
| Source du jeu en cours | Lecteur multimédia qui fournit le jeu quand la console ne le fait pas (PlayStation Network). |
| Allumer avec / Éteindre avec | Script, scène, bouton ou interrupteur qui remplace la commande native. |
| Blocage parental avec | Activé à la place de l'extinction quand le temps de jeu est écoulé. |
| Puissances estimées | En jeu, allumée sans jeu, en veille ou éteinte (W). Valeurs indicatives par défaut. |
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

« Puissance » (W) vient du capteur de puissance associé ou, à défaut, d'une estimation selon
l'état (en jeu, allumée, veille). « Énergie » (kWh, cumulée) peut s'ajouter au tableau de bord
Énergie comme appareil individuel. Valeurs estimées par défaut :

| Console | En jeu | Allumée sans jeu | Veille / éteinte |
|---|---|---|---|
| PS5 | 200 W | 70 W | 1,5 W |
| PS3 | 90 W | 75 W | 0,5 W |
| Switch (dock) | 12 W | 7 W | 0,5 W |
| Xbox | 150 W | 50 W | 10 W |
| PS4 | 140 W | 60 W | 5 W |

Une prise connectée donne la vraie valeur ; les modèles et les jeux varient beaucoup (une PS3
« fat » consomme plus du double d'une Slim).

## Entités par console

| Entité | Remarque |
|---|---|
| `media_player` | état, jeu, jaquette, allumer/éteindre |
| Jeu en cours, En jeu | pour les automatisations et l'historique |
| Puissance, Énergie | si un capteur est associé ou si une estimation existe |
| Temps de jeu aujourd'hui, Temps de jeu restant, Contrôle parental | |
| Contrôle parental, Temps de jeu quotidien, Préavis, plage horaire, action | réglages (catégorie configuration) |
| Message à l'écran, Redémarrer | PS3 et Switch |
| Capteurs propres | PS3 : températures, ventilateur, firmware ; Switch : batterie, charge, manettes ; PS5 : version |

## Architecture

```text
custom_components/gaming_hub/
  protocols/   protocoles sans Home Assistant : ddp (PS5), remoteplay (PS5), webman (PS3),
               switch_assistant (Switch)
  drivers/     un pilote par type : ps5, ps3, switch, linked (Xbox et autres)
  coordinator  état du pilote + entités liées + temps de jeu, énergie, contrôle parental
  parental     règles du contrôle parental (pures, testées sans Home Assistant)
  usage        temps de jeu du jour et énergie cumulée
  config_flow  ajout par type, découverte MQTT des Switch, appairage PS5, options
```

Ajouter une console revient à écrire un pilote : `async_fetch()` renvoie un `ConsoleSnapshot`
(alimentation, jeu, image, attributs), et les commandes disponibles sont déclarées. Le contrôle
parental, la consommation et les entités communes viennent du hub.

## Développement

```sh
python3.13 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest            # protocoles, logique, flux de configuration et entités
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

- `tests/test_protocol_ps5.py` : chiffrement et messages comparés à des vecteurs produits par
  playactor (`tools/remoteplay_vectors.js`), puis séquences complètes contre une PS5 simulée.
- `tests/test_protocol_ps3_switch.py` : page webMAN reconstituée depuis le source de webMAN MOD, sujets Switch Assistant.
- `tests/test_logic.py` : contrôle parental, temps de jeu, énergie.
- `tests/test_config_flow.py`, `tests/test_entities.py` : intégration dans un vrai Home Assistant (MQTT simulé).

Logo : source vectorielle `docs/logo.svg`, rendue en `brand/icon.png` (256 px) et
`brand/icon@2x.png` (512 px) par `tools/render_logo.sh` (Chromium et ImageMagick).

Crédits et licences des projets étudiés ou portés : [`NOTICE.md`](NOTICE.md).
