## データ出典

[国土交通省 不動産情報ライブラリ](https://www.reinfolib.mlit.go.jp/)の API から取得した、
全国の不動産取引価格・地価公示・鑑定評価書、都市計画決定GISデータ、防災情報、重要土地等調査法の特別注視区域です。

## テーブル: mart_trade_prices

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

## テーブル: mart_land_prices

地価公示・都道府県地価調査の標準地。1行が1地点1年で、1995年から収録しています。

主なカラム:

- land_price_type_name: 地価情報区分（地価公示 / 地価調査）
- year: 価格時点年
- prefecture_name / municipality_name / location: 都道府県 / 市区町村 / 所在地
- current_price / last_year_price / change_rate: 当年価格 / 前年価格 / 対前年変動率
- cadastral_area: 地積（平米）
- use_category / zoning_use_category: 用途区分 / 用途地域
- nearest_station / station_distance: 最寄駅 / 駅からの道路距離
- front_road_width: 前面道路の幅員（0.1m 単位。60 は 6.0m。0 と 9999 は幅員を表さない）
- geom: 地点（EPSG:6668）

## テーブル: mart_appraisal_reports

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

## テーブル: mart_urban_planning_areas

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

## 都市計画決定GISデータ（urban_planning スキーマ）のほかのテーブル

令和7年度の都市計画決定GISデータです。mart_urban_planning_areas と同じく、原典がタイルの境界で
切って配信する区域を、属性が同じものごとに 1 つのポリゴン（都市計画道路は線）に結合しています。
地方公共団体が GIS データを出していない区域は入っていません。

- mart_use_districts: 用途地域。用途地域の種類、容積率・建蔽率（%、数値）
- mart_location_optimization_plans: 立地適正化計画の区域（立地適正化計画区域・居住誘導区域・都市機能誘導区域など）
- mart_fire_prevention_districts: 防火地域・準防火地域
- mart_district_plans: 地区計画などの区域。計画名・計画区分
- mart_high_utilization_districts: 高度利用地区。地区名
- mart_planned_roads: 都市計画道路の線と広場の範囲。原典に路線名は無い

## テーブル: disaster スキーマ（防災情報）

- mart_liquefaction_tendency: 地形区分に基づく液状化の発生傾向（国土交通省都市局）。250m メッシュごとの微地形区分と液状化の発生傾向。
  ポリゴンはメッシュコードから組み立てています。mesh3_code（先頭 8 桁）で 1km メッシュの統計と結合できます
- mart_disaster_history: 国土調査（土地履歴調査）の災害履歴。浸水・がけ崩れ・液状化・津波などの記録で、
  形状は点・線・面が混ざります。発生年月日は分からない部分が 0 の 8 桁の文字列（disaster_date_text）で、
  年と年月日が分かるものだけ disaster_year・disaster_date に入れています
- mart_evacuation_sites: 国土地理院の指定緊急避難場所。洪水・地震・津波など災害の種類ごとの対応フラグと経度・緯度。
  city_code は共通 ID の 2〜6 桁目です

## テーブル: regulation スキーマ

- mart_special_watch_areas: 重要土地等調査法に基づく特別注視区域（内閣府）のポリゴン

これらの範囲はいずれも概ねの位置で、重要事項説明や建築確認申請の根拠には使えません。

## クレジット

このサービスは、国土交通省の不動産情報ライブラリのAPI機能を使用していますが、提供情報の最新性、正確性、完全性等が保証されたものではありません。

## ライセンス

[政府標準利用規約 第2.0版](https://www.reinfolib.mlit.go.jp/help/termsOfUse/)
