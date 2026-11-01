{{ config(materialized='view') }}

-- XNT001 は区域名だけを持つ。geometry はタイル境界で切り出された断片。
select
    nullif(json_extract_string(properties, '$.NAME'), '') as area_name,
    st_collectionextract(st_makevalid(st_geomfromgeojson(geometry)), 3) as geom
from {{ source('reinfolib_source', 'special_watch_areas') }}
