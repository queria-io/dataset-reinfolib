{{ config(materialized='view') }}

-- XKT002 の properties を列に開く。geometry はタイル境界で切り出された断片で、
-- 無効なリングを含むものがあるので ST_MakeValid を通してから mart で結合する。
with parsed as (
    select
        from_json(properties, '{
            "prefecture": "VARCHAR",
            "city_code": "VARCHAR",
            "city_name": "VARCHAR",
            "youto_id": "INTEGER",
            "use_area_ja": "VARCHAR",
            "u_floor_area_ratio_ja": "VARCHAR",
            "u_building_coverage_ratio_ja": "VARCHAR",
            "decision_date": "VARCHAR",
            "decision_classification": "VARCHAR",
            "decision_maker": "VARCHAR",
            "notice_number": "VARCHAR",
            "notice_number_s": "VARCHAR",
            "first_decision_date": "VARCHAR"
        }') as p,
        geometry
    from {{ source('reinfolib_source', 'use_districts') }}
),

cols as (
    select
        nullif(p.prefecture, '') as prefecture_name,
        nullif(p.city_code, '') as city_code,
        nullif(p.city_name, '') as city_name,
        p.youto_id as use_district_code,
        nullif(p.use_area_ja, '') as use_district,
        nullif(p.u_floor_area_ratio_ja, '') as floor_area_ratio_text,
        nullif(p.u_building_coverage_ratio_ja, '') as building_coverage_ratio_text,
        nullif(p.decision_date, '') as decision_date,
        nullif(p.decision_classification, '') as decision_classification,
        nullif(p.decision_maker, '') as decision_maker,
        nullif(p.notice_number, '') as notice_number,
        nullif(p.notice_number_s, '') as first_notice_number,
        nullif(p.first_decision_date, '') as first_decision_date,
        st_collectionextract(st_makevalid(st_geomfromgeojson(geometry)), 3) as geom
    from parsed
)

select
    left(city_code, 2) as prefecture_code,
    * exclude (floor_area_ratio_text, building_coverage_ratio_text),
    try_cast(replace(floor_area_ratio_text, '%', '') as double)::integer as floor_area_ratio,
    try_cast(replace(building_coverage_ratio_text, '%', '') as double)::integer as building_coverage_ratio
from cols
