"""
批次谱系与召回案件视图。
"""
import logging
from decimal import Decimal, InvalidOperation

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.response import success_response, error_response
from .models import Batch, BatchMovement, Goods, RecallCase, RecallVersion
from .serializers import (
    BatchSerializer, BatchCreateSerializer, BatchMovementSerializer,
    RecallCaseSerializer, RecallCaseCreateSerializer,
    RecallItemSerializer, RecallVersionSerializer,
)
from . import recall_service

logger = logging.getLogger('apps')


def _first_error(serializer):
    errors = serializer.errors
    first = list(errors.values())[0]
    if isinstance(first, list):
        first = first[0]
    return str(first)


def _paginate(queryset, request):
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 10))
    total = queryset.count()
    start = (page - 1) * page_size
    return queryset[start:start + page_size], total, page, page_size


# ==================== 批次谱系 ====================

class BatchListView(APIView):
    """批次列表 / 登记入库批次"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Batch.objects.select_related('goods').all().order_by('-created_at')
        batch_no = request.query_params.get('batch_no')
        if batch_no:
            queryset = queryset.filter(batch_no=batch_no)
        goods_id = request.query_params.get('goods')
        if goods_id:
            queryset = queryset.filter(goods_id=goods_id)
        current = request.query_params.get('is_current')
        if current is not None:
            queryset = queryset.filter(is_current=current.lower() == 'true')

        batches, total, page, page_size = _paginate(queryset, request)
        return success_response(data={
            'list': BatchSerializer(batches, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    def post(self, request):
        """登记入库批次（谱系根节点）"""
        serializer = BatchCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer))
        data = serializer.validated_data
        batch = Batch.objects.create(
            batch_no=data['batch_no'],
            goods=Goods.objects.get(pk=data['goods']),
            relation=Batch.RELATION_ROOT,
            supplier=data.get('supplier', ''),
            quantity=data.get('quantity', 0),
            location=data.get('location', ''),
            created_by=request.user,
        )
        logger.info("User %s registered batch %s", request.user.username, batch.batch_no)
        return success_response(data=BatchSerializer(batch).data, message='批次登记成功')


class BatchDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            batch = Batch.objects.select_related('goods', 'parent').get(pk=pk)
        except Batch.DoesNotExist:
            return error_response(message='批次不存在', code=404)
        return success_response(data=BatchSerializer(batch).data)


class BatchLineageView(APIView):
    """批次谱系：返回从通报根节点到当前节点的完整去向树/祖先链。"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            batch = Batch.objects.get(pk=pk)
        except Batch.DoesNotExist:
            return error_response(message='批次不存在', code=404)
        ancestors = batch.ancestors()
        return success_response(data={
            'batch_id': batch.id,
            'batch_no': batch.batch_no,
            'ancestors': [
                {
                    'batch_id': n.id,
                    'batch_no': n.batch_no,
                    'relation': n.relation,
                    'relation_display': n.get_relation_display(),
                    'location_status': n.location_status,
                    'is_current': n.is_current,
                    'location': n.location,
                    'holder_name': n.holder_name,
                }
                for n in ancestors
            ],
        })


