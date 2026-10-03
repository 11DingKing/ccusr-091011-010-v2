"""
库房管理模型
"""
from django.db import models
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


class Batch(models.Model):
    """批次节点：在库批次谱系中的一个节点。

    通过 parent 自关联形成谱系树：入库批次为根，拆分/转移生成子节点，
    领用出库生成叶子离库节点。沿谱系向上可追溯到通报批次。
    """
    RELATION_ROOT = 'root'
    RELATION_SPLIT = 'split'
    RELATION_TRANSFER = 'transfer'
    RELATION_COLLECT = 'collect'
    RELATION_CHOICES = [
        (RELATION_ROOT, '入库'),
        (RELATION_SPLIT, '拆分'),
        (RELATION_TRANSFER, '转移'),
        (RELATION_COLLECT, '领用'),
    ]

    LOCATION_IN_STOCK = 'in_stock'
    LOCATION_OUT = 'out'
    LOCATION_CHOICES = [
        (LOCATION_IN_STOCK, '在库'),
        (LOCATION_OUT, '已离库'),
    ]

    batch_no = models.CharField('批次号', max_length=50, db_index=True)
    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='batches', verbose_name='货物'
    )
    parent = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='children', verbose_name='来源批次'
    )
    relation = models.CharField(
        '与来源批次关系', max_length=20,
        choices=RELATION_CHOICES, default=RELATION_ROOT
    )
    supplier = models.CharField('供应方', max_length=200, blank=True)
    quantity = models.DecimalField('批次数量', max_digits=12, decimal_places=2, default=0)
    location = models.CharField('所在位置', max_length=100, blank=True)
    location_status = models.CharField(
        '库位状态', max_length=20,
        choices=LOCATION_CHOICES, default=LOCATION_IN_STOCK
    )
    # 是否代表当前现存实物。转移/领用后原节点置为非当前（历史节点），
    # 仅保留在谱系路径中；拆分时父节点仍为当前（库存相应核减）。
    is_current = models.BooleanField('是否现存', default=True)
    # 离库责任人（领用人）与最后已知状态，离库时写入并快照保留
    holder_name = models.CharField('离库责任人', max_length=100, blank=True)
    holder_dept = models.CharField('责任部门', max_length=100, blank=True)
    holder_contact = models.CharField('责任人联系方式', max_length=50, blank=True)
    last_known_status = models.CharField('最后已知状态', max_length=200, blank=True)
    out_record = models.ForeignKey(
        StockOut, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='batches', verbose_name='出库记录'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_batches', verbose_name='创建人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_batch'
        verbose_name = '批次'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['batch_no']),
            models.Index(fields=['location_status']),
        ]

    def __str__(self):
        return f"{self.batch_no}({self.get_relation_display()})"

    @property
    def is_in_stock(self):
        return self.location_status == self.LOCATION_IN_STOCK

    @property
    def is_frozen(self):
        """是否被任一未关闭召回案件冻结。

        冻结状态派生自未关闭案件下的有效冻结项，因此关闭某宗案件
        只会解除该案件的限制；若对象仍被另一宗案件召回，则继续冻结。
        """
        return self.recall_items.filter(
            is_active=True,
            is_frozen=True,
            case__status=RecallCase.STATUS_OPEN,
        ).exists()

    @property
    def active_freeze_cases(self):
        """当前仍对本批次生效的召回案件"""
        return RecallCase.objects.filter(
            status=RecallCase.STATUS_OPEN,
            items__batch=self,
            items__is_active=True,
            items__is_frozen=True,
        ).distinct()

    def ancestors(self):
        """沿 parent 链向上返回全部祖先批次（含自身）"""
        nodes = []
        node = self
        seen = set()
        while node is not None and node.id not in seen:
            nodes.append(node)
            seen.add(node.id)
            node = node.parent
        return nodes


class BatchMovement(models.Model):
    """批次流转事件：记录拆分、转移、领用等每次流转。

    事件流水与批次谱系共同构成可复算的去向依据。
    """
    TYPE_CHOICES = [
        (Batch.RELATION_SPLIT, '拆分'),
        (Batch.RELATION_TRANSFER, '转移'),
        (Batch.RELATION_COLLECT, '领用'),
    ]

    batch = models.ForeignKey(
        Batch, on_delete=models.CASCADE,
        related_name='movements', verbose_name='流转批次'
    )
    movement_type = models.CharField('流转类型', max_length=20, choices=TYPE_CHOICES)
    from_location = models.CharField('原位置', max_length=100, blank=True)
    to_location = models.CharField('目标位置', max_length=100, blank=True)
    holder_name = models.CharField('领用人', max_length=100, blank=True)
    holder_dept = models.CharField('领用部门', max_length=100, blank=True)
    quantity = models.DecimalField('流转数量', max_digits=12, decimal_places=2, default=0)
    remark = models.TextField('备注', blank=True)
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='batch_movements', verbose_name='操作人'
    )
    created_at = models.DateTimeField('流转时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_batch_movement'
        verbose_name = '批次流转事件'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.batch.batch_no}-{self.get_movement_type_display()}"


