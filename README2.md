중대한 변화가 생겼다.
raw가 되는 .csv파일들의 변화다. 모종의 사유로 raw(*이하 raw)로 여겨지는 데이터의 raw(*이하 raw_raw)를 기반으로 raw를 대체해야한다.

원래의 raw는 다음과 같았다.
*.csv파일을 export하게 되는 원본 query의 column list를 참고용으로 각 번호에 맞게 넣어뒀다. 이것은 query에 대한 데이터 타입으로 .csv와 컬럼타입에 차이는 있을 수 있으나 참조용으로 써라.(나도 실제 차이가 있을지 아닐지 있다면 어떤 차이인지 모르겠으며, 보안상 예시를 들어줄순 없음.)
다만, 현재 branch 기준으로는 'create_wip_table.py'가 내가 원하는 결과를 도출하고 있으므로 현재 branch 내용을 참고하라.

1.<"C:\Users\minuk12.choi\Documents\zhbm_eqpmaster.csv">

EQP_ID	VARCHAR2(40)
BATCH_KIND	VARCHAR2(20)
EQPLINE	VARCHAR2(10)
BODY_EQP_STATUS	VARCHAR2(40)
BODY_STATUS_CHANGE_TIME	DATE

2.<"C:\Users\minuk12.choi\Documents\zhbm_hold.csv">

SYSDATE	DATE
CUR_LINE_ID	VARCHAR2(40)
SYS_LINE_ID	VARCHAR2(40)
LOT_ID	VARCHAR2(40)
CARR_ID	VARCHAR2(40)
LOT_TYPE	VARCHAR2(40)
LOT_LEVEL	NUMBER
CUR_QTY	NUMBER
BAY_NAME	VARCHAR2(40)
STATUS	VARCHAR2(40)
PROC_ID	VARCHAR2(40)
ORDER_SEQ	NUMBER
SAMPLE_STEP_TYPE	VARCHAR2(40)
METAL_STATUS	VARCHAR2(40)
DE_RANK	NUMBER
DELAY_STEP_TYPE	VARCHAR2(40)
연속	VARCHAR2(46)
LAYER_ID	VARCHAR2(40)
STEP_LEVEL	NUMBER
STEP_SEQ	VARCHAR2(40)
STEP_DESC	VARCHAR2(255)
EQP_TYPE	VARCHAR2(40)
EQP_GROUP_RAW	VARCHAR2(40)
EQP_ID	VARCHAR2(40)
RECIPE_ID	VARCHAR2(40)
TKINTYPE	VARCHAR2(260)
TKIN_TYPE_DETAIL	VARCHAR2(40)
START_DATE	DATE
LAST_TKOUT_DATE	DATE
STEP_ARRIVE_DATE	DATE
LAST_EVENT_DATE	DATE
GRADE	VARCHAR2(255)

3.<"C:\Users\minuk12.choi\Documents\zhbm_tip.csv">

PROCESS	VARCHAR2(16)
STEP	VARCHAR2(16)
PPID	VARCHAR2(40)
EQPID	VARCHAR2(16)
EQPCHAM	VARCHAR2(41)
CHAMBERID	VARCHAR2(24)
BATCH_KIND	VARCHAR2(20)
PREVENT	VARCHAR2(7)
TYPE_BODY	VARCHAR2(7)
TYPE_CHAM	VARCHAR2(7)
TIP_EVENTTIME	DATE
EQPISSUE	VARCHAR2(40)
BODY_EQP_STATUS	VARCHAR2(40)
CHAM_EQP_STATUS	VARCHAR2(40)
EQPISSUETIME	DATE
EQPLINE	VARCHAR2(10)

4.<"C:\Users\minuk12.choi\Documents\zhbm_mclotsteppath.csv">

