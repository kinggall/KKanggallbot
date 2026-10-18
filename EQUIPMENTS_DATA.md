# equipments.csv 데이터 분석

분석일: 2026-10-19 (한국). 사용자가 74식 장비도감에서 내보내 업로드한 `equipments.csv`를 저장소 루트에 원본 그대로 보관했습니다.

## 저장 형식과 규모

- 인코딩: **CP932(Windows 일본어 / Shift-JIS 계열)**. UTF-8로 읽으면 이름이 깨질 수 있습니다.
- 헤더 제외 **741행**, **27개 컬럼**.
- 일반 장비 **584종**(장비 ID 1~588, 중간 결번 있음), 심해 장비 **157종**(ID 1501 이상).
- 장비 ID는 전부 고유합니다. 이름은 738종으로 일부 심해 장비 이름이 중복됩니다.
- 원본 SHA-256: `17ead9e3a8e77f14cb0932ea00342a7fc8be7c4bb0978e88cac1a33cd8094d22`.

```python
import csv
with open("equipments.csv", encoding="cp932", newline="") as file:
    equipment = list(csv.DictReader(file))
```

CSV는 저장·분석 자료입니다. 현재 `!피트`는 `data/fit_bonuses.json`과 `data/fit_metadata.json`을 읽습니다.

## 전체 컬럼

| 원문 컬럼 | 의미·사용 가능 정보 |
| --- | --- |
| 装備ID | 게임 장비 ID. 다른 데이터와 연결할 기본 키 |
| 図鑑番号 | 도감 번호. 심해 장비에는 0이 들어갈 수 있음 |
| 装備名 | 일본어 장비명. 일부 라틴 문자 악센트는 단순화됨 |
| 装備種1 / 装備種2 / 装備種3 / 装備種4 / 装備種5 | 게임 `api_type`의 5개 분류 코드. `装備種3`이 현재 피트·장착 판정에서 쓰는 장비 종류 코드 |
| 火力 | 화력 |
| 雷装 | 뇌장 |
| 対空 | 대공 |
| 装甲 | 장갑 |
| 対潜 | 대잠 |
| 回避 | 회피 |
| 索敵 | 색적 |
| 運 | 운. 이 파일에서는 전 장비 0 |
| 命中 | 명중 |
| 爆装 | 폭장 |
| 射程 | 사거리 코드 |
| レア | 희귀도 코드 |
| 廃棄燃料 / 廃棄弾薬 / 廃棄鋼材 / 廃棄ボーキ | 폐기 시 얻는 연료·탄약·강재·보크사이트 |
| 図鑑文章 | 도감 설명. **741행 모두 빈 값**으로 설명 본문은 포함되어 있지 않음 |
| 戦闘行動半径 | 전투 행동반경 |
| 配置コスト | 기지항공대 배치 코스트 원시값. 전체 운용 자원 계산 결과는 아님 |

음수 능력치도 있으므로 임의로 0으로 바꾸면 안 됩니다. 5개 장비 분류 코드는 한국어 이름 문자열이 아니라 숫자이므로 종류명 데이터와 연결해야 합니다.

## 현재 번역·장비·시너지 자료의 출처

