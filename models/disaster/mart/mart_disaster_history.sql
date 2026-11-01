{{ config(materialized='table') }}

-- 面と線はタイルの境界で切られて返るので、属性が同じ断片を結合して 1 行に戻す。
select
    disaster_type_code,
    disaster_type,
    disaster_date_text,
    disaster_year,
    disaster_date,
    source_document,
    st_union_agg(geom) as geom
from {{ ref('stg_disaster_history') }}
where not st_isempty(geom)
group by all
