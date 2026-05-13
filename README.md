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
   (*단, tip as t 테이블에서 (t.step='-' or t.ppid='-' or t.process='-') and t.prevent='PREVENT' 인 행에 한해서(=t1 테이블) 추가 조인이 필요하다. tip테이블에서 '-'이란건 해당 컬럼값을 특정하지않고 조인하겠다는 의미로, '-'인 컬럼부분을 조인기준에서 빼고 조인하여 t1.add_columns를 붙이면된다. 이 때 결국 t와 t1 조인의 add_columns끼리 충돌되는 컬럼이 있을텐데 우선순위는 t1에 있다. 충돌이 난다면 nvl(t1.add_columns, t.add_columns)이다. 이것 또한 초기 정합성 체크시에만 확인할 수 있도록 남겨두고 추후에는 변경된 컬럼이 최종컬럼이지 변경에 사용되는 컬럼은 남겨둘 필요가 없다.)
   -변경필요컬럼: body_eqp_status=nvl(t.body_eqp_status, me.body_eqp_status),
               batch_kind=nvl(t.batch_kind, me.bath_kind),
               eqpline=nvl(t.eqpline, me.eqpline),
               eqpissuetime=nvl(t.eqpissuetime, me.body_status_change_time),
               eqpissue=nvl(t.eqpissue, case when me.body_eqp_status in ('LOCAL', 'PM', 'DOWN') then me.body_eqp_status end)
     (*변경필요컬럼은 초기 정합성 체크 단계에서만 변경된 컬럼, 변경에 사용된 컬럼을 모두 남겨놓지만 정합성 검증이 되면 최종적으론 변경된 컬럼만 유지하면 되고 변경에 사용된 컬럼은 없어도된다.)

4. met 테이블에 hold as h를 조인한다. (=as meth 테이블)
   -조인조건: met.lot_id = h.lot_id and met.step_seq = h.step_seq
   (*단, 해당 조인은 where met.status<>'RUN' 일 때만 조인할 것)
   -신규컬럼: h.item_type의 값은 ['EXCEPTION', 'HOLD LOT', 'FTkinPvLot', 'FUTUREHOLD'] 인데, 각각이 차례대로 '예약제외', 'HOLD', 'FTP' 컬럼이 새로 생기게 하고 h.item_type에 해당하는 행에 'O'가 컬럼값으로 들어가게 해달라.예를 들면 item_type='EXCEPTION'인 행은 '예약제외' 컬럼에 'O'가 체크되게 하는 것이다.(*FUTUREHOLD는 HOLD컬럼쪽에 붙게하기) 그리고 같은 타입에 두개의 행이 조인되는 경우이면 'O'를 하나만 넣으면 된다.
   -add_columns: h.hold_user, h.hold_reason, h.hold_date(*hold_date는 '예약제외', 'HOLD', 'FTP'이 하나의 행에 몇개가 조인이 될진 모르겠지만 셋중에 min hold_date값이 하나만 들어가게 해주고,각각은 또 '예약제외_user', 'FTP_user', 'HOLD_user', '예약제외_reason', 'FTP_reason', 'HOLD_reason'의 커럼에 각 값이 들어간다. 만약 같은 타입에 두개 이상의 행이 조인되는 경우 hold_user나, hold_reason 같은 경우엔 uniqueconcatenate(h.add_columns) over (met.lot_id, met.order_seq, met.step_seq, met.recipeid) 가 되도록 해달라. 즉 이 4번 조인으로 인해서는 행이 늘어나지 않길 원하는 것이다.

meth 테이블을 원본으로 하여 시각화하는 웹을 만들 예정.