class BatchMovementListView(APIView):
    """批次流转事件"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        movements = BatchMovement.objects.filter(batch_id=pk).select_related('operator')
        return success_response(data=BatchMovementSerializer(movements, many=True).data)


class BatchSplitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            parent = Batch.objects.get(pk=pk)
        except Batch.DoesNotExist:
            return error_response(message='批次不存在', code=404)
        child_no = request.data.get('child_batch_no')
        if not child_no:
            return error_response(message='请输入拆分后批次号')
        quantity = request.data.get('quantity')
        try:
            quantity = Decimal(str(quantity))
        except (InvalidOperation, TypeError, ValueError):
            return error_response(message='拆分数量无效')
        try:
            child = recall_service.split_batch(
                parent=parent, child_batch_no=child_no, quantity=quantity,
                location=request.data.get('location', ''), user=request.user,
                remark=request.data.get('remark', ''),
            )
        except recall_service.RecallError as e:
            return error_response(message=str(e))
        return success_response(data=BatchSerializer(child).data, message='拆分成功')


class BatchTransferView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            batch = Batch.objects.get(pk=pk)
        except Batch.DoesNotExist:
            return error_response(message='批次不存在', code=404)
        to_location = request.data.get('to_location')
        if not to_location:
            return error_response(message='请输入目标位置')
        try:
            moved = recall_service.transfer_batch(
                batch=batch, to_location=to_location, user=request.user,
                remark=request.data.get('remark', ''),
            )
        except recall_service.RecallError as e:
            return error_response(message=str(e))
        return success_response(data=BatchSerializer(moved).data, message='转移成功')


class BatchCollectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            batch = Batch.objects.get(pk=pk)
        except Batch.DoesNotExist:
            return error_response(message='批次不存在', code=404)
        try:
            out = recall_service.collect_batch(
                batch=batch,
                holder_name=request.data.get('holder_name', ''),
                holder_dept=request.data.get('holder_dept', ''),
                holder_contact=request.data.get('holder_contact', ''),
                last_known_status=request.data.get('last_known_status', ''),
                user=request.user,
                remark=request.data.get('remark', ''),
            )
        except recall_service.RecallError as e:
            return error_response(message=str(e))
        return success_response(data=BatchSerializer(out).data, message='领用离库登记成功')


# ==================== 召回案件 ====================

class RecallCaseListView(APIView):
    """召回案件列表 / 建立召回案件"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = RecallCase.objects.select_related('goods').all().order_by('-created_at')
        status = request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        batch_no = request.query_params.get('notified_batch_no')
        if batch_no:
            queryset = queryset.filter(notified_batch_no=batch_no)
        cases, total, page, page_size = _paginate(queryset, request)
        return success_response(data={
            'list': RecallCaseSerializer(cases, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    def post(self, request):
        serializer = RecallCaseCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer))
        data = serializer.validated_data
        try:
            goods = Goods.objects.get(pk=data['goods'])
            case, version = recall_service.create_recall_case(
                title=data['title'], case_no=data['case_no'],
                notified_batch_no=data['notified_batch_no'], goods=goods,
                user=request.user, supplier=data.get('supplier', ''),
                basis=data.get('basis', ''), defect_desc=data.get('defect_desc', ''),
            )
        except recall_service.RecallError as e:
            return error_response(message=str(e))
        logger.info("User %s created recall case %s", request.user.username, case.case_no)
        return success_response(
            data={
                'case': RecallCaseSerializer(case).data,
                'version': RecallVersionSerializer(version).data,
            },
            message='召回案件已建立并完成影响范围计算与在库冻结',
        )


class RecallCaseDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            case = RecallCase.objects.select_related('goods').get(pk=pk)
        except RecallCase.DoesNotExist:
            return error_response(message='召回案件不存在', code=404)
        return success_response(data=RecallCaseSerializer(case).data)


class RecallCaseItemsView(APIView):
    """案件影响清单（在库冻结 / 已离库责任人）。"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            case = RecallCase.objects.get(pk=pk)
        except RecallCase.DoesNotExist:
            return error_response(message='召回案件不存在', code=404)

        items = case.items.select_related('batch').all()
        scope = request.query_params.get('impact_status')
        if scope in ('in_stock', 'out'):
            items = items.filter(impact_status=scope)
        include_removed = request.query_params.get('include_removed') == 'true'
        if not include_removed:
            items = items.filter(is_active=True)

        data = RecallItemSerializer(items, many=True).data
        return success_response(data={
            'list': data,
            'total': len(data),
            'case_no': case.case_no,
            'case_status': case.status,
        })


class RecallCaseRecomputeView(APIView):
    """案件更新后复算影响清单，记录新增/移除/变更及原因。"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            case = RecallCase.objects.get(pk=pk)
        except RecallCase.DoesNotExist:
            return error_response(message='召回案件不存在', code=404)
        if case.status == RecallCase.STATUS_CLOSED:
            return error_response(message='案件已关闭，不能再复算；如需重新处置请另立新案件')
        reason = request.data.get('change_reason', '') or '手动触发复算'
        version = recall_service.recompute_case(case, request.user, change_reason=reason)
        return success_response(
            data=RecallVersionSerializer(version).data,
            message='影响清单已按当前批次谱系复算',
        )


class RecallCaseCloseView(APIView):
    """关闭案件，仅解除本案件冻结。"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            case = RecallCase.objects.get(pk=pk)
        except RecallCase.DoesNotExist:
            return error_response(message='召回案件不存在', code=404)
        try:
            case, version = recall_service.close_case(
                case, request.user, remark=request.data.get('remark', ''))
        except recall_service.RecallError as e:
            return error_response(message=str(e))
        logger.info("User %s closed recall case %s", request.user.username, case.case_no)
        return success_response(
            data={
                'case': RecallCaseSerializer(case).data,
                'version': RecallVersionSerializer(version).data,
            },
            message='案件已关闭，本案件冻结已解除；其他案件限制不受影响',
        )


class RecallCaseVersionsView(APIView):
    """案件影响清单的历次复算版本（可复算、可追溯）。"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not RecallCase.objects.filter(pk=pk).exists():
            return error_response(message='召回案件不存在', code=404)
        versions = RecallVersion.objects.filter(case_id=pk).select_related('created_by')
        return success_response(data=RecallVersionSerializer(versions, many=True).data)