| 용도 | 원본 | 저장·반영 위치 |
| --- | --- | --- |
| 한국어 장비명·장비 종류명 | [ElectronicObserverEN/Data의 Translations/ko-KR/equipment.json](https://github.com/ElectronicObserverEN/Data/blob/1603c0ac77fd57e7ee44f1ebc31dde84f74cd867/Translations/ko-KR/equipment.json) | `data/fit_metadata.json`의 `equipment.*.name`, `types` |
| 장비 일본어 원명·종류·능력치, 함선 장착 제한 | [kcwiki/kancolle-data의 api/api_start2.json](https://github.com/kcwiki/kancolle-data/blob/7b92cdb8e4601fdec45ddd00489c7c6da9fa346d/api/api_start2.json) | `data/fit_metadata.json`의 장비·함선 메타데이터 |
| 함선·장비 조합별 추가 보너스 규칙 | [ElectronicObserverEN/Data의 Data/FitBonuses.json](https://github.com/ElectronicObserverEN/Data/blob/1603c0ac77fd57e7ee44f1ebc31dde84f74cd867/Data/FitBonuses.json) | `data/fit_bonuses.json` |
| 함선 한국어 이름 | `kinggall/Data/Translations/ko-KR/ship.json` | 기존 `bot.py`의 함선 번역 로더 |

장비 번역은 현재 사용자 포크가 아닌 **ElectronicObserverEN/Data 원본의 한국어 파일**에서 가져온 스냅샷입니다. 위 장비 번역 키는 현재 마스터의 741개 원명에 모두 존재합니다. 일반 장비 중 503종의 표시 이름에 한글이 들어 있으며, 나머지에는 영어 고유명 그대로인 이름도 있으므로 한글이 없다는 이유만으로 미번역이라고 판단하지 않습니다.

`Data/Equipments.json`을 장비 능력치 원본으로 사용한 것은 아닙니다. 현재 `!피트`가 장비에서 사용하는 능력치는 전탐 판정에 필요한 **색적·대공·명중**이며, CSV에는 그 외 기본 능력치도 들어 있습니다. 생성 코드는 `scripts/build_fit_data.py`입니다.

봇 표시명에만 적용하는 보정은 `data/equipment_name_overrides.json`에서 관리합니다. ID 483의 원명 `三式弾改二`는 CSV에서도 확인되며, 원본 한국어 번역의 `3식 改2`에서 빠진 '탄'을 보완해 `3식탄 개2`로 표시합니다. CSV에는 일본어 이름이 들어 있어 한국어 번역의 누락을 자동으로 채워 주는 것은 아닙니다.

## 기존 마스터와 대조

741개의 장비 ID 집합이 현재 `data/fit_metadata.json`의 장비 ID와 완전히 일치합니다. 비교한 게임 마스터는 위 `7b92cdb...` 스냅샷입니다.

- ID·도감 번호, 분류 코드 5개, 능력치·사거리·희귀도·행동반경·배치 코스트 14개, 폐기 자원 4개: **25개 숫자 컬럼에서 전 행 일치**.
- `!피트`의 전탐 판정에 사용하는 분류(`装備種3`)·색적·대공·명중: 불일치 0건.
- 도감 설명은 CSV에서 모두 비어 있어 본문 대조 자료가 없습니다.
- 장비명만 **6건**이 아래처럼 악센트 제거 표기로 다릅니다. 같은 ID이므로 같은 장비입니다.

| 장비 ID | CSV 이름 | 현재 마스터 원명 |
| --- | --- | --- |
| 126 | WG42 (Wurfgerat 42) | WG42 (Wurfgerät 42) |
| 194 | Late 298B | Laté 298B |
| 579 | 13.8cm単装砲 Modele 1927 | 13.8cm単装砲 Modèle 1927 |
| 580 | 55cm三連装魚雷 Modele 1924 | 55cm三連装魚雷 Modèle 1924 |
| 581 | 55cm複合配置五連装魚雷 Modele 1932 | 55cm複合配置五連装魚雷 Modèle 1932 |
| 582 | 20.3cm/50 連装砲 Modele 1931 | 20.3cm/50 連装砲 Modèle 1931 |

중복 이름은 `5inch単装高射砲`(1504·1510), `16inch三連装砲`(1509·1568), `深海5inch連装砲C型`(1588·1627)입니다. 이름을 키로 쓰면 서로 다른 장비를 덮어쓸 수 있으므로 **장비 ID로 연결**합니다.

## できること・別途必要なもの

이 CSV로 기본 능력치·사거리·행동반경·폐기 자원을 안내하는 장비 검색의 기반을 만들 수 있습니다. 일본어 이름과 한국어 번역은 ID를 거쳐 연결할 수 있습니다.

장비 시너지, ★별 개수강화 효과·개수 레시피, 장착 가능한 함선, 보유 수량·보유 장비의 ★·숙련도, 개발·개수·임무 등 입수 방법은 이 27개 컬럼에 포함되지 않습니다. 시너지는 `FitBonuses.json`, 장착 제한은 게임 마스터 등의 별도 자료가 필요합니다. 일반 사용자용 장비 검색을 추가할 때는 심해 장비 157종을 제외합니다.
