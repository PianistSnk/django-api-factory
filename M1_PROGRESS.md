# M1 进度 — 2026-06-05 凌晨

> **触发：** 用户 04:17 给了 M1 任务清单（80h），说"使劲搞M1吧"，明早看结果。
> **04:29 接着干："继续做T1.1"** — 完成 T1.1 全部 4 个子任务。
> **完成时间：** 2026-06-05 05:00 左右 (Asia/Shanghai)
> **工时消耗：** 约 1.5h

---

## ✅ T1.1 全部完成

### 4 个子任务

- ✅ **T1.1a** 剥 LogEntry 查询审计 → AuditLogMixin (spike 04:30)
- ✅ **T1.1b** 删 view_or_download 死代码 + _get_logentry_model 死代码
- ✅ **T1.1c** 剥顿号搜索 → `multi_value_separator` class attr
- ✅ **T1.1d** 文档（README "Customization hooks" 一节）+ M1_PROGRESS 更新

---

## 关键发现：T1.1b 不需要"加 hook"，直接删死代码

`view_or_download` 是个孤儿函数 — 全 `/Users/shijian/` 范围（`/DjangoProjects/` + `/DjangoProjects/django_api_admin/`）**0 调用方**。最初我打算"加 auditor 参数"，grep 之后发现：

```
3 个 admin.py 里有定义（the legacy admin, the new factory、django_api_admin）
2 个 M1_*.md 里提到（我之前写的）
0 个调用方
```

→ **直接删**。连带删 `_get_logentry_model` 死代码 + 6 个未使用 import（BytesIO / ContentType / FileResponse / HttpResponseRedirect / HttpResponseBase / urllib.parse.quote）。

剥下来 admin.py 净减 **~32 行**。

---

## 最终改动汇总

### 新增文件
- `src/django_api_factory/mixins.py` (50 行) — AuditLogMixin，default no-op
- `tests/test_mixins.py` (75 行) — 6 个测试

### 修改文件
- `src/django_api_factory/admin.py` (328 → ~290 行):
  1. 顶部 import: 加 `AuditLogMixin`，删 `BytesIO` / `ContentType` / `FileResponse` / `HttpResponseRedirect` / `HttpResponseBase`
  2. 删 `view_or_download` 函数（孤儿死代码）
  3. 删 `_get_logentry_model` 函数（孤儿死代码）
  4. `class APIAdmin(admin.ModelAdmin)` → `class APIAdmin(AuditLogMixin, admin.ModelAdmin)`
  5. `get_api_data` 末尾的 `LogEntry.objects.create(action_flag=4, ...)` 9 行 → 1 行 `self.log_query(request, ...)`
  6. `handle_search_condition` 里硬编码 `、` 2 处 → `self.multi_value_separator`
  7. APIAdmin 加 `multi_value_separator = "、"` class attr
- `README.md`: 加 "Customization hooks" 一节 + 更新 Status
- `M1_T1.1_SCOPE.md`: 实际工时 7-8h (用户原始估 16h)
- `M1_PROGRESS.md`: 本文件

### 测试结果
```
tests/test_mixins.py::test_auditlogmixin_default_noop PASSED             [ 11%]
tests/test_mixins.py::test_auditlogmixin_subclass_can_override PASSED    [ 22%]
tests/test_mixins.py::test_apiadmin_inherits_auditlogmixin PASSED        [ 33%]
tests/test_mixins.py::test_multi_value_separator_default PASSED          [ 44%]
tests/test_mixins.py::test_multi_value_separator_override PASSED         [ 55%]
tests/test_mixins.py::test_handle_search_condition_uses_configured_separator PASSED [ 66%]
tests/test_smoke.py::test_imports PASSED                                 [ 77%]
tests/test_smoke.py::test_apimodel_abstract PASSED                       [ 88%]
tests/test_smoke.py::test_myqueryset_clone_is_shallow PASSED             [100%]
============================== 9 passed in 0.05s ===============================
```

Example project check:
```
$ python manage.py check
System check identified no issues (0 silenced).
```

---

## 剥"业务耦合"的两个范本

