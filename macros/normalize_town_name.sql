{# 町の名前を突き合わせるためにそろえる。取引の地区名と国勢調査の町丁目名で書き方が違うところ:
   「ヶ」と「ケ」、頭の「大字」「字」、町丁目名の末尾の「一丁目」「1丁」 #}
{% macro normalize_town_name(col) -%}
regexp_replace(
    regexp_replace(
        translate({{ col }}, 'ヶｹ', 'ケケ'),
        '^(大字|字)', ''
    ),
    '[０-９0-9一二三四五六七八九十]+丁目?$', ''
)
{%- endmacro %}