SYSDATE	DATE
CUR_LINE_ID	VARCHAR2(40)
SYS_LINE_ID	VARCHAR2(40)
LOT_ID	VARCHAR2(40)
CARR_ID	VARCHAR2(40)
LOT_TYPE	VARCHAR2(40)
LOT_LEVEL	NUMBER
CUR_QTY	NUMBER
BAY_NAME	VARCHAR2(40)
STATUS	VARCHAR2(40)
PROC_ID	VARCHAR2(40)
ORDER_SEQ	NUMBER
SAMPLE_STEP_TYPE	VARCHAR2(40)
METAL_STATUS	VARCHAR2(40)
DE_RANK	NUMBER
DELAY_STEP_TYPE	VARCHAR2(40)
연속	VARCHAR2(46)
LAYER_ID	VARCHAR2(40)
STEP_LEVEL	NUMBER
STEP_SEQ	VARCHAR2(40)
STEP_DESC	VARCHAR2(255)
EQP_TYPE	VARCHAR2(40)
EQP_GROUP_RAW	VARCHAR2(40)
EQP_ID	VARCHAR2(40)
RECIPE_ID	VARCHAR2(40)
TKINTYPE	VARCHAR2(260)
TKIN_TYPE_DETAIL	VARCHAR2(40)
START_DATE	DATE
LAST_TKOUT_DATE	DATE
STEP_ARRIVE_DATE	DATE
LAST_EVENT_DATE	DATE
GRADE	VARCHAR2(255)


raw_raw는 다음과 같다.

1.<"C:\Users\minuk12.choi\Documents\eqpmaster.csv">

EQP_ID	VARCHAR2(40)
BATCH_KIND	VARCHAR2(20)
EQPLINE	VARCHAR2(10)
BODY_EQP_STATUS	VARCHAR2(40)
BODY_STATUS_CHANGE_TIME	DATE

2.<"C:\Users\minuk12.choi\Documents\hold.csv">

SYSDATE	DATE
CUR_LINE_ID	VARCHAR2(40)
SYS_LINE_ID	VARCHAR2(40)
LOT_ID	VARCHAR2(40)
CARR_ID	VARCHAR2(40)
LOT_TYPE	VARCHAR2(40)
LOT_LEVEL	NUMBER
CUR_QTY	NUMBER
BAY_NAME	VARCHAR2(40)
STATUS	VARCHAR2(40)
PROC_ID	VARCHAR2(40)
ORDER_SEQ	NUMBER
SAMPLE_STEP_TYPE	VARCHAR2(40)
METAL_STATUS	VARCHAR2(40)
DE_RANK	NUMBER
DELAY_STEP_TYPE	VARCHAR2(40)
연속	VARCHAR2(46)
LAYER_ID	VARCHAR2(40)
STEP_LEVEL	NUMBER
STEP_SEQ	VARCHAR2(40)
STEP_DESC	VARCHAR2(255)
EQP_TYPE	VARCHAR2(40)
EQP_GROUP_RAW	VARCHAR2(40)
EQP_ID	VARCHAR2(40)
RECIPE_ID	VARCHAR2(40)
TKINTYPE	VARCHAR2(260)
TKIN_TYPE_DETAIL	VARCHAR2(40)
START_DATE	DATE
LAST_TKOUT_DATE	DATE
STEP_ARRIVE_DATE	DATE
LAST_EVENT_DATE	DATE
GRADE	VARCHAR2(255)

3.<"C:\Users\minuk12.choi\Documents\tip.csv">

PROCESS	VARCHAR2(16)
STEP	VARCHAR2(16)
PPID	VARCHAR2(40)
EQPID	VARCHAR2(16)
EQPCHAM	VARCHAR2(41)
CHAMBERID	VARCHAR2(24)
BATCH_KIND	VARCHAR2(20)
PREVENT	VARCHAR2(7)
TYPE_BODY	VARCHAR2(7)
TYPE_CHAM	VARCHAR2(7)
TIP_EVENTTIME	DATE
EQPISSUE	VARCHAR2(40)
BODY_EQP_STATUS	VARCHAR2(40)
CHAM_EQP_STATUS	VARCHAR2(40)
EQPISSUETIME	DATE
EQPLINE	VARCHAR2(10)

4.<"C:\Users\minuk12.choi\Documents\zhbm_mclot.csv">

SYSDATE	DATE
CUR_LINE_ID	VARCHAR2(40)
SYS_LINE_ID	VARCHAR2(40)
LOT_INFORM	VARCHAR2(500)
LOT_ID	VARCHAR2(40)
GRADE	VARCHAR2(255)
CARR_ID	VARCHAR2(40)
LOT_TYPE	VARCHAR2(40)
LOT_LEVEL	NUMBER
CUR_QTY	NUMBER
BAY_NAME	VARCHAR2(40)
STATUS	VARCHAR2(40)
PROC_ID	VARCHAR2(40)
ORDER_SEQ	NUMBER
STEP_SEQ	VARCHAR2(40)
START_DATE	DATE
LAST_TKOUT_DATE	DATE
STEP_ARRIVE_DATE	DATE
LAST_EVENT_DATE	DATE

