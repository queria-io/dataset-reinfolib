{{ config(materialized='table') }}

-- 断片を区域名ごとに結合して 1 つの区域に戻す。
select
    area_name,
    st_union_agg(geom) as geom
from {{ ref('stg_special_watch_areas') }}
where not st_isempty(geom)
group by all
