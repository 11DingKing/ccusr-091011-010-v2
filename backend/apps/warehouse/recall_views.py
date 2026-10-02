"""
召回案件视图

立案 -> 按批次谱系复算影响范围 -> 冻结在库物资 / 列出离库责任人；
同一对象多宗召回分别保留依据；关闭案件仅解除该案冻结。
"""
import logging

from django.db import transaction
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from apps.core.response import success_response, error_response
from .models import (
    RecallCase, RecallBasis,
    RecallFreeze, RecallSnapshot,
)
from .recall import apply_case_impact, close_case
from .recall_serializers import (
    RecallCaseSerializer, RecallCaseCreateSerializer,
    RecallBasisSerializer, RecallBasisCreateSerializer,
    RecallItemSerializer, RecallFreezeSerializer,
    RecallRevisionSerializer, RecallSnapshotSerializer,
)

logger = logging.getLogger('apps')


def _paginate(request, queryset, serializer_cls):
    """统一分页"""
    page = max(int(request.query_params.get('page', 1)), 1)
    page_size = max(int(request.query_params.get('page_size', 10)), 1)
    total = queryset.count()
    rows = queryset[(page - 1) * page_size: page * page_size]
    return {
        'list': serializer_cls(rows, many=True).data,
        'total': total,
        'page': page,
        'page_size': page_size,
    }


class RecallCaseListView(APIView):
    """召回案件列表 / 立案"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = RecallCase.objects.all().prefetch_related('bases')
        status = request.query_params.get('status')
        if status in ('open', 'closed'):
            queryset = queryset.filter(status=status)
        keyword = request.query_params.get('keyword', '').strip()
        if keyword:
            queryset = queryset.filter(
                Q(case_no__icontains=keyword)
                | Q(title__icontains=keyword)
                | Q(supplier__icontains=keyword)
            )
        return success_response(data=_paginate(request, queryset, RecallCaseSerializer))

    def post(self, request):
        """建立召回案件并立即按批次谱系计算影响范围、冻结在库物资"""
        serializer = RecallCaseCreateSerializer(data=request.data)
        if not serializer.is_valid():
            first_error = list(serializer.errors.values())[0]
            if isinstance(first_error, list):
                first_error = first_error[0]
            return error_response(message=str(first_error))
        data = serializer.validated_data

        case_no = data.get('case_no') or RecallCase.generate_case_no()
        with transaction.atomic():
            case = RecallCase.objects.create(
                case_no=case_no,
                title=data['title'],
                supplier=data['supplier'],
                description=data['description'],
                created_by=request.user,
            )
            for batch_no in data['batch_nos']:
                RecallBasis.objects.create(
                    case=case, batch_no=batch_no, source=data['source'],
                    notice_no=data['notice_no'], evidence=data['evidence'],
                    created_by=request.user,
                )
            summary = apply_case_impact(
                case, request.user,
                reason_note='立案首次计算', trigger='create',
            )

        logger.info(
            f"User {request.user.username} created recall case {case.case_no} "
            f"for batches {data['batch_nos']}"
        )
        return success_response(
            data={'case': RecallCaseSerializer(case).data, 'recompute': summary},
            message='召回案件已建立，影响清单已生成并冻结在库物资',
        )


class RecallCaseDetailView(APIView):
    """召回案件详情"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            case = RecallCase.objects.prefetch_related('bases').get(pk=pk)
        except RecallCase.DoesNotExist:
            return error_response(message='召回案件不存在', code=404)
        return success_response(data=RecallCaseSerializer(case).data)


class RecallCaseCloseView(APIView):
    """关闭召回案件（仅解除本案冻结，不影响其他案件）"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            case = RecallCase.objects.get(pk=pk)
        except RecallCase.DoesNotExist:
            return error_response(message='召回案件不存在', code=404)

        if not case.is_open:
            return error_response(message='案件已关闭，请勿重复操作')

        with transaction.atomic():
            closed = close_case(case, request.user)
        if not closed:
            return error_response(message='案件关闭失败')

        logger.info(f"User {request.user.username} closed recall case {case.case_no}")
        return success_response(
            data=RecallCaseSerializer(case).data,
            message='案件已关闭，本案冻结已解除；其他召回案件的限制不受影响',
        )


class RecallBasisListView(APIView):
    """案件依据列表 / 追加依据"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            case = RecallCase.objects.get(pk=pk)
        except RecallCase.DoesNotExist:
            return error_response(message='召回案件不存在', code=404)
        return success_response(
            data=_paginate(request, case.bases.all().order_by('-id'), RecallBasisSerializer)
        )

    def post(self, request, pk):
        """向执行中的案件追加缺陷批次依据，并复算影响清单"""
        try:
            case = RecallCase.objects.get(pk=pk)
        except RecallCase.DoesNotExist:
            return error_response(message='召回案件不存在', code=404)
        if not case.is_open:
            return error_response(message='案件已关闭，不能追加依据')

        serializer = RecallBasisCreateSerializer(data=request.data)
        if not serializer.is_valid():
            first_error = list(serializer.errors.values())[0]
            if isinstance(first_error, list):
                first_error = first_error[0]
            return error_response(message=str(first_error))
        data = serializer.validated_data

        if case.bases.filter(batch_no=data['batch_no']).exists():
            return error_response(message=f"批次 {data['batch_no']} 的依据已存在，请勿重复登记")

        with transaction.atomic():
            basis = RecallBasis.objects.create(
                case=case, batch_no=data['batch_no'], source=data['source'],
                notice_no=data['notice_no'], evidence=data['evidence'],
                created_by=request.user,
            )
            summary = apply_case_impact(
                case, request.user,
                reason_note=f"追加批次 {data['batch_no']} 依据", trigger='basis_added',
            )

        logger.info(
            f"User {request.user.username} added basis batch {basis.batch_no} "
            f"to recall case {case.case_no}"
        )
        return success_response(
            data={'basis': RecallBasisSerializer(basis).data, 'recompute': summary},
            message='依据已追加，影响清单已复算',
        )


