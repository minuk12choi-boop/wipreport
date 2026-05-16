from django.db import models

class WipReportLotPath(models.Model):
    sys_line_id = models.TextField(null=True, blank=True)
    cur_line_id = models.TextField(null=True, blank=True)
    eqpline = models.TextField(null=True, blank=True)
    sysdate = models.TextField(null=True, blank=True)
    lot_inform = models.TextField(null=True, blank=True)
    lot_id = models.TextField(null=True, blank=True)
    status = models.TextField(null=True, blank=True)
    status_reason = models.TextField(null=True, blank=True)
    grade = models.TextField(null=True, blank=True)
    lot_type = models.TextField(null=True, blank=True)
    lot_level = models.TextField(null=True, blank=True)
    cur_qty = models.FloatField(null=True, blank=True)
    carr_id = models.TextField(null=True, blank=True)
    bay_name = models.TextField(null=True, blank=True)
    proc_id = models.TextField(null=True, blank=True)
    order_seq = models.TextField(null=True, blank=True)
    sample_step_type = models.TextField(null=True, blank=True)
    metal_status = models.TextField(null=True, blank=True)
    layer_id = models.TextField(null=True, blank=True)
    step_level = models.TextField(null=True, blank=True)
    continuous = models.TextField(db_column='연속', null=True, blank=True)
    step_seq = models.TextField(null=True, blank=True)
    step_desc = models.TextField(null=True, blank=True)
    recipe_id = models.TextField(null=True, blank=True)
    tkintype = models.TextField(null=True, blank=True)
    batch_kind = models.TextField(null=True, blank=True)
    eqp_type = models.TextField(null=True, blank=True)
    eqpgroup = models.TextField(null=True, blank=True)
    eqpgroup_cham = models.TextField(null=True, blank=True)
    prevent = models.TextField(null=True, blank=True)
    issue_eqp = models.TextField(null=True, blank=True)
    input_elapsed_days = models.TextField(db_column='투입경과일_일', null=True, blank=True)
    step_arrive_elapsed_days = models.TextField(db_column='step도착경과_일', null=True, blank=True)
    last_event_elapsed_days = models.TextField(db_column='마지막event경과_일', null=True, blank=True)
    start_date = models.TextField(null=True, blank=True)
    last_tkout_date = models.TextField(null=True, blank=True)
    step_arrive_date = models.TextField(null=True, blank=True)
    last_event_date = models.TextField(null=True, blank=True)
    exclusion_type = models.TextField(null=True, blank=True)
    loaded_at = models.DateTimeField(null=True, blank=True)
    loaded_id = models.TextField(null=True, blank=True)
    class Meta:
        managed = False
        db_table = 'wip_report_lotpath'

class WipMove(models.Model):
    report_date = models.TextField(db_column='일보date', null=True, blank=True)
    lot_id = models.TextField(null=True, blank=True)
    lot_type = models.TextField(null=True, blank=True)
    move = models.FloatField(null=True, blank=True)
    process_id = models.TextField(null=True, blank=True)
    step_seq = models.TextField(null=True, blank=True)
    tkout_date = models.TextField(null=True, blank=True)
    loaded_at = models.DateTimeField(null=True, blank=True)
    loaded_id = models.TextField(null=True, blank=True)
    class Meta:
        managed = False
        db_table = 'wip_move'

class WipMoveGroup(models.Model):
    y = models.IntegerField(null=True, blank=True)
    m = models.IntegerField(null=True, blank=True)
    w = models.IntegerField(null=True, blank=True)
    report_date = models.TextField(db_column='일보date', null=True, blank=True)
    lot_id = models.TextField(null=True, blank=True)
    lot_type = models.TextField(null=True, blank=True)
    move = models.FloatField(null=True, blank=True)
    loaded_at = models.DateTimeField(null=True, blank=True)
    loaded_id = models.TextField(null=True, blank=True)
    class Meta:
        managed = False
        db_table = 'wip_move_group'

class WipRefProductRule(models.Model):
    sort_no = models.IntegerField(default=0)
    lot_char_1 = models.CharField(max_length=20, blank=True, default='')
    lot_char_2 = models.CharField(max_length=20, blank=True, default='')
    lot_char_3 = models.CharField(max_length=20, blank=True, default='')
    lot_char_4 = models.CharField(max_length=20, blank=True, default='')
    lot_char_5 = models.CharField(max_length=20, blank=True, default='')
    processed = models.CharField(max_length=50, blank=True, default='')
    product_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: db_table = 'wip_ref_product_rule'

class WipRefModuleRule(models.Model):
    sort_no = models.IntegerField(default=0)
    product_name = models.CharField(max_length=100)
    start_layer = models.CharField(max_length=50, blank=True, default='')
    end_layer = models.CharField(max_length=50, blank=True, default='')
    start_stepseq = models.CharField(max_length=50, blank=True, default='')
    end_stepseq = models.CharField(max_length=50, blank=True, default='')
    module_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: db_table = 'wip_ref_module_rule'

class WipRefExclusionTypeRule(models.Model):
    sort_no = models.IntegerField(default=0)
    exclusion_kind = models.CharField(max_length=20)
    condition_1 = models.CharField(max_length=200)
    condition_2 = models.CharField(max_length=200, blank=True, default='')
    condition_3 = models.CharField(max_length=200, blank=True, default='')
    type_name = models.CharField(max_length=100, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: db_table = 'wip_ref_exclusion_type_rule'

class WipRefHotLotRule(models.Model):
    sort_no = models.IntegerField(default=0)
    grade = models.CharField(max_length=20, blank=True, default='')
    condition_1 = models.CharField(max_length=200)
    condition_2 = models.CharField(max_length=200, blank=True, default='')
    condition_3 = models.CharField(max_length=200, blank=True, default='')
    type_name = models.CharField(max_length=100, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: db_table = 'wip_ref_hot_lot_rule'
