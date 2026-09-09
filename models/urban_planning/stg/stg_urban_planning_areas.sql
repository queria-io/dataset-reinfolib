{{ config(materialized='view') }}

-- XKT001 の geometry はタイル境界で切り出された断片で、無効なリングを含むものが
-- 5% ほどある。ST_MakeValid が返す GEOMETRYCOLLECTION から面だけを取り出して、
-- mart での結合に渡せる形にそろえる。
select
    prefecture as prefecture_name,
    left(city_code, 2) as prefecture_code,
    city_code,
    city_name,
    kubun_id,
    area_classification_ja as area_classification,
    nullif(decision_date, '') as decision_date,
    nullif(decision_classification, '') as decision_classification,
    nullif(decision_maker, '') as decision_maker,
    nullif(notice_number, '') as notice_number,
    nullif(notice_number_s, '') as first_notice_number,
    nullif(first_decision_date, '') as first_decision_date,
    st_collectionextract(st_makevalid(st_geomfromgeojson(geometry)), 3) as geom
from {{ ref('raw_urban_planning_areas') }}
