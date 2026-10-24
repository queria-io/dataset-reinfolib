{{ config(materialized='table') }}

{# 地域メッシュの順 (1 次メッシュ → 2 次メッシュ) に並べて書き出す。
   商圏分析は地点の周り数 km を緯度経度で引くので、並んでいれば Parquet の行グループ統計で
   数ブロックに絞れる。並んでいないと 1995 年からの全国の地点を読み切ることになり、
   ブラウザの初回で数分かかる。年は同じ場所の中で並べる #}
select * from {{ ref('stg_land_prices') }}
order by
    floor(latitude * 1.5),
    floor(longitude),
    floor(latitude * 12),
    floor(longitude * 8),
    point_id,
    year
