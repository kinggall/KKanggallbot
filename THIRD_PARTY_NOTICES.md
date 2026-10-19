# Third-party notices

## Expedition facts and ElectronicObserver reference

- wikiwiki Kancolle contributors: https://wikiwiki.jp/kancolle/%E9%81%A0%E5%BE%81 . Expedition requirements, rewards and prerequisite facts were extracted from a user-provided HAR; the site's HTML and browser request credentials are not redistributed.
- ElectronicObserverEN/ElectronicObserver revision `8b66df3ffeb79ddef0d092693cf0d257ee96c1a7`: `MissionClearCondition.cs` and `ExpeditionCalculatorData.cs` were consulted to verify ship eligibility, IDs, levels, stats, duration, rewards and monthly/drum classifications. The existing ElectronicObserver MIT notice below is retained.
- ElectronicObserverEN/Data revision `824b5ce4383f5be8ca40f12fb8c5413ada29a9ef`: `Translations/ko-KR/expedition.json` supplies Korean names. Credits belong to the translation contributors.
- Derived files: `data/expeditions.json`, `data/expedition_verification.json`; implementation and rebuild instructions: `EXPEDITION_DATA.md`. External factual data retains its respective source rights; this does not apply the bot's GPL license to the wiki page.
- Additional expedition cross-check: user-provided Namu Wiki HAR, KC3Kai/KC3Kai `src/library/helpers/KanColleHelpers.js` at `db1e102da2315299d543cfc90003929dc377c111`, and kcwiki/kancolle-data `api/api_start2.json` at `7b92cdb8e4601fdec45ddd00489c7c6da9fa346d`. Only factual values and provenance hashes are extracted; the JavaScript is not executed or redistributed. Source decisions and remaining uncertainty are in `EXPEDITION_CROSSCHECK.md` and `data/expedition_crosscheck.json`.

## 艦ろぐ / kanlog.info

- Source: https://kanlog.info/ (37 normal-map pages).
- The operator permitted the chatbot use described by the user, with access spread out to avoid bursts and source attribution requested where possible.
- Extracted factual statistics: `data/kanlog_maps_seed.json`, with the earlier 5-5 regression snapshot retained as `data/kanlog_55_seed.json`; subsequent snapshots are stored on the user's PC. The site's HTML, scripts, artwork and images are not redistributed here.
- Attribution and thanks in Korean and Japanese are in README.md; collection and verification details are in KANLOG_DROPS.md. This does not relicense third-party site data under the bot software license.

## kcwiki ship conversion material reference

- Source: https://github.com/kcwiki/kancolle-data/blob/7b92cdb8e4601fdec45ddd00489c7c6da9fa346d/wiki/ship.json
- Derived data: `data/ship_convert_materials.json`, 53 directed conversion routes extracted from ship remodel fields, with upstream record names and field prefixes retained.
- Attribution: kcwiki/kancolle-data contributors and their upstream wiki data contributors. This factual data extraction does not assert ownership or relicense upstream material under the bot software license.
- Method and limitations: `REMODEL_MATERIALS_DATA.md`.

## Remodel-Status data

- Author/project: s3gn, https://github.com/s3gn/Remodel-Status
- Revision: `d7ab4df226e3d74912c4dc358694697f51f1b493` (`gh-pages`).
- Unmodified data: upstream `data/ships.csv`, stored here as `data/ship_remodel_materials.csv`.
- No explicit license file was found at this revision. This attribution does not relicense the data under the bot's GPL. See `REMODEL_MATERIALS_DATA.md` for schema and limitations.

## kc-development-tools

