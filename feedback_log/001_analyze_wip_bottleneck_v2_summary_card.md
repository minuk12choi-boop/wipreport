# 작업 로그 - analyze_wip_bottleneck_v2 기반 요약 카드 개선

## 1) analyze_wip_bottleneck_v2.py 핵심 참고 로직
- 입력 컬럼: lot_id/order_seq/step_seq/proc_id/layer_id/step_desc/exclusion_type/issue_eqp/prevent/eqpgroup/eqpgroup_cham/cur_qty 등.
- 전처리: 컬럼 소문자 정규화, cur_qty/order_seq 숫자 변환, lot_id+order_seq+step_seq 정렬.
- 집계: WAIT/HOLD/WAIT(진행불가) 중심으로 proc/layer/step 축 병목 식별.
- 병목 해석 요소: STEP_DESC, EQPGROUP, HOLD 사유 파싱, issue_eqp 파싱, 대기성 총량 및 lot 수.

## 2) Excel 의존 vs 웹 적용 가능 로직 분리
- Excel 의존: pd.read_excel(file_path), 로컬 파일 경로 지정, 콘솔 출력 리포트.
- 웹 적용 가능: 상태별 수량 합산, proc/layer/step 그룹 집계, exclusion/issue 문자열 파싱, 위험도 문구 생성.
- 적용 원칙: DB 조회 결과(dict rows)를 입력으로 받는 순수 함수로 구현.

## 3) 현재 요약 카드 관련 파일 구조
- 백엔드 집계: wipreport/services.py (build_summary, _build_summary_sections)
- API/View: wipreport/views.py summary_data
- 프론트: wipreport/static/wipreport/js/wipreport.js (summary_sections 렌더)
- 템플릿: wipreport/templates/wipreport/partials/summary_cards.html

## 4) lot_type 반영 여부 및 개선
- 기존: lot_type 필터는 존재하나 요약 카드 문구에서 lot_type 집중도/편차 반영 약함.
- 개선: lot_type breakdown 순수 함수 추가, 선택 lot_type 단일/전체 케이스별 문구 분기 추가.

## 5) 수정 파일 목록
- wipreport/services.py
- wipreport/tests.py
- feedback_log/001_analyze_wip_bottleneck_v2_summary_card.md

## 6) 검증 명령 및 결과
- python manage.py check: OK
- python manage.py test: OK (2 tests)
- python -m compileall wipreport: OK

## 7) 남은 TODO
- TODO: 실제 운영 데이터에서 lot_type 값 체계(PP/PB/PG 외) 검증 후 문구 임계값(현재 45%) 튜닝 필요.
- TODO: summary_sections[0]에 덮어쓰기 방식 대신 카드 내 상세 breakdown UI 확장 여부 검토.

## 8) 사용자 확인 필요사항
- 요약 카드 1번 섹션이 기존 Top5 나열 대신 해석형 3문장으로 표시되도록 변경됨.
- 응답에 lot_type_breakdown, bn_issue_rows 필드가 추가되었으나 기존 필드는 유지됨.
