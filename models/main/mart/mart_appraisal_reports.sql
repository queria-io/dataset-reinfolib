{{ config(materialized='table') }}

select * from {{ ref('stg_appraisal_reports') }}
