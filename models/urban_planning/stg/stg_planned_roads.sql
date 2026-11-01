{{ config(materialized='view') }}

-- XKT030 の properties を列に開く。geometry はタイル境界で切り出された断片で、
-- 無効なリングを含むものがあるので ST_MakeValid を通してから mart で結合する。
with parsed as (
    select
        from_json(properties, '{
            "prefecture": "VARCHAR",
            "city_code": "VARCHAR",
            "city_name": "VARCHAR",
            "kubun_id": "INTEGER",
            "planning_road_ja": "VARCHAR",
            "decision_type_ja": "VARCHAR",
            "decision_date": "VARCHAR",
            "decision_maker": "VARCHAR",
            "notice_number": "VARCHAR",
            "notice_number_s": "VARCHAR",
            "first_decision_date": "VARCHAR"
        }') as p,
        geometry
    from {{ source('reinfolib_source', 'planned_roads') }}
),

cols as (
    select
        nullif(p.prefecture, '') as prefecture_name,
        nullif(p.city_code, '') as city_code,
        nullif(p.city_name, '') as city_name,
        p.kubun_id as kubun_id,
        nullif(p.planning_road_ja, '') as road_type,
        nullif(p.decision_type_ja, '') as decision_classification,
        nullif(p.decision_date, '') as decision_date,
        nullif(p.decision_maker, '') as decision_maker,
        nullif(p.notice_number, '') as notice_number,
        nullif(p.notice_number_s, '') as first_notice_number,
        nullif(p.first_decision_date, '') as first_decision_date,
        st_makevalid(st_geomfromgeojson(geometry)) as geom
    from parsed
)

select
    left(city_code, 2) as prefecture_code,
    *
from cols
