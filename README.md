# wipreport

[참조 테이블](*각 txt엔 sql 및 column list가 있음, 모든 date타입 컬럼들은 결과값이 2026-05-13 04:04:22 형태로 나오게 설정해둠.)
eqp.txt -> eqp as e
holdtxt -> hold as h
mclotsteppath.txt -> mcpath as m
tip.txt -> tip as t

<'wip' 테이블 만드는 .py파일 만들기>
*아래는 내가 생각할 수 있는 결과값을 도출해낼 수 있는 방법이다. 이를 python 코드에 맞게 더 효율적으로 빠르고 오류없이 결과를 도출해낼 수 있는 파일로 구현하여야한다.

1. mcpath as m에 eqpmaster를 조인한다. (= as me 테이블)
   -조인기준: m.eqp_id = e.eqp_id
   -add_columns: e.batch_kind, e.eqpline, e.body_eqp_status, e.body_status_change_time

2. me테이블에 tip as t를 조인한다. (=as met 테이블)
   -조인기준: me.proc_id = t.process
           and me.step_seq = t.step
           and me.eqp_id = t.eqpid
           and me.recipe_id = t.ppid
   -add_columns: t.eqpcham, t.chamberid, t.batch_kind, t.prevent, t.typebody, t.type_cham, t.tip_eventtime, t.eqpissue, t.body_eqp_status, t.cham_eqp_status, t.eqpissuetime, t.eqpline
   -변경필요컬럼: body_eqp_status=nvl(t.body_eqp_status, me.body_eqp_status),
               batch_kind=nvl(t.batch_kind, me.bath_kind),
               eqpline=nvl(t.eqpline, me.eqpline),
               eqpissuetime=nvl(t.eqpissuetime, me.body_status_change_time),
               eqpissue=nvl(t.eqpissue, case when me.body_eqp_status in ('LOCAL', 'PM', 'DOWN') then me.body_eqp_status end)
     (*변경필요컬럼은 초기 정합성 체크 단계에서만 변경된 컬럼, 변경에 사용된 컬럼을 모두 남겨놓지만 정합성 검증이 되면 최종적으론 변경된 컬럼만 유지하면 되고 변경에 사용된 컬럼은 없어도된다.)

3.