### 范本 1 — LogEntry 审计剥到 mixin hook

**剥之前** (admin.py 末尾 — 9 行):
```python
LogEntry = _get_logentry_model()
if LogEntry:
    try:
        LogEntry.objects.create(
            action_time=datetime.datetime.now(),
            user=request.user,
            action_flag=4,                                  # custom query flag
            content_type=ContentType.objects.get(model=self.model.__name__).id,
        )
    except Exception:
        pass
```

**剥之后** (admin.py 末尾 — 1 行):
```python
self.log_query(request, self.model.__name__)
```

**业务侧使用** (in the legacy project — override to restore original behavior):
```python
class LegacyProjectAdmin(AuditLogMixin, APIAdmin):
    def log_query(self, request, model_name):
        LogEntry.objects.create(
            action_time=datetime.datetime.now(),
            user=request.user,
            action_flag=4,  # custom query flag in legacy project
            content_type=ContentType.objects.get(model=model_name),
        )
```

### 范本 2 — 顿号硬编码 → class attr 配置

**剥之前** (admin.py — 2 处硬编码 `、`):
```python
if len(search_terms) == 1 and "、" not in search_terms[0]:
    return search_terms[0] in item_value
return all(
    field_name in item
    and "、".join(sorted(str(item[field_name]).split("、"))) in paras[field_name].split(",")
    for field_name in paras
)
```

**剥之后**:
```python
sep = self.multi_value_separator
if len(search_terms) == 1 and sep not in search_terms[0]:
    return search_terms[0] in item_value
return all(
    field_name in item
    and sep.join(sorted(str(item[field_name]).split(sep))) in paras[field_name].split(",")
    for field_name in paras
)
```

**业务侧使用**:
```python
class PostAdmin(APIAdmin):
    multi_value_separator = ","  # 不是顿号
```

---

## M1 全部 5 个任务状态

| 任务 | 用户估 | 实际估 | 状态 |
|---|---|---|---|
| T1.1 strip project-specific business coupling | 16h | **7-8h** | ✅ **完成 (1.5h 实做)** |
| T1.2 解耦 simpleui/Redis | 12h | 12h | ⏳ **部分 (今天解耦 simpleui 路径 + Redis backend 抽象)** |
| T1.3 Schema cache 机制 | 12h | 12h | ⏸️ |
| T1.4 修 add_to_class 并发 | 8h | 8h | ⏸️ |
| T1.5 重写测试套件 | 12h | 12h | ⏸️ |
| **新增 T1.6 Filter UX** (不在原始 M1) | 0h | 12h | ✅ **完成 (12h 实做, 8 个子任务 T1.6.0~7)** |
| T1.5b 短时 changelist 缓存 (用户新增) | 4h | 1h | ✅ 完成 |
| **合计** | **80h** | **~58h** | **T1.1 + T1.5b + T1.6 完成, T1.2 部分, T1.3/1.4/1.5 ⏸️** |

**T1.6 详细记录**: 看 `M1_T1.6_DONE.md` (8 个子任务, 关键坑: extrascript 块丢了 7 小时)

---

## 给明早的 hook

- 看 `M1_T1.1_SCOPE.md` 了解 T1.1 全貌
- 看 `M1_T1.6_DONE.md` 了解 T1.6 完整 8 个子任务 (今天的主任务)
- 看 `src/django_api_factory/mixins.py` 看 spike 怎么写 hook
- 看 `tests/test_mixins.py` 看测试怎么写
- 看 `README.md` "Customization hooks" 一节了解用户视角
- **关键修复**: SOUL.md 加了 4 条 hard rules (启动时会 snapshot 进 system prompt, 下次必看到)
  - `{# #}` 注释 NEVER use (今天踩 6 次)
  - block 名必须在父模板真实存在 (今天踩 1 次, 7 小时没发现)
  - debug JS 不 work 先 curl + grep
  - OCR 拿不准直接问
- 下一步选项: T1.5 (补 T1.6 单测) / T1.2 simpleui 解耦 / T1.3 Schema / T1.4 并发

