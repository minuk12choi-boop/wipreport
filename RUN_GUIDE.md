# Django 실행 가이드 (1차 검증용)

## 1) 가상환경 생성/활성화 (PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 2) 환경변수 파일 준비
```powershell
Copy-Item .env.example .env
```

`.env`에서 `DB_PASSWORD`를 실제 값으로 설정하세요.

## 3) 의존성 설치
```powershell
python -m pip install -r requirements.txt
```

## 4) 최초 1회 마이그레이션 (기준정보 테이블 생성)
```powershell
python manage.py migrate
```
- 위 migrate는 `wip_ref_product_rule`, `wip_ref_module_rule`, `wip_ref_exclusion_type_rule`, `wip_ref_hot_lot_rule` 생성 목적입니다.
- `wip_report_lotpath`, `wip_move`, `wip_move_group` 운영 테이블은 `managed=False`로 Django 생성/수정 대상이 아닙니다.
- `/wip/ref/` 접속 시 1146 오류가 보인다면 migrate 미실행 상태이므로 위 명령을 먼저 실행하세요.

## 5) 기본 검증 명령
```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python -m compileall .
```

## 6) 실행
```powershell
python manage.py runserver 127.0.0.1:8031
```

## 7) 접속 URL
- 루트(자동 이동): `http://127.0.0.1:8031/` → `/wip/summary/`
- 요약: `http://127.0.0.1:8031/wip/summary/`
- 기준정보: `http://127.0.0.1:8031/wip/ref/`

## 8) 포트 확인 (Windows)
```powershell
netstat -ano | findstr :8031
netsh interface ipv4 show excludedportrange protocol=tcp
```
