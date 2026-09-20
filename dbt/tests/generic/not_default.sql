{#
  ClickHouse's answer to not_null. A column that is not Nullable cannot hold a NULL, so
  not_null on it can never fail: what a broken decode or an unmatched join leaves behind is
  the TYPE DEFAULT ('' for a String, 1970-01-01 for a DateTime, 0 for a number). This test
  fails on those. Use it only where the default is never a legitimate value; on a Nullable
  column use not_null, which works there.
#}
{% test not_default(model, column_name) %}

select {{ column_name }}
from {{ model }}
where {{ column_name }} = defaultValueOfArgumentType({{ column_name }})

{% endtest %}
