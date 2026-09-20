{#
  Uniqueness of a combination of columns. Written here instead of pulling in dbt_utils:
  one small macro is not worth a package download on every `dbt deps`.
  Aggregates the bare keys only: carrying extra columns through a GROUP BY of ~860k
  distinct keys is what made the first duplicates check use 661 MiB.
#}
{% test unique_combination(model, columns) %}

select {{ columns | join(', ') }}, count() as copies
from {{ model }}
group by {{ columns | join(', ') }}
having copies > 1

{% endtest %}