5.<"C:\Users\minuk12.choi\Documents\zhbm_steppath.csv">
LOT_ID	VARCHAR2(40)
PROC_ID	VARCHAR2(40)
SAMPLE_STEP_TYPE	VARCHAR2(40)
METAL_STATUS	VARCHAR2(40)
DE_RANK	NUMBER
DELAY_STEP_TYPE	VARCHAR2(40)
연속	VARCHAR2(46)
LAYER_ID	VARCHAR2(40)
STEP_LEVEL	NUMBER
ORDER_SEQ	NUMBER
STEP_SEQ	VARCHAR2(40)
STEP_DESC	VARCHAR2(255)
EQP_TYPE	VARCHAR2(40)
EQP_GROUP_RAW	VARCHAR2(40)
EQP_ID	VARCHAR2(40)
RECIPE_ID	VARCHAR2(40)
TKINTYPE	VARCHAR2(260)
TKIN_TYPE_DETAIL	VARCHAR2(40)


1,2,3은 raw와 raw_raw가 똑같다. raw의 4가 raw_raw의 4,5로 분리된 것이 차이점일뿐이다.(*또한, 기존 raw 4에 없었던 컬럼인 lot_inform이 추가됐다. 아래 내용을 참조할 것)

raw_raw의 4,5가 raw의 4로 만들어지는 query는 아래와 같다.

with

r as (select
	lot_id, 
	order_seq, 
	count(CASE WHEN delay_step_type='S' THEN delay_step_type END) OVER (PARTITION BY lot_id ORDER BY order_seq) as de_rank 
from
(select lot_id, 
	order_seq, 
	delay_step_type
	from SMICDC_P3NRD.MC_LOT_STEP_PATH 
	where step_skip_yn<>'Y'
         	and proc_id in ('K4B1', 'K4B2', 'K4B3', 'K4B4') 
	and delay_step_type IN ('S', 'Y')
	order by lot_id, order_seq)
	),

p as (
select 
p.lot_id,
proc_id,
p.order_seq, 
sample_step_type,
metal_status,
r.de_rank,
p.delay_step_type,
(case 
when nvl(p.delay_step_type,'-') = 'S' then '연속첫' 
when nvl(p.delay_step_type,'-') ='Y' then 
'연속'
||
'('
||
(case when NVL(p.delay_step_type,'-')='Y' then TO_CHAR(TRUNC(p.delay_time_mins)) end)
||')'
end) as 연속,
	layer_id,
	step_level,
	step_seq,
	step_desc,
	eqp_type,
	eqp_group_id AS eqp_group_raw,
	e.eqp_id,
	recipe_id,
(CASE WHEN ext_1st_vals is not null then 
(case 
when NVL(tkin_type, '-') = 'EIN' then 'EIN' end)
||
'('
||
ext_1st_vals
||')'
end ) as tkintype,
	tkin_type_detail
from SMICDC_P3NRD.MC_LOT_STEP_PATH p, 
	 (select 
                 eqp_group_name, 
                 eqp_id 
            from SMIMES.MI_EQP_GROUP_LIST
            where instr(eqp_id, 'OFF')=0 
	and line_id = 'PFR1'
            order by eqp_group_name, eqp_id) e,
	r
where step_skip_yn<>'Y'
         and proc_id in ('K4B1', 'K4B2', 'K4B3', 'K4B4')
         and eqp_group_id = eqp_group_name(+)
	and p.lot_id = r.lot_id(+)
	and p.order_seq = r.order_seq(+)),

m as (
select 
m.cur_line_id,
m.sys_line_id,
m.lot_id,
m.carr_id,
m.lot_type,
m.lot_level,
m.cur_qty,
m.bay_name,
(case when m.lot_status_seg='Hold' then 'HOLD' else m.step_status_seg end) as status,
m.proc_id,
p.order_seq,
p.sample_step_type,
p.metal_status,
p.de_rank,
p.delay_step_type,
p.연속,
p.layer_id,
p.step_level,
p.step_seq,
p.step_desc,
p.eqp_type,
p.eqp_group_raw,
p.eqp_id,
p.recipe_id,
p.tkintype,
p.tkin_type_detail,
to_date(m.START_DATE, 'yyyymmdd hh24:mi:ss') as START_DATE,
to_date(m.LAST_TKOUT_DATE, 'yyyymmdd hh24:mi:ss') as LAST_TKOUT_DATE,
to_date(m.STEP_ARRIVE_DATE, 'yyyymmdd hh24:mi:ss') as STEP_ARRIVE_DATE,
to_date(m.LAST_EVENT_DATE, 'yyyymmdd hh24:mi:ss') as LAST_EVENT_DATE
from SMICDC_P3NRD.MC_LOT m, p
where m.PROC_ID in ('K4B1', 'K4B2', 'K4B3', 'K4B4')
	and m.LOT_STATUS_SEG in ('Active', 'Hold', 'Transferred')
	and m.lot_id = p.lot_id(+)
	and m.order_seq = p.order_seq(+)
),

