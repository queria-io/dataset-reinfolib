{{ config(materialized='table') }}

-- 形状はタイルで切られた断片を結合するより、メッシュコードから組み立てるほうが
-- 正確で軽い。10 桁は 3 次メッシュ (8 桁) + 2 分の 1 + 4 分の 1 の番号で、
-- 分割の番号は 1=南西、2=南東、3=北西、4=北東。
with meshes as (
    select
        mesh_code,
        any_value(landform_code) as landform_code,
        any_value(landform) as landform,
        any_value(liquefaction_level) as liquefaction_level,
        any_value(liquefaction_note) as liquefaction_note
    from {{ ref('stg_liquefaction_tendency') }}
    where length(mesh_code) = 10
    group by mesh_code
),

corners as (
    select
        *,
        substr(mesh_code, 1, 2)::int / 1.5
            + substr(mesh_code, 5, 1)::int / 12.0
            + substr(mesh_code, 7, 1)::int / 120.0
            + (substr(mesh_code, 9, 1)::int in (3, 4))::int / 240.0
            + (substr(mesh_code, 10, 1)::int in (3, 4))::int / 480.0 as lat0,
        100 + substr(mesh_code, 3, 2)::int
            + substr(mesh_code, 6, 1)::int / 8.0
            + substr(mesh_code, 8, 1)::int / 80.0
            + (substr(mesh_code, 9, 1)::int in (2, 4))::int / 160.0
            + (substr(mesh_code, 10, 1)::int in (2, 4))::int / 320.0 as lon0
    from meshes
)

select
    mesh_code,
    left(mesh_code, 8) as mesh3_code,
    landform_code,
    landform,
    liquefaction_level,
    liquefaction_note,
    st_makeenvelope(lon0, lat0, lon0 + 1 / 320.0, lat0 + 1 / 480.0) as geom
from corners
order by mesh_code
