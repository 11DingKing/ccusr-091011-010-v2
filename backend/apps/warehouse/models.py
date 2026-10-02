"""
库房管理模型
"""
from django.db import models
from django.utils import timezone
from apps.authentication.models import User


class Unit(models.Model):
    """单位模型"""
    name = models.CharField('单位名称', max_length=5, unique=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_units', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_unit'
        verbose_name = '单位'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品类"""
        return self.categories.exists()


class Category(models.Model):
    """品类模型"""
    name = models.CharField('品类名称', max_length=10, unique=True)
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT,
        related_name='categories', verbose_name='单位'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_categories', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_category'
        verbose_name = '品类'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品种"""
        return self.varieties.exists()


class Variety(models.Model):
    """品种模型"""
    name = models.CharField('品种名称', max_length=20)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT,
        related_name='varieties', verbose_name='所属品类'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_varieties', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_variety'
        verbose_name = '品种'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        unique_together = ['category', 'name']
    
    def __str__(self):
        return f"{self.category.name} - {self.name}"
    
    @property
    def is_in_stock(self):
        """是否已入库"""
        return self.goods.exists()
    
    @property
    def unit_name(self):
        """获取单位名称"""
        return self.category.unit.name if self.category and self.category.unit else ''


class Goods(models.Model):
    """货物模型"""
    variety = models.ForeignKey(
        Variety, on_delete=models.CASCADE,
        related_name='goods', verbose_name='所属品种'
    )
    name = models.CharField('货物名称', max_length=200)
    code = models.CharField('货物编码', max_length=50, unique=True)
    specification = models.CharField('规格型号', max_length=200, blank=True)
    quantity = models.DecimalField('库存数量', max_digits=12, decimal_places=2, default=0)
    warning_threshold = models.DecimalField('预警阈值', max_digits=12, decimal_places=2, default=10)
    location = models.CharField('存放位置', max_length=100, blank=True)
    remark = models.TextField('备注', blank=True)
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_goods'
        verbose_name = '货物'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_warning(self):
        """是否预警"""
        return self.quantity <= self.warning_threshold

    @property
    def active_freeze_quantity(self):
        """当前由执行中召回案件施加的有效冻结总量"""
        total = self.recall_freezes.filter(
            is_active=True, case__status='open'
        ).aggregate(total=models.Sum('quantity'))['total']
        return total or 0

    @property
    def is_frozen(self):
        """是否被任一执行中的召回案件冻结"""
        return self.recall_freezes.filter(
            is_active=True, case__status='open'
        ).exists()

    @property
    def frozen_quantity(self):
        """冻结数量（兼容属性名）"""
        return self.active_freeze_quantity

    @property
    def available_quantity(self):
        """可动用库存（总库存扣除召回冻结）"""
        frozen = self.active_freeze_quantity
        available = self.quantity - frozen
        return available if available > 0 else self.quantity.__class__('0')


class StockIn(models.Model):
    """入库记录模型"""
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_ins', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_in_operations', verbose_name='操作人'
    )
    quantity = models.DecimalField('入库数量', max_digits=12, decimal_places=2)
    batch_no = models.CharField('批次号', max_length=50, blank=True)
    supplier = models.CharField('供应商', max_length=200, blank=True)
    stock_in_time = models.DateTimeField('入库时间', auto_now_add=True)
    remark = models.TextField('备注', blank=True)
    
    class Meta:
        db_table = 'wh_stock_in'
        verbose_name = '入库记录'
        verbose_name_plural = verbose_name
        ordering = ['-stock_in_time']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class StockOut(models.Model):
    """出库记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
        ('completed', '已完成'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_outs', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_out_operations', verbose_name='操作人'
    )
    receiver = models.CharField('领用人', max_length=100)
    receiver_dept = models.CharField('领用部门', max_length=100, blank=True)
    quantity = models.DecimalField('出库数量', max_digits=12, decimal_places=2)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    stock_out_time = models.DateTimeField('出库时间', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_stock_out'
        verbose_name = '出库记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class Warning(models.Model):
    """预警记录模型"""
    TYPE_CHOICES = [
        ('low_stock', '库存不足'),
        ('expiring', '即将过期'),
        ('expired', '已过期'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='warnings', verbose_name='货物'
    )
    type = models.CharField('预警类型', max_length=20, choices=TYPE_CHOICES)
    message = models.TextField('预警信息')
    is_read = models.BooleanField('是否已读', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_warning'
        verbose_name = '预警记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.get_type_display()}"


class Approval(models.Model):
    """审批记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
    ]
    
    stock_out = models.ForeignKey(
        StockOut, on_delete=models.CASCADE,
        related_name='approvals', verbose_name='出库记录'
    )
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='approvals', verbose_name='审批人'
    )
    status = models.CharField('审批状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    remark = models.TextField('审批意见', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_approval'
        verbose_name = '审批记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.stock_out} - {self.get_status_display()}"


# ==================== 召回案件 ====================

class RecallCase(models.Model):
    """召回案件模型

    供应方通报批次缺陷后建立的案件。一个案件可依据多个批次号立案；
    同一对象可被多个案件召回，每个案件独立保留依据、独立计算影响清单、
    独立施加冻结，关闭一个案件不得解除其他案件的限制。
    """
    STATUS_CHOICES = [
        ('open', '执行中'),
        ('closed', '已关闭'),
    ]

    case_no = models.CharField('案件编号', max_length=50, unique=True)
    title = models.CharField('案件名称', max_length=200)
    supplier = models.CharField('供应方', max_length=200, blank=True)
    description = models.TextField('缺陷描述', blank=True)
    status = models.CharField('案件状态', max_length=20, choices=STATUS_CHOICES, default='open')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_recall_cases', verbose_name='立案人'
    )
    closed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='closed_recall_cases', verbose_name='关闭人'
    )
    closed_at = models.DateTimeField('关闭时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_recall_case'
        verbose_name = '召回案件'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.case_no} - {self.title}"

    @property
    def is_open(self):
        return self.status == 'open'

    @classmethod
    def generate_case_no(cls):
        """生成案件编号：RC-年月日-当日序号"""
        today = timezone.now().strftime('%Y%m%d')
        prefix = f'RC-{today}-'
        last = cls.objects.filter(case_no__startswith=prefix).order_by('case_no').last()
        seq = 1
        if last:
            try:
                seq = int(last.case_no.rsplit('-', 1)[-1]) + 1
            except ValueError:
                seq = 1
        return f'{prefix}{seq:03d}'


