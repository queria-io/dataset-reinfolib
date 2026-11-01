{{ config(materialized='view') }}

-- XST001 の properties を列に開く。形状は災害の種類によって点・線・面が混ざる。
-- 年月日は 8 桁の文字列で、分からない部分が 0 で埋まっている（19810000 など）。
select
    disaster_type_code,
    disaster_type,
    disaster_date_text,
    nullif(try_cast(left(disaster_date_text, 4) as integer), 0) as disaster_year,
    try_strptime(disaster_date_text, '%Y%m%d')::date as disaster_date,
    source_document,
    geom
from (
    select
        nullif(p.disastertype_code, '') as disaster_type_code,
        nullif(p.disaster_name_ja, '') as disaster_type,
        nullif(p.disaster_date, '') as disaster_date_text,
        nullif(p.disaster_source, '') as source_document,
        st_makevalid(st_geomfromgeojson(geometry)) as geom
    from (
        select
            from_json(properties, '{
                "disastertype_code": "VARCHAR",
                "disaster_name_ja": "VARCHAR",
                "disaster_date": "VARCHAR",
                "disaster_source": "VARCHAR"
            }') as p,
            geometry
        from {{ source('reinfolib_source', 'disaster_history') }}
    )
)
