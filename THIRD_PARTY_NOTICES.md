# Third-party notices

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

Upstream's `public/data/i18n/` translations are separately attributed to KC3Kai/kc3-translations under MIT. Those files are **not copied here**. Korean equipment names come from this bot's existing equipment metadata, overrides, and alias list. Korean development-pool labels were added for this bot.

Game master data and other pre-existing external datasets retain their respective rights and source attributions. Inclusion of a GPL license for the software does not relicense third-party game content or grant rights the original provider does not hold.
