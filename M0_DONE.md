# M0: 浅克隆 Demo — ✅ 完成

**完成时间：** 2026-06-05 凌晨 02:20 (Asia/Shanghai)
**用时：** 实际 1.5h (比预估 1-2 天快很多)

## 跑通验证

```
tests/test_smoke.py ............... 3 passed ✓
tests/test_e2e.py .................. 2 endpoints OK ✓
  → /admin/api/post/   200, 127KB JSONPlaceholder 数据
  → /admin/api/user/   200,  44KB JSONPlaceholder 数据
python manage.py check ............ no issues ✓
```

## 交付物

```
/Users/shijian/DjangoProjects/django-api-factory/
├── pyproject.toml                 # 包配置 (0.1.0.dev0)
├── LICENSE                        # MIT
├── README.md                      # 用户文档
├── .gitignore
├── pytest.ini
├── src/django_api_factory/        # 核心包
│   ├── __init__.py
│   ├── models.py                  # APIModel 抽象基类 (classmethod 重构)
│   ├── admin.py                   # APIAdmin 核心实现
│   ├── filter.py                  # APIFilter (中文顿号拆分)
│   ├── changelist.py              # APIChangeList
│   └── queryset.py                # MyQuerySet 浅拷贝
├── example/                       # 完整 demo 项目
│   ├── manage.py
│   ├── example/                   # settings/urls/wsgi
│   └── api/                       # Post + User model + admin
└── tests/
    ├── conftest.py
    ├── test_smoke.py              # 3 个单元测试
    └── test_e2e.py                # 端到端 admin 数据加载验证
```

## 关键改动(compared to the legacy project)

1. **`urls()` / `cache()` 改成 classmethod** — 解决 `self.model.urls()` 缺 self 的坑
2. **Redis 做成可选** — 没装/没配就静默跳过，不报错
3. **`requests` 直接用** — remove the legacy requests wrapper
4. **Stripped project-specific business coupling** — removed BaseAdmin / BaseAjaxAdmin / YYDMAdmin and the 顿号-specific semantics
5. **错误处理改进** — `try/except: pass` 换成具体异常 + log
6. **抽象基类** — `class Meta: abstract = True` 干净一点

## 启动方式

```bash
cd /Users/shijian/DjangoProjects/django-api-factory
source .venv/bin/activate
cd example
python manage.py runserver
# 浏览器: http://127.0.0.1:8000/admin/api/post/
# 账号: admin / admin12345
```

## 下一步 (M1)

- 解决 `add_to_class` 并发坑（Schema 注册模式）
- 把 list_per_page 改 server-side 分页
- 处理 1 万+行数据的 streaming
- 加测试覆盖（目标 80%）

## 已知问题

- `add_to_class` 并发坑还在（多用户同时访问会互相覆盖字段）→ M1 解决
- `list_per_page=50` 在 50w 行数据下会卡 → M2 解决
- 没装 redis 时 `_get_cache_data` 静默返回 None，符合预期
