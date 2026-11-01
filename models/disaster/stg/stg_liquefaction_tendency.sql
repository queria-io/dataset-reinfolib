{{ config(materialized='view') }}

-- XKT025 の properties を列に開く。1 行が 250m メッシュ 1 つ（タイルの境界にかかる
-- メッシュは隣のタイルにも入る）。
with parsed as (
    select
        from_json(properties, '{
            "mesh_code": "VARCHAR",
            "topographic_classification_code": "INTEGER",
            "topographic_classification_name_ja": "VARCHAR",
            "liquefaction_tendency_level": "INTEGER",
            "note": "VARCHAR"
        }') as p
    from {{ source('reinfolib_source', 'liquefaction_tendency') }}
)

select
    p.mesh_code,
    p.topographic_classification_code as landform_code,
    nullif(p.topographic_classification_name_ja, '') as landform,
    p.liquefaction_tendency_level as liquefaction_level,
    nullif(p.note, '') as liquefaction_note
from parsed
