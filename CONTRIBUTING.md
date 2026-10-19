# Contribuer

Gaming Hub est un projet personnel, [fourni en l'état](README.md#avertissement) : les retours et
les propositions sont bienvenus, mais une réponse, un correctif ou une fusion ne sont pas garantis.

## Signaler un problème

Ouvrir une [issue](https://github.com/StephM66/Gaming_Hub/issues/new/choose) avec le formulaire
« Bug », en joignant si possible :

- **les diagnostics** : Paramètres → Appareils et services → Gaming Hub → la console → ⋮ →
  Télécharger les diagnostics. Les clés, jetons et identifiants (compte PlayStation Network,
  console) y sont masqués ; les adresses IP locales restent, elles servent au diagnostic ;
- **les journaux** : sur la même page, « Activer la journalisation de débogage », reproduire le
  problème, puis la désactiver : le fichier se télécharge. Le relire avant de le publier.

Une faille de sécurité ne se signale pas dans une issue publique : voir [`SECURITY.md`](SECURITY.md).

Les essais sur console réelle sont précieux : la liste est dans
[`docs/TESTS_MATERIEL.md`](docs/TESTS_MATERIEL.md), un résultat (même « ça marche ») peut être
rapporté dans une issue.

## Proposer une modification

1. Pour un changement important (nouvelle console, nouvelle dépendance, changement de
   comportement), ouvrir d'abord une issue pour en discuter.
2. Forker le dépôt, créer une branche depuis `main`.
3. Vérifier en local (Python 3.13) :

   ```bash
   python3.13 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
   .venv/bin/pytest
   .venv/bin/ruff check . && .venv/bin/ruff format --check .
   ```

4. Ouvrir une pull request vers `main` en remplissant le modèle. Les contrôles `tests`,
   `hassfest` et `hacs` doivent passer ; la PR est fusionnée en « squash » (un commit par PR).

Quelques règles pour garder le hub léger et facile à maintenir :

- pas de nouvelle dépendance Python sans discussion préalable ;
- chaque comportement nouveau ou corrigé a son test ; les protocoles se testent contre une
  console ou un serveur simulé (voir `tests/`) ;
- les protocoles (`protocols/`) n'importent pas Home Assistant ; ce qui est propre à une console
  va dans son pilote (`drivers/`) ;
- les textes visibles passent par les traductions, en anglais **et** en français
  (`translations/en.json`, `translations/fr.json`) ;
- tout ce qui vient du réseau ou de MQTT est borné et validé (voir `tests/test_security.py`).

Le code est en anglais, la documentation en français ; les issues et PR peuvent être écrites
en français ou en anglais.

## Publier une version (mainteneur)

1. Dans la PR, augmenter `version` dans `custom_components/gaming_hub/manifest.json`
   (`0.2.1` pour une correction, `0.3.0` pour une nouveauté, `0.3.0b1` pour une préversion).
2. Une fois la PR fusionnée, le workflow `release` crée le tag `v<version>` et la release
   GitHub avec les notes générées depuis les PR. HACS propose alors la mise à jour.
   Une préversion (`a`, `b`, `rc`) est publiée comme telle : HACS ne la propose qu'à qui
   l'a demandé.

## Licence

En contribuant, vous acceptez que votre contribution soit publiée sous la
[licence MIT](LICENSE) du projet.