- Project: SkywalkerJi/kc-development-tools
- Source: https://github.com/SkywalkerJi/kc-development-tools
- Revision: `d0651207acb88854baa29a8e64effe8a9a095370`
- Upstream authors: SkywalkerJi and contributors; see the upstream Git history for attribution.
- License: GNU General Public License, version 3. The complete upstream license is preserved verbatim in [LICENSE](LICENSE).
- Unmodified upstream files: `data/development/DevelopmentPool.json`, `data/development/start2.json`, `data/development/ctype.json`.
- Adapted upstream files: `src/core/developmentPool.ts`, `sameShipList.ts`, `poolMatching.ts`, `recipe.ts`, and `orchestration.ts`.
- Modifications dated 2026-10-18: port the recipe calculation to Python in `development.py`; retain pool membership, resource thresholds, negative-pool handling, and display sorting; provide Korean secretary labels, one optimal recipe and an optional generic recipe; reuse the bot's equipment-name/alias/ID search. Integrate the command into `bot.py`.
- The combined bot software is distributed under GPL-3.0. Corresponding source is provided in this repository: https://github.com/kinggall/KKanggallbot . Preserve this notice and LICENSE when redistributing it; distribute changes under the applicable GPL requirements. No warranty is provided, as described in LICENSE.
- Additional modification dated 2026-10-18: omit recipes whose target probability plus failure probability exceeds 100%; the pinned data contains one such recipe for equipment #201. All other recipes are preserved.
- Additional presentation change dated 2026-10-18: when the optimal and general recipes have identical resources, target probability and failure probability, display only the general recipe as optimal.
- Additional modification dated 2026-10-18: port forward `computePoolRates`, resource-pool selection, equipment affordability/type ordering, and `setFlagship` secretary selection from upstream `src/core/orchestration.ts`, `recipe.ts`, `poolMatching.ts`, `grouping.ts`, and `src/stores/developmentStore.ts`. Add `!레시피` with Korean ship names, aliases and explicit remodel selection. Expand forward secretary conditions using this bot's current ship CSV and game-ID metadata; retain the pinned original membership for reverse `!개발` recipes. Preserve game-data and translation source attributions already recorded in this repository.
- Additional presentation changes dated 2026-10-18: clarify that the upstream Hyuga/Ise special pools include Kai and Kai Ni; allow named Soya form selection and display the selected form; revise invalid recipe input guidance. Numeric pool data remains unmodified.

Upstream's `public/data/i18n/` translations are separately attributed to KC3Kai/kc3-translations under MIT. Those files are **not copied here**. Korean equipment names come from this bot's existing equipment metadata, overrides, and alias list. Korean development-pool labels were added for this bot.

Game master data and other pre-existing external datasets retain their respective rights and source attributions. Inclusion of a GPL license for the software does not relicense third-party game content or grant rights the original provider does not hold.

## Starting equipment factual supplement

`data/initial_equipment_supplement.json` records ship/equipment IDs, slot positions and improvement levels extracted from `wiki/ship.json` and `wiki/equipment.json` in https://github.com/kcwiki/kancolle-data/tree/7b92cdb8e4601fdec45ddd00489c7c6da9fa346d . Original game data rights remain with their respective owners. Narrative text and upstream translations are not included. File hashes and exact CSV slot values are preserved for verification. The 2026-10-18 implementation uses this supplement only for verified improvement levels and unknown CSV slots; it retains known CSV equipment and explicitly empty slots. See INITIAL_EQUIPMENT_DATA.md for the extraction fields and validation limits.

## ElectronicObserver equipment improvement data and cost semantics

`data/equipment_upgrades.json` preserves the original `Data/EquipmentUpgrades.json` from https://github.com/ElectronicObserverEN/Data/tree/b975e55ec1a548522c057b6796b39609de5e39d7 . Equipment, ship and material identifiers and game-data rights retain their respective source attributions and rights. This is a static game-information dataset, not a service API.

The Python implementation in `improvement.py`, added 2026-10-18, follows the target-level cost rules and additive extra-material handling in ElectronicObserverEN/ElectronicObserver revision `8b66df3ffeb79ddef0d092693cf0d257ee96c1a7`, particularly `ElectronicObserver/Utility/Data/EquipmentUpgradeCostExtensions.cs` and `ElectronicObserver.Core/Types/Serialization/EquipmentUpgrade`. It adds Korean names, contiguous equal-cost grouping, helper weekdays, distinct conversion routes, and the `!개수` webhook command. The MIT notice for the referenced software is preserved below. The combined bot continues to be distributed under GPL-3.0, retaining this compatible upstream notice.

Subsequent presentation changes: label helpers as the second ship, group same-family remodel forms only when weekday sets match, hide base resources, separate material consumption from development/screw costs, and omit numbering for a single conversion. Original numeric data and eligibility IDs remain unchanged.

The MIT License (MIT)

Original work copyright (c) 2014 Andante
Translation work copyright (c) 2015 Ryuu Kitsune

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
