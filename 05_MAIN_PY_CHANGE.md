# Router 등록 방법

## 방식 A: main.py에 직접 등록

수정 파일:

```text
D:\Projects\stock-platform\src\stock_platform\api\main.py
```

import 추가:

```python
from stock_platform.api.v1.indicator_router import router as indicator_router
```

Router 등록 추가:

```python
app.include_router(indicator_router)
```

예:

```python
from fastapi import FastAPI
from stock_platform.api.v1.router import router as api_router
from stock_platform.api.v1.indicator_router import router as indicator_router

app = FastAPI()
app.include_router(api_router)
app.include_router(indicator_router)
```

## 방식 B: api/v1/router.py에 등록

프로젝트가 통합 Router 구조라면 다음 파일을 수정합니다.

```text
D:\Projects\stock-platform\src\stock_platform\api\v1\router.py
```

```python
from stock_platform.api.v1.indicator_router import router as indicator_router
router.include_router(indicator_router)
```

방식 A와 방식 B를 동시에 사용하지 마십시오.
