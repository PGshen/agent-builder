"""MCP 配置里敏感字段（stdio 的 env、sse/http 的 headers）的脱敏 / 回填逻辑。

只脱敏这两个约定的 dict 字段的 value（key 不脱敏，方便用户在编辑表单里看到有哪些
env/header 名，无需重新输入 key 就能确认要不要更新某个 value）。
"""

MASK_SENTINEL = "********"

_SECRET_DICT_FIELDS = ("env", "headers")


def mask_config(config: dict) -> dict:
    masked = dict(config)
    for field in _SECRET_DICT_FIELDS:
        value = masked.get(field)
        if isinstance(value, dict):
            masked[field] = {key: MASK_SENTINEL for key in value}
    return masked


def merge_secret_fields(old_config: dict, new_config: dict) -> dict:
    """把 `new_config` 里等于 MASK_SENTINEL 的 value 替换回 `old_config` 里的原值（未修改则不必重新输入）。"""
    merged = dict(new_config)
    for field in _SECRET_DICT_FIELDS:
        new_value = merged.get(field)
        if not isinstance(new_value, dict):
            continue
        old_value = old_config.get(field)
        old_value = old_value if isinstance(old_value, dict) else {}
        merged[field] = {
            key: (old_value[key] if val == MASK_SENTINEL and key in old_value else val)
            for key, val in new_value.items()
        }
    return merged
