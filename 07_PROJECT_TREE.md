# STEP34 파일 구조

```text
README_STEP34_REVISED
├─ README_STEP34.md
├─ 01_USER_ACTION_CHECKLIST.md
├─ 02_INSTALL_AND_APPLY.md
├─ 03_FILES_TO_CREATE_OR_CHANGE.md
├─ 04_ALEMBIC_GUIDE.md
├─ 05_MAIN_PY_CHANGE.md
├─ 06_TEST_AND_VERIFY.md
├─ 07_PROJECT_TREE.md
├─ CHANGELOG.md
├─ requirements_step34.txt
├─ src
│  └─ stock_platform
│     ├─ indicator
│     │  ├─ __init__.py
│     │  ├─ models.py
│     │  └─ calculator.py
│     ├─ screener
│     │  ├─ __init__.py
│     │  └─ service.py
│     └─ api
│        └─ v1
│           └─ indicator_router.py
├─ alembic
│  └─ versions
│     └─ 20260717_03_indicator.py
└─ tests
   └─ step34
      ├─ test_indicator.py
      └─ test_screener.py
```