class RecallBasisDetailView(APIView):
    """删除单条召回依据并复算（仅执行中案件）"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk, basis_id):
        try:
            case = RecallCase.objects.get(pk=pk)
        except RecallCase.DoesNotExist:
            return error_response(message='召回案件不存在', code=404)
        if not case.is_open:
            return error_response(message='案件已关闭，不能移除依据')

        basis = case.bases.filter(pk=basis_id).first()
        if basis is None:
            return error_response(message='召回依据不存在', code=404)
        batch_no = basis.batch_no
        with transaction.atomic():
            basis.delete()
            summary = apply_case_impact(
                case, request.user,
                reason_note=f"移除批次 {batch_no} 依据", trigger='basis_removed',
            )
        logger.info(
            f"User {request.user.username} removed basis batch {batch_no} "
            f"from recall case {case.case_no}"
        )
        return success_response(data=summary, message='依据已移除，影响清单已复算')


class RecallRecomputeView(APIView):
    """手动复算案件影响清单（案件更新后可随时重算并说明增删原因）"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            case = RecallCase.objects.get(pk=pk)
        except RecallCase.DoesNotExist:
            return error_response(message='召回案件不存在', code=404)
        if not case.is_open:
            return error_response(message='案件已关闭，无需复算')

        note = (request.data.get('note') or '').strip() if request.data else ''
        with transaction.atomic():
            summary = apply_case_impact(
                case, request.user, reason_note=note or '手动复算', trigger='manual',
            )
        return success_response(data=summary, message='影响清单复算完成')


class RecallItemListView(APIView):
    """案件影响清单：在库冻结对象与已离库对象（含责任人/最后状态）"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            case = RecallCase.objects.get(pk=pk)
        except RecallCase.DoesNotExist:
            return error_response(message='召回案件不存在', code=404)

        queryset = case.items.select_related('goods', 'stock_out')
        location = request.query_params.get('location_status')
        if location in ('in_stock', 'out'):
            queryset = queryset.filter(location_status=location)
        is_active = request.query_params.get('is_active')
        if is_active in ('true', 'false'):
            queryset = queryset.filter(is_active=(is_active == 'true'))
        batch_no = request.query_params.get('batch_no', '').strip()
        if batch_no:
            queryset = queryset.filter(batch_no=batch_no)

        data = _paginate(request, queryset.order_by('-is_active', 'location_status', 'id'),
                         RecallItemSerializer)

        # 汇总：在库冻结数量 / 离库去向数量
        active = case.items.filter(is_active=True)
        data['summary'] = {
            'in_stock_count': active.filter(location_status='in_stock').count(),
            'out_count': active.filter(location_status='out').count(),
        }
        return success_response(data=data)


class RecallRevisionListView(APIView):
    """案件影响清单变更记录（新增 / 移除原因）"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            case = RecallCase.objects.get(pk=pk)
        except RecallCase.DoesNotExist:
            return error_response(message='召回案件不存在', code=404)
        queryset = case.revisions.select_related('goods', 'created_by')
        change_type = request.query_params.get('change_type')
        if change_type in ('added', 'removed', 'updated'):
            queryset = queryset.filter(change_type=change_type)
        return success_response(
            data=_paginate(request, queryset, RecallRevisionSerializer)
        )


class RecallSnapshotListView(APIView):
    """案件复算快照列表"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            case = RecallCase.objects.get(pk=pk)
        except RecallCase.DoesNotExist:
            return error_response(message='召回案件不存在', code=404)
        return success_response(
            data=_paginate(request, case.snapshots.all(), RecallSnapshotSerializer)
        )


class RecallSnapshotDetailView(APIView):
    """单次复算快照详情"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, snapshot_id):
        snapshot = RecallSnapshot.objects.filter(case_id=pk, pk=snapshot_id).first()
        if snapshot is None:
            return error_response(message='快照不存在', code=404)
        return success_response(data=RecallSnapshotSerializer(snapshot).data)


class RecallFreezeListView(APIView):
    """冻结记录查询（可按案件或货物筛选）"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = RecallFreeze.objects.select_related('case', 'goods')
        case_id = request.query_params.get('case')
        if case_id:
            queryset = queryset.filter(case_id=case_id)
        goods_id = request.query_params.get('goods')
        if goods_id:
            queryset = queryset.filter(goods_id=goods_id)
        active = request.query_params.get('is_active')
        if active in ('true', 'false'):
            queryset = queryset.filter(is_active=(active == 'true'))
        return success_response(
            data=_paginate(request, queryset.order_by('-id'), RecallFreezeSerializer)
        )