class RecallBasis(models.Model):
    """召回依据

    案件与批次号之间的独立依据记录。同一对象被多次召回时，
    各案件分别保留各自的依据，互不影响。
    """
    SOURCE_CHOICES = [
        ('supplier_notice', '供应方通报'),
        ('internal_check', '内部排查'),
        ('regulatory_order', '监管指令'),
        ('other', '其他'),
    ]

    case = models.ForeignKey(
        RecallCase, on_delete=models.CASCADE,
        related_name='bases', verbose_name='所属案件'
    )
    batch_no = models.CharField('缺陷批次号', max_length=50)
    source = models.CharField('依据来源', max_length=30, choices=SOURCE_CHOICES,
                              default='supplier_notice')
    notice_no = models.CharField('通报文号', max_length=100, blank=True)
    evidence = models.TextField('依据说明', blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_recall_bases', verbose_name='登记人'
    )
    created_at = models.DateTimeField('登记时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_recall_basis'
        verbose_name = '召回依据'
        verbose_name_plural = verbose_name
        ordering = ['id']
        unique_together = [('case', 'batch_no')]

    def __str__(self):
        return f"{self.case.case_no} - 批次 {self.batch_no}"


class RecallItem(models.Model):
    """召回影响清单条目

    每个案件对每个受影响对象（货物 × 批次）保留一条独立记录。
    在库对象记录应冻结数量，离库对象记录责任人与最后已知状态。
    """
    LOCATION_CHOICES = [
        ('in_stock', '在库'),
        ('out', '已离库'),
    ]

    case = models.ForeignKey(
        RecallCase, on_delete=models.CASCADE,
        related_name='items', verbose_name='所属案件'
    )
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='recall_items', verbose_name='受影响货物'
    )
    stock_out = models.ForeignKey(
        'StockOut', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='recall_items', verbose_name='对应出库单'
    )
    batch_no = models.CharField('批次号', max_length=50)
    location_status = models.CharField('库位状态', max_length=20, choices=LOCATION_CHOICES)
    affected_qty = models.DecimalField('受影响数量', max_digits=12, decimal_places=2, default=0)
    frozen_qty = models.DecimalField('冻结数量', max_digits=12, decimal_places=2, default=0)
    receiver = models.CharField('责任领用人', max_length=100, blank=True)
    receiver_dept = models.CharField('领用部门', max_length=100, blank=True)
    last_known_status = models.CharField('最后已知状态', max_length=200, blank=True)
    trace_detail = models.TextField('谱系追溯说明', blank=True)
    is_active = models.BooleanField('是否仍在影响清单', default=True)
    first_seen_at = models.DateTimeField('首次纳入时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_recall_item'
        verbose_name = '召回影响条目'
        verbose_name_plural = verbose_name
        ordering = ['-is_active', 'case', 'id']
        # 在库行 stock_out 为空（同一案件同一货物批次仅一条）；
        # 离库行按对应出库单区分（同一批次可流向多张出库单）
        unique_together = [('case', 'goods', 'batch_no', 'stock_out')]

    def __str__(self):
        return f"{self.case.case_no} - {self.goods.name} - {self.batch_no}"


class RecallFreeze(models.Model):
    """按案件施加的批次冻结记录

    冻结以"案件 × 货物 × 批次"为粒度独立计数；货物总冻结状态由所有
    执行中案件的有效冻结汇总，关闭一个案件只解除该案冻结。
    """
    case = models.ForeignKey(
        RecallCase, on_delete=models.CASCADE,
        related_name='freezes', verbose_name='所属案件'
    )
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='recall_freezes', verbose_name='冻结货物'
    )
    batch_no = models.CharField('批次号', max_length=50)
    quantity = models.DecimalField('冻结数量', max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField('是否生效', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_recall_freeze'
        verbose_name = '召回冻结'
        verbose_name_plural = verbose_name
        ordering = ['case', 'id']
        unique_together = [('case', 'goods', 'batch_no')]

    def __str__(self):
        return f"{self.case.case_no} - {self.goods.name} - {self.quantity}"


class RecallRevision(models.Model):
    """召回影响清单变更记录（可复算、可说明增删原因）"""
    CHANGE_CHOICES = [
        ('added', '新增'),
        ('removed', '移除'),
        ('updated', '数量变更'),
    ]

    case = models.ForeignKey(
        RecallCase, on_delete=models.CASCADE,
        related_name='revisions', verbose_name='所属案件'
    )
    change_type = models.CharField('变更类型', max_length=20, choices=CHANGE_CHOICES)
    goods = models.ForeignKey(
        Goods, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='recall_revisions', verbose_name='货物'
    )
    batch_no = models.CharField('批次号', max_length=50, blank=True)
    location_status = models.CharField('库位状态', max_length=20, blank=True)
    qty_before = models.DecimalField('变更前数量', max_digits=12, decimal_places=2, null=True, blank=True)
    qty_after = models.DecimalField('变更后数量', max_digits=12, decimal_places=2, null=True, blank=True)
    reason = models.TextField('变更原因')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='recall_revisions', verbose_name='操作人'
    )
    created_at = models.DateTimeField('变更时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_recall_revision'
        verbose_name = '召回清单变更'
        verbose_name_plural = verbose_name
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"{self.case.case_no} - {self.get_change_type_display()}"


class RecallSnapshot(models.Model):
    """召回影响清单复算快照

    每次立案、依据变更或手动复算时留存当时的依据批次、完整影响清单
    与汇总结果，使历史影响范围可随时核对、重放。
    """
    case = models.ForeignKey(
        RecallCase, on_delete=models.CASCADE,
        related_name='snapshots', verbose_name='所属案件'
    )
    trigger = models.CharField('触发动作', max_length=30, default='create')
    batch_basis = models.JSONField('依据批次', default=list)
    items = models.JSONField('影响清单快照', default=list)
    summary = models.JSONField('复算汇总', default=dict)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='recall_snapshots', verbose_name='操作人'
    )
    created_at = models.DateTimeField('快照时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_recall_snapshot'
        verbose_name = '召回复算快照'
        verbose_name_plural = verbose_name
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"{self.case.case_no} - 快照 {self.id}"
