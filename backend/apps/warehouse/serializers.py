"""
仓库管理序列化器
"""
from rest_framework import serializers
from .models import (
    Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval,
    Batch, BatchMovement, RecallCase, RecallItem, RecallVersion,
)


class UnitSerializer(serializers.ModelSerializer):
    """单位序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = Unit
        fields = [
            'id', 'name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class UnitCreateSerializer(serializers.Serializer):
    """单位创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=5, required=True, error_messages={
        'required': '请输入单位名称',
        'blank': '单位名称不能为空',
        'min_length': '单位名称至少1个字',
        'max_length': '单位名称最多5个字',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Unit.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('单位名称已存在')
        else:
            if Unit.objects.filter(name=value).exists():
                raise serializers.ValidationError('单位名称已存在')
        return value


class CategorySerializer(serializers.ModelSerializer):
    """品类序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)
    
    class Meta:
        model = Category
        fields = [
            'id', 'name', 'unit', 'unit_name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CategoryCreateSerializer(serializers.Serializer):
    """品类创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=10, required=True, error_messages={
        'required': '请输入品类名称',
        'blank': '品类名称不能为空',
        'min_length': '品类名称至少1个字',
        'max_length': '品类名称最多10个字',
    })
    unit = serializers.IntegerField(required=True, error_messages={
        'required': '请选择单位',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Category.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('品类名称已存在')
        else:
            if Category.objects.filter(name=value).exists():
                raise serializers.ValidationError('品类名称已存在')
        return value
    
    def validate_unit(self, value):
        if not Unit.objects.filter(pk=value).exists():
            raise serializers.ValidationError('单位不存在')
        return value


class VarietySerializer(serializers.ModelSerializer):
    """品种序列化器"""
    is_in_stock = serializers.BooleanField(read_only=True)
    unit_name = serializers.CharField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    class Meta:
        model = Variety
        fields = [
            'id', 'name', 'category', 'category_name', 'unit_name',
            'is_in_stock', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class VarietyCreateSerializer(serializers.Serializer):
    """品种创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=20, required=True, error_messages={
        'required': '请输入品种名称',
        'blank': '品种名称不能为空',
        'min_length': '品种名称至少1个字',
        'max_length': '品种名称最多20个字',
    })
    category = serializers.IntegerField(required=True, error_messages={
        'required': '请选择品类',
    })
    
    def validate_category(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('品类不存在')
        return value
    
    def validate(self, data):
        instance = self.context.get('instance')
        name = data['name']
        category_id = data['category']
        
        if instance:
            if Variety.objects.filter(name=name, category_id=category_id).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        else:
            if Variety.objects.filter(name=name, category_id=category_id).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        return data


class GoodsSerializer(serializers.ModelSerializer):
    """货物序列化器"""
    variety_name = serializers.CharField(source='variety.name', read_only=True)
    category_name = serializers.CharField(source='variety.category.name', read_only=True)
    unit_name = serializers.CharField(source='variety.category.unit.name', read_only=True)
    is_warning = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Goods
        fields = [
            'id', 'name', 'code', 'variety', 'variety_name',
            'category_name', 'unit_name', 'specification',
            'quantity', 'warning_threshold', 'location',
            'remark', 'is_active', 'is_warning',
            'created_at', 'updated_at'
        ]


class StockInSerializer(serializers.ModelSerializer):
    """入库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    
    class Meta:
        model = StockIn
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'quantity', 'batch_no', 'supplier', 'stock_in_time', 'remark'
        ]


class StockOutSerializer(serializers.ModelSerializer):
    """出库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = StockOut
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'receiver', 'receiver_dept', 'quantity', 'status', 'status_display',
            'stock_out_time', 'remark', 'created_at'
        ]


class WarningSerializer(serializers.ModelSerializer):
    """预警记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    
    class Meta:
        model = Warning
        fields = [
            'id', 'goods', 'goods_name', 'type', 'type_display',
            'message', 'is_read', 'created_at'
        ]


class ApprovalSerializer(serializers.ModelSerializer):
    """审批记录序列化器"""
    approver_name = serializers.CharField(source='approver.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Approval
        fields = [
            'id', 'stock_out', 'approver', 'approver_name',
            'status', 'status_display', 'remark', 'created_at', 'updated_at'
        ]


# ==================== 批次谱系 ====================

class BatchMovementSerializer(serializers.ModelSerializer):
    """批次流转事件序列化器"""
    movement_type_display = serializers.CharField(source='get_movement_type_display', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)

    class Meta:
        model = BatchMovement
        fields = [
            'id', 'batch', 'movement_type', 'movement_type_display',
            'from_location', 'to_location', 'holder_name', 'holder_dept',
            'quantity', 'remark', 'operator', 'operator_name', 'created_at'
        ]


class BatchSerializer(serializers.ModelSerializer):
    """批次序列化器"""
    relation_display = serializers.CharField(source='get_relation_display', read_only=True)
    location_status_display = serializers.CharField(source='get_location_status_display', read_only=True)
    is_frozen = serializers.BooleanField(read_only=True)
    is_in_stock = serializers.BooleanField(read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    parent_id = serializers.IntegerField(source='parent.id', read_only=True)
    active_freeze_cases = serializers.SerializerMethodField()

    class Meta:
        model = Batch
        fields = [
            'id', 'batch_no', 'goods', 'goods_name', 'parent_id', 'relation',
            'relation_display', 'supplier', 'quantity', 'location',
            'location_status', 'location_status_display', 'is_current',
            'is_frozen', 'is_in_stock', 'holder_name', 'holder_dept',
            'holder_contact', 'last_known_status', 'out_record',
            'created_by', 'created_at', 'updated_at', 'active_freeze_cases'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_active_freeze_cases(self, obj):
        return [
            {'id': c.id, 'case_no': c.case_no, 'title': c.title}
            for c in obj.active_freeze_cases
        ]


class BatchCreateSerializer(serializers.Serializer):
    """入库批次创建序列化器（登记通报可追溯的批次）"""
    batch_no = serializers.CharField(max_length=50, required=True, error_messages={
        'required': '请输入批次号', 'blank': '批次号不能为空'})
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择货物'})
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False)
    supplier = serializers.CharField(max_length=200, required=False, allow_blank=True)
    location = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value).exists():
            raise serializers.ValidationError('货物不存在')
        return value


# ==================== 召回案件 ====================

class RecallCaseSerializer(serializers.ModelSerializer):
    """召回案件序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    closed_by_name = serializers.CharField(source='closed_by.username', read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    item_count = serializers.SerializerMethodField()
    frozen_count = serializers.SerializerMethodField()
    out_count = serializers.SerializerMethodField()

    class Meta:
        model = RecallCase
        fields = [
            'id', 'title', 'case_no', 'notified_batch_no', 'goods', 'goods_name',
            'supplier', 'basis', 'defect_desc', 'status', 'status_display',
            'created_by', 'created_by_name', 'closed_by', 'closed_by_name',
            'closed_at', 'close_remark', 'created_at', 'updated_at',
            'item_count', 'frozen_count', 'out_count'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'closed_at']

    def get_item_count(self, obj):
        return obj.items.filter(is_active=True).count()

    def get_frozen_count(self, obj):
        return obj.items.filter(is_active=True, is_frozen=True).count()

    def get_out_count(self, obj):
        return obj.items.filter(is_active=True, impact_status='out').count()


class RecallCaseCreateSerializer(serializers.Serializer):
    """召回案件创建序列化器"""
    title = serializers.CharField(min_length=1, max_length=200, required=True, error_messages={
        'required': '请输入案件名称', 'blank': '案件名称不能为空'})
    case_no = serializers.CharField(min_length=1, max_length=50, required=True, error_messages={
        'required': '请输入案件编号', 'blank': '案件编号不能为空'})
    notified_batch_no = serializers.CharField(min_length=1, max_length=50, required=True, error_messages={
        'required': '请输入通报批次号', 'blank': '通报批次号不能为空'})
    goods = serializers.IntegerField(required=True, error_messages={'required': '请选择涉事物资'})
    supplier = serializers.CharField(max_length=200, required=False, allow_blank=True)
    basis = serializers.CharField(required=False, allow_blank=True)
    defect_desc = serializers.CharField(required=False, allow_blank=True)

    def validate_case_no(self, value):
        if RecallCase.objects.filter(case_no=value).exists():
            raise serializers.ValidationError('案件编号已存在')
        return value

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value).exists():
            raise serializers.ValidationError('货物不存在')
        return value


class RecallItemSerializer(serializers.ModelSerializer):
    """召回影响项序列化器"""
    batch_no = serializers.CharField(source='batch.batch_no', read_only=True)
    impact_status_display = serializers.CharField(source='get_impact_status_display', read_only=True)
    relation = serializers.CharField(source='batch.relation', read_only=True)
    relation_display = serializers.CharField(source='batch.get_relation_display', read_only=True)
    location = serializers.CharField(source='batch.location', read_only=True)
    freeze_case_nos = serializers.SerializerMethodField()

    class Meta:
        model = RecallItem
        fields = [
            'id', 'case', 'batch', 'batch_no', 'relation', 'relation_display',
            'location', 'impact_status', 'impact_status_display', 'is_active',
            'is_frozen', 'lineage_path', 'included_reason',
            'holder_name', 'holder_dept', 'holder_contact', 'last_known_status',
            'first_included_at', 'removed_at', 'remove_reason',
            'created_at', 'updated_at', 'freeze_case_nos'
        ]
        read_only_fields = ['id', 'case', 'created_at', 'updated_at']

    def get_freeze_case_nos(self, obj):
        """该批次当前仍生效的全部召回案件（证明多案件限制独立保留）"""
        return [c.case_no for c in obj.batch.active_freeze_cases]


class RecallVersionSerializer(serializers.ModelSerializer):
    """召回清单复算版本序列化器"""
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = RecallVersion
        fields = [
            'id', 'case', 'version_no', 'snapshot', 'added', 'removed',
            'changed', 'change_reason', 'frozen_count', 'out_count',
            'created_by_name', 'created_at'
        ]
