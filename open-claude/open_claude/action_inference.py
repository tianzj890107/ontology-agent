"""动作（Action）元模型推断与九字段输出纯函数。

动作是独立元模型，正式输出 ``actions.csv`` 严格使用《本体元模型模板
v.0.0.1》动作 Sheet 的九个字段：

``动作编码, 动作名称, 动作英文名, 动作描述, 动作类型, 业务对象编码, 协议, 服务节点, 服务名称``

识别策略是“明确证据优先、合理推断兜底”：没有 API、接口、服务、前端按钮或
业务操作文档等明确证据时，允许根据已确认的业务对象和逻辑实体生成可展示的
演示动作，不得因为证据不完整直接输出空动作表。

本模块只做确定性的解析、推断、去重、排序和编码，不访问任何全局任务/run
存储；当前任务/run 隔离由调用方保证（只传入当前任务的 BO/LE 数据）。
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

# 模板“动作”Sheet 的正式九字段，顺序不能改变。
ACTION_FIELDS = (
    "动作编码", "动作名称", "动作英文名", "动作描述", "动作类型",
    "业务对象编码", "协议", "服务节点", "服务名称",
)

# 第一版动作类型只使用新增/修改/删除。
ACTION_TYPES = ("新增", "修改", "删除")

# 动作编码：ACT + 6 位流水码，例如 ACT000001。
ACTION_CODE_PATTERN = re.compile(r"^ACT\d{6}$")

# 英文枚举映射（仅内部使用；最终写入模板/CSV 时使用中文）。
ACTION_TYPE_ALIASES = {
    "新增": "新增", "CREATE": "新增", "CREATED": "新增", "INSERT": "新增", "ADD": "新增",
    "修改": "修改", "UPDATE": "修改", "UPDATED": "修改", "EDIT": "修改", "MODIFY": "修改",
    "删除": "删除", "DELETE": "删除", "DELETED": "删除", "REMOVE": "删除", "REMOVED": "删除",
    "CANCEL": "删除", "CANCELLED": "删除", "VOID": "删除", "INVALIDATE": "删除",
}

# BO 级动作的默认动词与英文枚举。
BO_VERBS = {
    "新增": ("创建", "create"),
    "修改": ("修改", "update"),
    "删除": ("删除", "delete"),
}
# LE 级动作的默认动词与英文枚举（按模板示例：新增采购订单行）。
LE_VERBS = {
    "新增": ("新增", "add"),
    "修改": ("修改", "update"),
    "删除": ("删除", "delete"),
}

# 名称开头常见业务动词；生成动作名称时避免“创建创建订单”式重复。
_LEADING_VERBS = (
    "创建", "新增", "修改", "更新", "删除", "作废", "取消", "提交", "审批",
    "维护", "登记", "导入", "导出", "启用", "停用", "关闭", "打开", "确认", "发布",
)

# 明显可独立操作、值得生成 LE 级动作的实体名称关键词（按 BO 内顺序优先选择）。
_OPERABLE_LE_KEYWORDS = (
    "明细", "行项目", "项目行", "订单行", "分录", "条目", "明细行",
    "地址", "联系人", "附件", "配置", "参数", "收款", "付款",
)
# 明显属于纯技术/派生/关系载体的实体名称关键词，不默认生成三套动作。
_TECHNICAL_LE_KEYWORDS = (
    "日志", "流水", "快照", "缓存", "映射", "关联表", "中间表", "临时表",
    "历史", "备份", "视图", "队列", "任务表", "字典项", "码值",
)


def _text(value: Any) -> str:
    return str(value or "").strip().lstrip("\ufeff")


def _nullable(value: Any) -> str:
    text = _text(value)
    return "" if text.upper() in {"NONE", "NULL", "N/A", "NA", "-"} else text


def normalize_action_type(value: Any) -> str:
    """把来源动作类型归一化为新增/修改/删除之一；无法识别时返回空串。"""
    raw = _text(value).upper()
    return ACTION_TYPE_ALIASES.get(raw, ACTION_TYPE_ALIASES.get(_text(value), ""))


def parse_action_sheet(rows: Any) -> list[dict[str, str]]:
    """按表头读取动作 Sheet，返回九字段字典列表。

    兼容：
    - 表头顺序变化（按列名读取）；
    - 只有表头、空数据、空白行和尾部空列；
    - 旧模板没有动作 Sheet（传入空/None）时返回空列表；
    - UTF-8 BOM；
    - 表头包含“动作”Sheet 之外的多余列（忽略多余列）。
    任何行都只输出九个字段；缺失字段输出空字符串。
    """
    if not rows:
        return []
    header: list[str] = []
    body: list[Sequence[str]] = []
    if isinstance(rows, Mapping):
        rows = [rows]
    values = list(rows)
    if not values:
        return []
    first = values[0]
    if isinstance(first, Mapping):
        header = [_text(key) for key in first.keys()]
        body = values
        index = {name: position for position, name in enumerate(header)}
    else:
        header = [_text(value) for value in first]
        body = values[1:]
        index = {name: position for position, name in enumerate(header)}
    result: list[dict[str, str]] = []
    for row in body:
        if isinstance(row, Mapping):
            item = {field: _nullable(row.get(field)) for field in ACTION_FIELDS}
        else:
            cells = [_text(value) for value in row]
            item = {}
            for field in ACTION_FIELDS:
                position = index.get(field)
                item[field] = _nullable(cells[position]) if position is not None and position < len(cells) else ""
        if not any(item.values()):
            continue
        result.append(item)
    return result


def _strip_leading_verb(name: str, verb: str) -> str:
    text = _text(name)
    for leading in _LEADING_VERBS:
        if text.startswith(leading):
            text = text[len(leading):].strip()
            break
    if verb and text.startswith(verb):
        text = text[len(verb):].strip()
    return text or _text(name)


def _pascal_parts(value: str) -> list[str]:
    parts = re.split(r"[^A-Za-z0-9]+", _text(value))
    parts = [part for part in parts if part]
    if not parts:
        return []
    words: list[str] = []
    for part in parts:
        for token in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", part):
            words.append(token)
    return [word for word in words if word] or [parts[0]]


def _lower_camel(verb: str, name: str, english: str = "", code: str = "") -> str:
    source = english or code or name
    parts = _pascal_parts(source)
    if not parts:
        parts = ["Action", code or "Action"]
    joined = "".join(part[:1].upper() + part[1:] for part in parts)
    joined = re.sub(r"[^A-Za-z0-9]", "", joined)
    return verb + joined[:1].upper() + joined[1:] if joined else verb


def action_name_for(object_name: str, action_type: str, *, le_level: bool = False) -> str:
    """生成自然可读的动作名称：动词 + 业务对象/逻辑实体名称。"""
    normalized = normalize_action_type(action_type)
    if normalized not in ACTION_TYPES:
        return ""
    verbs = LE_VERBS if le_level else BO_VERBS
    verb, _english = verbs[normalized]
    stem = _strip_leading_verb(object_name, verb)
    return f"{verb}{stem}"


def english_action_name(object_name: str, action_type: str, *,
                        object_english: str = "", object_code: str = "",
                        le_level: bool = False) -> str:
    """生成稳定的 lowerCamelCase 英文动作名，不得输出空值。"""
    normalized = normalize_action_type(action_type)
    if normalized not in ACTION_TYPES:
        return ""
    verbs = LE_VERBS if le_level else BO_VERBS
    _verb, english_verb = verbs[normalized]
    return _lower_camel(english_verb, object_name, object_english, object_code)


def _demo_description(action_type: str, object_name: str, bo_code: str,
                      le_name: str = "", bo_name: str = "") -> str:
    normalized = normalize_action_type(action_type)
    verbs = {"新增": "新增", "修改": "修改", "删除": "删除"}
    verb = verbs.get(normalized, "")
    if le_name:
        target = f"{le_name}逻辑实体数据"
        scope = f"在{bo_name or object_name}业务对象中"
    else:
        target = f"{object_name}业务对象"
        scope = ""
    effect = {
        "新增": "创建新的业务数据记录",
        "修改": "更新已有业务数据记录",
        "删除": "移除或作废业务数据记录",
    }.get(normalized, "执行业务操作")
    return (f"{scope}{verb}{target}，{effect}。"
            f"该动作为根据当前业务对象及逻辑实体结构推断的演示候选动作，"
            f"具体服务实现需结合实际系统确认。").strip()


def infer_bo_actions(business_object: Mapping[str, Any]) -> list[dict[str, str]]:
    """为单个业务对象生成新增/修改/删除三个 BO 级演示动作。"""
    code = _nullable(business_object.get("业务对象编码"))
    name = _text(business_object.get("业务对象名称")) or code
    english = _nullable(business_object.get("业务对象英文名"))
    if not code or not name:
        return []
    actions: list[dict[str, str]] = []
    for action_type in ACTION_TYPES:
        actions.append({
            "动作编码": "",
            "动作名称": action_name_for(name, action_type),
            "动作英文名": english_action_name(name, action_type, object_english=english, object_code=code),
            "动作描述": _demo_description(action_type, name, code),
            "动作类型": action_type,
            "业务对象编码": code,
            "协议": "",
            "服务节点": "",
            "服务名称": "",
        })
    return actions


def _is_technical_entity(logical_entity: Mapping[str, Any]) -> bool:
    name = _text(logical_entity.get("逻辑实体名称") or logical_entity.get("逻辑实体编码"))
    lowered = name.lower()
    return any(keyword.lower() in lowered for keyword in _TECHNICAL_LE_KEYWORDS)


def _le_is_operable(logical_entity: Mapping[str, Any]) -> bool:
    name = _text(logical_entity.get("逻辑实体名称") or logical_entity.get("逻辑实体编码"))
    lowered = name.lower()
    if _is_technical_entity(logical_entity):
        return False
    return any(keyword.lower() in lowered for keyword in _OPERABLE_LE_KEYWORDS)


def select_le_candidates(logical_entities: Sequence[Mapping[str, Any]],
                         limit: int = 6) -> list[Mapping[str, Any]]:
    """选择值得生成 LE 级动作的代表性逻辑实体。

    优先选择名称明显可独立操作（明细、行、地址、联系人、附件、配置等）的
    实体，再补充主逻辑实体；明显的纯技术/派生实体不默认生成三套动作。
    """
    entities = [entity for entity in logical_entities if isinstance(entity, Mapping)]
    # 明显的纯技术/派生/关系载体实体不默认生成三套动作，直接排除。
    entities = [entity for entity in entities if not _is_technical_entity(entity)]
    operable = [entity for entity in entities if _le_is_operable(entity)]
    rest = [entity for entity in entities if entity not in operable]
    main = [entity for entity in rest
            if _text(entity.get("是否主逻辑实体")).upper() == "Y"]
    others = [entity for entity in rest if entity not in main]
    ordered = operable + main + others
    return ordered[:limit]


def infer_le_actions(logical_entity: Mapping[str, Any], bo_code: str,
                     bo_name: str = "") -> list[dict[str, str]]:
    """为单个逻辑实体生成 LE 级演示动作，动作引用所属业务对象编码。

    模板没有逻辑实体编码字段：LE 名称写入动作名称/描述，不新增 LE 编码列。
    """
    le_name = _text(logical_entity.get("逻辑实体名称"))
    le_english = _nullable(logical_entity.get("逻辑实体英文名"))
    le_code = _text(logical_entity.get("逻辑实体编码"))
    if not le_name or not bo_code:
        return []
    actions: list[dict[str, str]] = []
    for action_type in ACTION_TYPES:
        actions.append({
            "动作编码": "",
            "动作名称": action_name_for(le_name, action_type, le_level=True),
            "动作英文名": english_action_name(le_name, action_type, object_english=le_english,
                                              object_code=le_code, le_level=True),
            "动作描述": _demo_description(action_type, le_name, bo_code, le_name=le_name, bo_name=bo_name),
            "动作类型": action_type,
            "业务对象编码": bo_code,
            "协议": "",
            "服务节点": "",
            "服务名称": "",
        })
    return actions


def collect_bo_le(logical_entities: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """建立业务对象编码 -> 逻辑实体列表的归属关系（仅统计显式归属）。"""
    index: dict[str, list[Mapping[str, Any]]] = {}
    for entity in logical_entities:
        if not isinstance(entity, Mapping):
            continue
        bo_code = _nullable(entity.get("业务对象编码"))
        if bo_code:
            index.setdefault(bo_code, []).append(entity)
    return index


def normalize_explicit_actions(actions: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """把来源明确的动作归一化为九字段字典（动作类型转中文，缺失字段置空）。"""
    result: list[dict[str, str]] = []
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        item = {field: _nullable(action.get(field)) for field in ACTION_FIELDS}
        item["动作类型"] = normalize_action_type(action.get("动作类型"))
        if not any(item.values()):
            continue
        result.append(item)
    return result


def dedupe_actions(actions: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """按 (业务对象编码, 动作类型, 动作名称) 去重，保留首次出现的动作。"""
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, str]] = []
    for action in actions:
        key = (_nullable(action.get("业务对象编码")),
               normalize_action_type(action.get("动作类型")),
               _text(action.get("动作名称")))
        if not key[0] or not key[1] or not key[2]:
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(action))
    return result


_ACTION_TYPE_ORDER = {name: index for index, name in enumerate(ACTION_TYPES)}


def sort_actions(actions: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """稳定排序：业务对象编码 -> 动作类型（新增/修改/删除）-> 动作名称。"""
    return sorted(
        (dict(action) for action in actions),
        key=lambda action: (_text(action.get("业务对象编码")),
                            _ACTION_TYPE_ORDER.get(normalize_action_type(action.get("动作类型")), 99),
                            _text(action.get("动作名称"))),
    )


def assign_action_codes(actions: Iterable[Mapping[str, str]], start: int = 1) -> list[dict[str, str]]:
    """按稳定顺序分配 ACT + 6 位流水码；已存在合法编码的动作保持不变。"""
    result: list[dict[str, str]] = []
    counter = max(start, 1)
    used: set[str] = set()
    for action in sort_actions(actions):
        item = dict(action)
        code = _text(item.get("动作编码"))
        if ACTION_CODE_PATTERN.fullmatch(code) and code not in used:
            used.add(code)
            result.append(item)
            continue
        while f"ACT{counter:06d}" in used:
            counter += 1
        item["动作编码"] = f"ACT{counter:06d}"
        used.add(item["动作编码"])
        counter += 1
        result.append(item)
    return result


def infer_actions(business_objects: Sequence[Mapping[str, Any]],
                  logical_entities: Sequence[Mapping[str, Any]] | None = None,
                  explicit_actions: Iterable[Mapping[str, Any]] | None = None,
                  *, le_limit: int = 6, max_total: int = 50) -> list[dict[str, str]]:
    """生成当前任务的最终动作清单。

    规则：
    - 没有业务对象时不生成动作；
    - 每个 BO 生成新增/修改/删除三个 BO 级动作；
    - 每个 BO 选择不超过 ``le_limit`` 个代表性 LE，生成 LE 级动作；
    - 明确证据动作优先于推断动作，同语义不重复；
    - 总量不超过 ``max_total``（优先保留 BO 级动作）；
    - 结果按稳定顺序分配 ACT 编码，重复执行结果稳定。
    """
    bo_rows = [bo for bo in business_objects if isinstance(bo, Mapping)]
    if not bo_rows:
        return []
    explicit = normalize_explicit_actions(explicit_actions or [])
    bo_level: list[dict[str, str]] = []
    le_level: list[dict[str, str]] = []
    le_index = collect_bo_le(logical_entities or [])
    for bo in bo_rows:
        bo_code = _nullable(bo.get("业务对象编码"))
        bo_name = _text(bo.get("业务对象名称"))
        if not bo_code:
            continue
        bo_level.extend(infer_bo_actions(bo))
        for le in select_le_candidates(le_index.get(bo_code, []), limit=le_limit):
            le_level.extend(infer_le_actions(le, bo_code, bo_name))
    merged = dedupe_actions([*explicit, *bo_level, *le_level])
    if len(merged) > max_total:
        # 优先保留明确动作和 BO 级动作，再按 BO 顺序保留 LE 级动作。
        merged = dedupe_actions([*explicit, *bo_level])
        merged.extend(dedupe_actions(le_level))
        merged = merged[:max_total]
    return assign_action_codes(merged)


def validate_bo_references(actions: Iterable[Mapping[str, str]],
                           business_object_codes: Iterable[str]) -> list[dict[str, str]]:
    """校验动作引用的业务对象编码是否存在于当前任务；返回违规动作摘要。"""
    allowed = {_text(code) for code in business_object_codes if _text(code)}
    issues: list[dict[str, str]] = []
    for action in actions:
        code = _text(action.get("业务对象编码"))
        if code and code not in allowed:
            issues.append({
                "动作编码": _text(action.get("动作编码")),
                "动作名称": _text(action.get("动作名称")),
                "业务对象编码": code,
            })
    return issues


def explicit_action_structural_errors(actions: Iterable[Mapping[str, Any]],
                                      business_object_codes: Iterable[str]) -> list[dict[str, str]]:
    """返回明确识别动作中的结构错误摘要；非空时不得用推断兜底掩盖。

    结构错误包括：必填字段（动作名称/动作英文名/动作描述）缺失、动作类型无法
    归一化为新增/修改/删除、动作编码非空但不符合 ``ACT+6位数字``、以及业务
    对象编码悬空（不在当前任务已确认集合中）。动作编码允许为空，由稳定编码
    阶段统一补齐；其余结构错误必须继续进入正式产物门禁，由契约报告，而不是
    被自动生成的动作悄悄覆盖。
    """
    allowed = {_text(code) for code in business_object_codes if _text(code)}
    errors: list[dict[str, str]] = []
    for index, action in enumerate(actions, 2):
        if not isinstance(action, Mapping):
            continue
        action_type = normalize_action_type(action.get("动作类型"))
        code = _text(action.get("动作编码"))
        bo_code = _text(action.get("业务对象编码"))
        if not any((_text(action.get("动作名称")), _text(action.get("动作英文名")),
                    _text(action.get("动作描述")))):
            errors.append({"row": str(index), "field": "required",
                           "message": f"动作第 {index} 行缺少动作名称/动作英文名/动作描述必填字段"})
        if not action_type:
            errors.append({"row": str(index), "field": "动作类型",
                           "message": f"动作第 {index} 行动作类型无法归一化为新增/修改/删除"})
        if code and not ACTION_CODE_PATTERN.fullmatch(code):
            errors.append({"row": str(index), "field": "动作编码",
                           "message": f"动作第 {index} 行动作编码 {code} 不符合 ACT+6 位数字"})
        if bo_code and bo_code not in allowed:
            errors.append({"row": str(index), "field": "业务对象编码",
                           "message": f"动作第 {index} 行引用的业务对象编码 {bo_code} "
                                       "不在当前任务已确认业务对象中"})
    return errors


def to_nine_field_rows(actions: Iterable[Mapping[str, str]]) -> list[list[str]]:
    """输出严格九字段顺序的行，供 CSV 写入使用。"""
    return [[_text(action.get(field)) for field in ACTION_FIELDS] for action in actions]
