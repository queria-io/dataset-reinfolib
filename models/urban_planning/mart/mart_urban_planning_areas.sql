{{ config(materialized='table') }}

-- 断片は隣のタイルとわずかに重なって返るので、そのまま数えると件数も面積も
-- 過大になる。属性が同じ断片をまとめて 1 つの区域に戻す。
select
    prefecture_code,
    prefecture_name,
    city_code,
    city_name,
    kubun_id,
    area_classification,
    decision_date,
    decision_classification,
    decision_maker,
    notice_number,
    first_notice_number,
    first_decision_date,
    st_union_agg(geom) as geom
from {{ ref('stg_urban_planning_areas') }}
group by all
