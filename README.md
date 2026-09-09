## データ出典

[国土交通省 不動産情報ライブラリ](https://www.reinfolib.mlit.go.jp/)の API から取得した、
全国の不動産取引価格・地価公示および都市計画決定GISデータです。

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
- geom: 地点（EPSG:6668）

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

## クレジット

このサービスは、国土交通省の不動産情報ライブラリのAPI機能を使用していますが、提供情報の最新性、正確性、完全性等が保証されたものではありません。

## ライセンス

[政府標準利用規約 第2.0版](https://www.reinfolib.mlit.go.jp/help/termsOfUse/)