u as (select 
m.cur_line_id,
m.sys_line_id,
m.lot_id,
m.carr_id,
m.lot_type,
m.lot_level,
m.cur_qty,
m.bay_name,
m.status,
m.proc_id,
p.order_seq,
p.sample_step_type,
p.metal_status,
p.de_rank,
p.delay_step_type,
p.연속,
p.layer_id,
p.step_level,
P.step_seq,
p.step_desc,
p.eqp_type,
p.eqp_group_raw,
p.eqp_id,
p.recipe_id,
p.tkintype,
p.tkin_type_detail,
START_DATE,
LAST_TKOUT_DATE,
STEP_ARRIVE_DATE,
LAST_EVENT_DATE
from m, p
where m.delay_step_type='S' 
	and status<>('RUN')
	and m.lot_id = p.lot_id(+)
	and m.de_rank = p.de_rank(+)

union all

select * from m
where m.delay_step_type='S' and status='RUN'
	or m.delay_step_type<>'S'),

g AS	
(SELECT DISTINCT LOT_ID, NEW_ATTR_VALUE AS GRADE
FROM 
(SELECT
h.LOT_ID,
h.LOT_TRANSN_TIME,
h.NEW_ATTR_VALUE,
MAX(h.LOT_TRANSN_TIME) OVER (PARTITION BY h.LOT_ID) AS MAX
FROM   MI_LOT_TRANSN_HIST_V h, (select lot_id from SMICDC_P3NRD.MC_LOT m where m.PROC_ID in ('K4B1', 'K4B2', 'K4B3', 'K4B4')) m
WHERE h.lot_id = m.lot_id
	and LOT_TRANSN_TYPE = 'ModifyAttr' AND WIP_ATTRIBUTE IN ('GRADE')
	AND LINE_ID IN ('PFR1'))
where MAX=LOT_TRANSN_TIME),


c as (SELECT 
	S.LOT_ID, S.STEP_COMMENT
	FROM SMICDC_P3NRD.MC_LOT_STEP_COMMENT S, SMICDC_P3NRD.MC_LOT MC
	WHERE MC.LOT_STATUS_SEG IN ('Hold', 'Active', 'Transferred')
	AND MC.PROC_ID in ('K4B1', 'K4B2', 'K4B3', 'K4B4')
	AND MC.LOT_ID=S.LOT_ID
	AND PARENT_ORDER_SEQ=0
)


select
SYSDATE,
u.*,
nvl(g.grade,'-') as grade,
c.step_comment as lot_inform
from u, g, c
where u.lot_id = g.lot_id(+)
	and u.lot_id = c.lot_id(+)



내가 원하는 결과는 이것이다. raw_raw를 바탕으로 기존 raw를 가지고 create_wip_table.py를 통해 도출해낸 결과와 똑같은 결과를 만들길 원한다.
(*단, 언급했듯이 lot_inform컬럼이 추가되었고, lot_inform은 최종 output_wip_concat에서 lot_id 왼쪽 컬럼에 위치하길 원한다.)
단, 조건이 있다. 기존의 create_wip_table.py는 output_wip_concat을 도출하기 위해 step by step으로 진행하느라 불필요한 과정이 있는 것 같다.
내가 생각하기엔 output_wip_concat을 한번에 더 간결하게 만들 수 있는 효율화가 가능할 것으로 보인다.
output_wip.xlsx를 최종적으로 만들 필요가 없고, output_wip_concat이 꼭 output_wip을 거쳤다가 가야하는건 아니다. 내가 원하는건 그저 output_wip_concat.xlsx라는 결과이다.
그러니 효율화해서 한번에 내가 원하는 결과를 만들 수 있도록 create_wip_table.py를 수정하라.
