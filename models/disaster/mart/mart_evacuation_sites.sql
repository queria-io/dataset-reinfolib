{{ config(materialized='table') }}

-- 共通 ID は「E + 市区町村コード 5 桁 + 連番」。境界上の点は隣のタイルにも
-- 入って返ることがあるので、共通 ID ごとに 1 行に絞る。
select distinct on (common_id)
    common_id,
    substr(common_id, 2, 2) as prefecture_code,
    substr(common_id, 2, 5) as city_code,
    * exclude (common_id, geom),
    st_x(geom) as longitude,
    st_y(geom) as latitude,
    geom
from {{ ref('stg_evacuation_sites') }}
order by common_id
