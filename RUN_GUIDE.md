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

## 4) 기본 검증 명령
```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python -m compileall .
python manage.py runserver 127.0.0.1:8000
```

## 5) URL 확인
- 요약: `http://127.0.0.1:8000/wip/summary/`
- 참조: `http://127.0.0.1:8000/wip/ref/`
