{{ config(materialized='view') }}

-- XGT001 の properties を列に開く。避難場所は点なので、タイルの境界で切られない。
with parsed as (
    select
        from_json(properties, '{
            "common_id": "VARCHAR",
            "prefecture_and_city": "VARCHAR",
            "facility_name_ja": "VARCHAR",
            "address_ja": "VARCHAR",
            "flood_flag": "BOOLEAN",
            "landslide_flag": "BOOLEAN",
            "high_tide_flag": "BOOLEAN",
            "earthquake_flag": "BOOLEAN",
            "tsunami_flag": "BOOLEAN",
            "large_fire_flag": "BOOLEAN",
            "inland_flooding_flag": "BOOLEAN",
            "volcanic_phenomenon_flag": "BOOLEAN",
            "same_address_flag": "BOOLEAN",
            "remarks": "VARCHAR"
        }') as p,
        geometry
    from {{ source('reinfolib_source', 'evacuation_sites') }}
)

select
    p.common_id,
    nullif(p.prefecture_and_city, '') as prefecture_and_city,
    nullif(p.facility_name_ja, '') as facility_name,
    nullif(p.address_ja, '') as address,
    p.flood_flag as for_flood,
    p.landslide_flag as for_landslide,
    p.high_tide_flag as for_storm_surge,
    p.earthquake_flag as for_earthquake,
    p.tsunami_flag as for_tsunami,
    p.large_fire_flag as for_large_fire,
    p.inland_flooding_flag as for_inland_flooding,
    p.volcanic_phenomenon_flag as for_volcano,
    p.same_address_flag as same_address_as_shelter,
    nullif(p.remarks, '') as remarks,
    st_geomfromgeojson(geometry) as geom
from parsed
