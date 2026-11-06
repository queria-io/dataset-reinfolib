# 不動産情報ライブラリ

国土交通省の[不動産情報ライブラリ](https://www.reinfolib.mlit.go.jp/)の API から取得した、全国の不動産取引価格・地価公示・地価調査・鑑定評価書、都市計画決定GISデータ、防災情報、重要土地等調査法の特別注視区域を、SQL で検索・集計できるテーブルにしたデータセットです。地点と区域は座標と形状を持つので、地図に重ねたり空間結合したりできます。

## 出典と利用条件

- 国土交通省「不動産情報ライブラリ」の API を加工して作成しています
- [政府標準利用規約 第2.0版](https://www.reinfolib.mlit.go.jp/help/termsOfUse/)に従います
- このサービスは、国土交通省の不動産情報ライブラリのAPI機能を使用していますが、提供情報の最新性、正確性、完全性等が保証されたものではありません。

## テーブル

| テーブル | 内容 | 行数 |
| --- | --- | ---: |
| `main.mart_trade_prices` | 不動産の取引価格・成約価格（2005 年から） | 5,850,659 |
| `main.mart_land_prices` | 地価公示・地価調査の地点別の価格（1995 年から） | 1,432,153 |
| `main.mart_appraisal_reports` | 地価公示の鑑定評価書（2022 年から） | 258,216 |
| `urban_planning.mart_urban_planning_areas` | 都市計画区域・市街化区域・市街化調整区域 | 2,683 |
| `urban_planning.mart_use_districts` | 用途地域 | 14,139 |
| `urban_planning.mart_location_optimization_plans` | 立地適正化計画の区域 | 1,729 |
| `urban_planning.mart_fire_prevention_districts` | 防火地域・準防火地域 | 926 |
| `urban_planning.mart_district_plans` | 地区計画などの区域 | 6,267 |
| `urban_planning.mart_high_utilization_districts` | 高度利用地区 | 562 |
| `urban_planning.mart_planned_roads` | 都市計画道路と広場 | 4,026 |
| `disaster.mart_liquefaction_tendency` | 液状化の発生傾向（250m メッシュ） | 5,954,133 |
| `disaster.mart_disaster_history` | 土地履歴調査の災害履歴 | 1,348 |
| `disaster.mart_evacuation_sites` | 指定緊急避難場所 | 115,902 |
| `regulation.mart_special_watch_areas` | 重要土地等調査法の特別注視区域 | 143 |

## 使い方

日野市の地価公示（住宅地）の中央値を年ごとに出す:

```sql
SELECT year, count(*) AS points, median(current_price) AS median_yen_per_m2
FROM reinfolib.main.mart_land_prices
WHERE land_price_type = 0          -- 地価公示
  AND city_code = '13212'
  AND use_category = '住宅地'
  AND year >= 2021
GROUP BY ALL
ORDER BY year;
```

## 注意

- 都市計画・防災・規制の区域の範囲は概ねの位置です。重要事項説明や建築確認申請の根拠には使えません
- 都市計画決定GISデータは、地方公共団体が GIS データを出していない区域を含みません。都市計画決定があっても行が無い区域があります
- 地価の `current_price` は円/㎡です。`front_road_width` の単位は `mart_land_prices` が 0.1m、`mart_appraisal_reports` が m で、テーブルによって違います

## main.mart_trade_prices

全国の不動産の取引価格と成約価格です。1 行が 1 件の取引で、2005 年から収録しています。

主なカラム:

- property_type: 種類（宅地、土地、中古マンション等、農地、林地）
- prefecture / municipality / district_name: 都道府県 / 市区町村 / 地区名
- trade_price: 取引価格（総額・円）
- unit_price: 平米単価
- price_per_unit: 坪単価
- area: 面積（平米）
- floor_plan: 間取り
- building_year: 建築年
- structure: 建物の構造
- city_planning: 都市計画
- coverage_ratio / floor_area_ratio: 建ぺい率 / 容積率（%）
- year / quarter: 取得年 / 四半期
- price_category: 価格区分（取引価格 / 成約価格）

## main.mart_land_prices

地価公示・都道府県地価調査の標準地。1行が1地点1年で、1995年から収録しています。

主なカラム:

- land_price_type_name: 地価情報区分（地価公示 / 地価調査）
- year: 価格時点年
- prefecture_name / city_code / municipality_name / location: 都道府県 / 市区町村コード（5 桁） / 市区町村名（政令指定都市の区は「横浜市南区」の形） / 所在地
- current_price / last_year_price / change_rate: 当年価格 / 前年価格 / 対前年変動率
- cadastral_area: 地積（平米）
- use_category / zoning_use_category: 用途区分 / 用途地域
- nearest_station / station_distance: 最寄駅 / 駅からの道路距離
- front_road_width: 前面道路の幅員（0.1m 単位。60 は 6.0m。0 と 9999 は幅員を表さない）
- geom: 地点（EPSG:6668）

## main.mart_appraisal_reports

地価公示の標準地について、不動産鑑定士が作成した鑑定評価書の内容。1行が1通で、
2022年から収録しています。mart_land_prices が「いくらか」を持つのに対し、
こちらは「なぜその価格か」を持ちます。

主なカラム:

- standard_lot_number: 標準地番号（mart_land_prices と同じ表記）
- year / prefecture_code / city_code: 価格時点年 / 都道府県コード / 市区町村コード
- use_category / use_division_code: 用途区分 / 用途区分コード
- appraised_price: この鑑定評価書の評価額（円/平米）
- comparison_method_price / income_method_price / cost_method_price / development_method_price:
  取引事例比較法 / 収益還元法 / 原価法 / 開発法による価格
- comparable_a_* 〜 comparable_e_*: 比準に用いた取引事例5件の取引価格・推定価格・標準価格・査定価格
- income_gross_revenue / income_net_revenue / income_capitalization_rate: 収益価格の算定内訳
- cadastral_area / land_shape / front_road_width: 地積 / 形状 / 前面道路の幅員（m。mart_land_prices は 0.1m 単位）
- area_division / zoning_use_category / building_coverage_ratio / floor_area_ratio: 法令上の規制
- geom: 標準地の位置（EPSG:6668）

1つの標準地につき2通の鑑定評価書があり、評価額は評価書ごとに異なります。appraised_price も
published_price も鑑定評価書に書かれた値で、公表される公示価格とは一致しないことがあるため、
公表値は mart_land_prices の current_price を参照してください。適用していない鑑定評価手法は
価格が0で入ります。

mart_land_prices と結合するときは year・prefecture_code・standard_lot_number の3つで
突き合わせます。標準地番号が一意なのは都道府県の中だけで、mart_land_prices は同じ地点を
年ごとに持つためです。収録は地価公示だけなので、mart_land_prices 側は land_price_type = 0
に絞ります。1地点に評価書が2通あるので、結合は1対2になります。

## urban_planning.mart_urban_planning_areas

都市計画区域・市街化区域・市街化調整区域のポリゴン。1行が市区町村と区域区分の組です。
`ST_Contains` で地点がどの区域に入るかを判定でき、地点を持つ mart_land_prices と
空間結合すると区域区分ごとの地価が出せます。

主なカラム:

- prefecture_name / city_code / city_name: 都道府県 / 市区町村コード / 市区町村名
- kubun_id: 区分コード（21=都市計画区域、22=市街化区域、23=市街化調整区域）
- area_classification: 区域区分
- decision_date / notice_number: 設定年月日 / 告示番号
- first_decision_date / first_notice_number: 当初決定日 / 当初告示番号
- geom: 区域のポリゴン（EPSG:6668）

原典は区域を細かく分割した形で配信しているため、同じ市区町村・同じ区域区分のものを
1つのポリゴンに結合して収録しています。設定年月日と告示番号は原典が和暦・西暦・略記の
混在した文字列で公開しているため、そのままの形で入っています。

## urban_planning スキーマのほかのテーブル

令和7年度の都市計画決定GISデータです。mart_urban_planning_areas と同じく、原典がタイルの境界で
切って配信する区域を、属性が同じものごとに 1 つのポリゴン（都市計画道路は線）に結合しています。
地方公共団体が GIS データを出していない区域は入っていません。

- mart_use_districts: 用途地域。用途地域の種類、容積率・建蔽率（%、数値）
- mart_location_optimization_plans: 立地適正化計画の区域（立地適正化計画区域・居住誘導区域・都市機能誘導区域など）
- mart_fire_prevention_districts: 防火地域・準防火地域
- mart_district_plans: 地区計画などの区域。計画名・計画区分
- mart_high_utilization_districts: 高度利用地区。地区名
- mart_planned_roads: 都市計画道路の線と広場の範囲。原典に路線名は無い
設定年月日と告示番号は、原典が和暦・西暦・略記の混在した文字列で公開しているため、そのままの形で入っています。

## disaster スキーマ

- mart_liquefaction_tendency: 地形区分に基づく液状化の発生傾向（国土交通省都市局）。250m メッシュごとの微地形区分と液状化の発生傾向。
  ポリゴンはメッシュコードから組み立てています。mesh3_code（先頭 8 桁）で 1km メッシュの統計と結合できます
- mart_disaster_history: 国土調査（土地履歴調査）の災害履歴。浸水・がけ崩れ・液状化・津波などの記録で、
  形状は点・線・面が混ざります。発生年月日は分からない部分が 0 の 8 桁の文字列（disaster_date_text）で、
  年と年月日が分かるものだけ disaster_year・disaster_date に入れています
- mart_evacuation_sites: 国土地理院の指定緊急避難場所。洪水・地震・津波など災害の種類ごとの対応フラグと経度・緯度。
  city_code は共通 ID の 2〜6 桁目です

液状化の発生傾向は、地形が示す一般的な地盤の性質から見た相対的な傾向で、特定の地震や震度を想定した危険度ではありません。メッシュの中で面積の大きい地形で分類しているので、埋立地や盛土などの人工改変地の細かい位置は反映されていません。傾向が弱いメッシュでも、その中の人工改変地では液状化が起きることがあります。水部（河道・湖沼）は原則として評価していません。

災害履歴は土地履歴調査を実施した地域だけの記録で、全国を網羅していません。記録が無い場所には、調査していない場所が含まれます。

指定緊急避難場所は、対応する災害が避難場所ごとに違うので、災害の種類で絞ってから使ってください。配信データは原典の更新をいつも反映しているわけではないので、最新の状況は市町村に確認してください。

## regulation スキーマ

- mart_special_watch_areas: 重要土地等調査法に基づく特別注視区域（内閣府）のポリゴン。区域内の一定面積以上の土地・建物の売買などの契約は、売主と買主の双方が内閣総理大臣に事前に届け出る必要があります。1 行が 1 つの区域名です。正式な範囲は内閣府の公示で確認してください

## 更新

```bash
uv sync
bash scripts/build.sh
```
