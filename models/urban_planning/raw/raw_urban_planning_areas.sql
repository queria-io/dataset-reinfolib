{{ config(materialized='view') }}

select *
from {{ source('reinfolib_source', 'urban_planning_areas') }}
