{{ config(materialized='view') }}

select *
from {{ source('reinfolib_source', 'appraisal_reports') }}