class RecallCase(models.Model):
    """召回案件：供应方通报某批次存在缺陷后立案。

    同一对象可被多宗案件分别召回，各案件的依据（RecallItem）独立保留；
    关闭一宗案件只解除本案件施加的冻结，不影响其他案件。
    """
    STATUS_OPEN = 'open'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = [
        (STATUS_OPEN, '处置中'),
        (STATUS_CLOSED, '已关闭'),
    ]

    title = models.CharField('案件名称', max_length=200)
    case_no = models.CharField('案件编号', max_length=50, unique=True)
    notified_batch_no = models.CharField('通报批次号', max_length=50, db_index=True)
    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='recall_cases', verbose_name='涉事物资'
    )
    supplier = models.CharField('通报供应方', max_length=200, blank=True)
    basis = models.TextField('召回依据', blank=True)
    defect_desc = models.TextField('缺陷描述', blank=True)
    status = models.CharField(
        '案件状态', max_length=20,
        choices=STATUS_CHOICES, default=STATUS_OPEN
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_recall_cases', verbose_name='立案人'
    )
    closed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='closed_recall_cases', verbose_name='关闭人'
    )
    closed_at = models.DateTimeField('关闭时间', null=True, blank=True)
    close_remark = models.TextField('关闭说明', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_recall_case'
        verbose_name = '召回案件'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.case_no}-{self.title}"


class RecallItem(models.Model):
    """召回影响清单项：案件 × 批次 的独立依据记录。

    同一批次被多宗案件召回时，每宗案件各持一条，依据与冻结状态互不影响。
    lineage_path 记录该批次被纳入本案件的谱系路径（批次id链），
    是"为何受影响"的可复核依据。
    """
    STATUS_IN_STOCK = 'in_stock'
    STATUS_OUT = 'out'
    IMPACT_STATUS_CHOICES = [
        (STATUS_IN_STOCK, '在库已冻结'),
        (STATUS_OUT, '已离库'),
    ]

    case = models.ForeignKey(
        RecallCase, on_delete=models.CASCADE,
        related_name='items', verbose_name='召回案件'
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT,
        related_name='recall_items', verbose_name='受影响批次'
    )
    is_active = models.BooleanField('是否仍在影响范围', default=True)
    is_frozen = models.BooleanField('是否已冻结', default=False)
    impact_status = models.CharField(
        '影响状态', max_length=20, choices=IMPACT_STATUS_CHOICES, default=STATUS_IN_STOCK
    )
    lineage_path = models.JSONField('谱系路径', default=list)
    included_reason = models.CharField('纳入依据', max_length=200, blank=True)
    # 离库对象责任人与最后已知状态快照（离库后不再随批次变动）
    holder_name = models.CharField('离库责任人', max_length=100, blank=True)
    holder_dept = models.CharField('责任部门', max_length=100, blank=True)
    holder_contact = models.CharField('责任人联系方式', max_length=50, blank=True)
    last_known_status = models.CharField('最后已知状态', max_length=200, blank=True)
    first_included_at = models.DateTimeField('首次纳入时间', auto_now_add=True)
    removed_at = models.DateTimeField('移出时间', null=True, blank=True)
    remove_reason = models.CharField('移出原因', max_length=200, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_recall_item'
        verbose_name = '召回影响项'
        verbose_name_plural = verbose_name
        unique_together = ['case', 'batch']
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.case.case_no}-{self.batch.batch_no}"


class RecallVersion(models.Model):
    """召回清单复算版本：案件每次更新后保存清单快照与差异原因。

    使影响清单可复算，并说明本次相对上一版本新增/移除/变更了什么及原因。
    """
    case = models.ForeignKey(
        RecallCase, on_delete=models.CASCADE,
        related_name='versions', verbose_name='召回案件'
    )
    version_no = models.PositiveIntegerField('版本号')
    snapshot = models.JSONField('影响清单快照', default=list)
    added = models.JSONField('本次新增', default=list)
    removed = models.JSONField('本次移除', default=list)
    changed = models.JSONField('本次变更', default=list)
    change_reason = models.TextField('变更原因', blank=True)
    frozen_count = models.PositiveIntegerField('在库冻结数', default=0)
    out_count = models.PositiveIntegerField('已离库数', default=0)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='recall_versions', verbose_name='复算人'
    )
    created_at = models.DateTimeField('复算时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_recall_version'
        verbose_name = '召回清单版本'
        verbose_name_plural = verbose_name
        unique_together = ['case', 'version_no']
        ordering = ['case', '-version_no']

    def __str__(self):
        return f"{self.case.case_no}-v{self.version_no}"
