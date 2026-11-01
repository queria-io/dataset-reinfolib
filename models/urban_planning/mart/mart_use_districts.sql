{{ config(materialized='table') }}

-- 断片は隣のタイルとわずかに重なって返るので、そのまま数えると件数も面積も
-- 過大になる。属性が同じ断片をまとめて 1 つに戻す。
select
    prefecture_code,
    prefecture_name,
    city_code,
    city_name,
    use_district_code,
    use_district,
    decision_date,
    decision_classification,
    decision_maker,
    notice_number,
    first_notice_number,
    first_decision_date,
    floor_area_ratio,
    building_coverage_ratio,
    st_union_agg(geom) as geom
from {{ ref('stg_use_districts') }}
where not st_isempty(geom)
group by all
