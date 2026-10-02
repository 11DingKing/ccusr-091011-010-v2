"""
召回案件序列化器
"""
from rest_framework import serializers

from .models import (
    RecallCase, RecallBasis, RecallItem,
    RecallFreeze, RecallRevision, RecallSnapshot,
)


class RecallBasisSerializer(serializers.ModelSerializer):
    """召回依据序列化器"""
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = RecallBasis
        fields = [
            'id', 'case', 'batch_no', 'source', 'source_display',
            'notice_no', 'evidence', 'created_by', 'created_by_name', 'created_at'
        ]
        read_only_fields = ['id', 'case', 'created_by', 'created_at']


class RecallBasisCreateSerializer(serializers.Serializer):
    """召回依据登记序列化器"""
    batch_no = serializers.CharField(max_length=50, required=True, error_messages={
        'required': '请输入缺陷批次号',
        'blank': '批次号不能为空',
    })
    source = serializers.ChoiceField(
        choices=RecallBasis.SOURCE_CHOICES, required=False, default='supplier_notice'
    )
    notice_no = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    evidence = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_batch_no(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('批次号不能为空')
        return value


class RecallCaseCreateSerializer(serializers.Serializer):
    """召回案件立案序列化器"""
    title = serializers.CharField(max_length=200, required=True, error_messages={
        'required': '请输入案件名称',
        'blank': '案件名称不能为空',
    })
    case_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    supplier = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    description = serializers.CharField(required=False, allow_blank=True, default='')
    batch_nos = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=True, allow_empty=False,
        error_messages={'required': '请提供至少一个缺陷批次号', 'empty': '批次号列表不能为空'},
    )
    source = serializers.ChoiceField(
        choices=RecallBasis.SOURCE_CHOICES, required=False, default='supplier_notice'
    )
    notice_no = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    evidence = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_batch_nos(self, value):
        cleaned = []
        for raw in value:
            batch = (raw or '').strip()
            if batch and batch not in cleaned:
                cleaned.append(batch)
        if not cleaned:
            raise serializers.ValidationError('请提供至少一个有效的缺陷批次号')
        return cleaned

    def validate_case_no(self, value):
        value = (value or '').strip()
        if value and RecallCase.objects.filter(case_no=value).exists():
            raise serializers.ValidationError('案件编号已存在')
        return value


class RecallItemSerializer(serializers.ModelSerializer):
    """召回影响条目序列化器"""
    goods_code = serializers.CharField(source='goods.code', read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    location_status_display = serializers.CharField(
        source='get_location_status_display', read_only=True
    )
    stock_out_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = RecallItem
        fields = [
            'id', 'goods', 'goods_code', 'goods_name', 'stock_out_id',
            'batch_no', 'location_status', 'location_status_display',
            'affected_qty', 'frozen_qty',
            'receiver', 'receiver_dept', 'last_known_status', 'trace_detail',
            'is_active', 'first_seen_at', 'updated_at'
        ]


class RecallFreezeSerializer(serializers.ModelSerializer):
    """召回冻结序列化器"""
    case_no = serializers.CharField(source='case.case_no', read_only=True)
    goods_code = serializers.CharField(source='goods.code', read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True)

    class Meta:
        model = RecallFreeze
        fields = [
            'id', 'case', 'case_no', 'goods', 'goods_code', 'goods_name',
            'batch_no', 'quantity', 'is_active', 'created_at', 'updated_at'
        ]


class RecallRevisionSerializer(serializers.ModelSerializer):
    """召回清单变更记录序列化器"""
    change_type_display = serializers.CharField(
        source='get_change_type_display', read_only=True
    )
    goods_code = serializers.CharField(source='goods.code', read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = RecallRevision
        fields = [
            'id', 'change_type', 'change_type_display',
            'goods', 'goods_code', 'goods_name', 'batch_no', 'location_status',
            'qty_before', 'qty_after', 'reason',
            'created_by', 'created_by_name', 'created_at'
        ]


class RecallSnapshotSerializer(serializers.ModelSerializer):
    """召回复算快照序列化器"""
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = RecallSnapshot
        fields = [
            'id', 'trigger', 'batch_basis', 'items', 'summary',
            'created_by', 'created_by_name', 'created_at'
        ]


class RecallCaseSerializer(serializers.ModelSerializer):
    """召回案件序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    closed_by_name = serializers.CharField(source='closed_by.username', read_only=True)
    bases = RecallBasisSerializer(many=True, read_only=True)
    active_item_count = serializers.SerializerMethodField()
    frozen_quantity_total = serializers.SerializerMethodField()

    class Meta:
        model = RecallCase
        fields = [
            'id', 'case_no', 'title', 'supplier', 'description',
            'status', 'status_display',
            'created_by', 'created_by_name', 'closed_by', 'closed_by_name',
            'closed_at', 'created_at', 'updated_at',
            'bases', 'active_item_count', 'frozen_quantity_total',
        ]

    def get_active_item_count(self, obj):
        return obj.items.filter(is_active=True).count()

    def get_frozen_quantity_total(self, obj):
        from django.db.models import Sum
        total = obj.freezes.filter(
            is_active=True, case__status='open'
        ).aggregate(t=Sum('quantity'))['t']
        return total or 0
