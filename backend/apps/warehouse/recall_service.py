"""
批次谱系与召回案件领域服务。

职责：
- 依据通报批次沿批次谱系（parent 自关联）计算全部受影响去向；
- 对尚在库的受影响批次施加冻结，对已离库对象快照责任人与最后已知状态；
- 案件更新后复算影响清单，记录新增/移除/变更及原因；
- 冻结状态按"未关闭案件 × 有效影响项"派生，保证多宗案件互不解除。
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import (
    Batch, BatchMovement, RecallCase, RecallItem, RecallVersion,
)


class RecallError(Exception):
    """召回业务错误"""


class FrozenBatchError(RecallError):
    """批次已被召回冻结，禁止流转"""


# ==================== 批次谱系 ====================

def lineage_seed_batches(notified_batch_no, goods):
    """通报批次对应的谱系起点（同批次号的入库根节点）。"""
    return list(
        Batch.objects.filter(
            batch_no=notified_batch_no,
            goods=goods,
            relation=Batch.RELATION_ROOT,
        )
    )


def collect_descendants(seed_batches):
    """从起点沿 children 关系广度遍历，返回 {batch_id: batch} 全集（含起点）。"""
    affected = {}
    frontier = list(seed_batches)
    while frontier:
        node = frontier.pop()
        if node.id in affected:
            continue
        affected[node.id] = node
        frontier.extend(node.children.all())
    return affected


def lineage_path_of(batch, seed_ids):
    """返回从通报起点到该批次的谱系路径（节点字典列表）。

    取一条起点在 seed_ids 内的祖先链；路径倒序为 起点 → 当前节点。
    """
    chain = batch.ancestors()  # [自身, parent, ...]
    cut = len(chain)
    for idx, node in enumerate(chain):
        if node.id in seed_ids:
            cut = idx
            break
    path_nodes = chain[: cut + 1][::-1]
    return [
        {
            'batch_id': node.id,
            'batch_no': node.batch_no,
            'relation': node.relation,
            'location_status': node.location_status,
        }
        for node in path_nodes
    ]


def inclusion_reason(path):
    """根据谱系路径生成人类可读的纳入依据。"""
    if len(path) <= 1:
        return '通报批次本体'
    steps = '→'.join(
        dict(Batch.RELATION_CHOICES).get(node['relation'], node['relation'])
        for node in path[1:]
    )
    root = path[0]['batch_no']
    return f"由通报批次 {root} 经{steps}派生"


def compute_scope(notified_batch_no, goods):
    """计算通报批次的影响范围，返回 [(batch, path, reason), ...]。

    范围限定为谱系中代表当前现存实物的节点（is_current=True）；
    转移/领用产生的历史节点仅保留在谱系路径中，不重复计入去向。
    """
    seeds = lineage_seed_batches(notified_batch_no, goods)
    seed_ids = {b.id for b in seeds}
    affected = collect_descendants(seeds)
    result = []
    for batch in affected.values():
        if not batch.is_current:
            continue
        path = lineage_path_of(batch, seed_ids)
        result.append((batch, path, inclusion_reason(path)))
    result.sort(key=lambda item: (item[0].created_at, item[0].id))
    return result


# ==================== 影响清单复算 ====================

def _snapshot_entry(item):
    return {
        'batch_id': item.batch_id,
        'batch_no': item.batch.batch_no,
        'relation': item.batch.relation,
        'impact_status': item.impact_status,
        'is_frozen': item.is_frozen,
        'is_active': item.is_active,
        'holder_name': item.holder_name,
        'holder_dept': item.holder_dept,
        'last_known_status': item.last_known_status,
        'location': item.batch.location,
        'included_reason': item.included_reason,
    }


def _apply_item_state(item, batch, path, reason):
    """按批次当前状态同步影响项的冻结/离库责任人快照，返回变更字段列表。"""
    changes = []
    if batch.is_in_stock:
        impact = RecallItem.STATUS_IN_STOCK
        if item.impact_status != impact:
            changes.append({'field': 'impact_status', 'to': impact})
            item.impact_status = impact
        if not item.is_frozen:
            changes.append({'field': 'is_frozen', 'to': True, 'reason': '在库物资纳入召回，予以冻结'})
            item.is_frozen = True
    else:
        impact = RecallItem.STATUS_OUT
        if item.impact_status != impact:
            changes.append({'field': 'impact_status', 'to': impact})
            item.impact_status = impact
        if item.is_frozen:
            changes.append({'field': 'is_frozen', 'to': False, 'reason': '物资已离库，无法在库冻结'})
            item.is_frozen = False
        for field, model_attr in (
            ('holder_name', 'holder_name'),
            ('holder_dept', 'holder_dept'),
            ('holder_contact', 'holder_contact'),
            ('last_known_status', 'last_known_status'),
        ):
            new_val = getattr(batch, model_attr)
            if getattr(item, field) != new_val:
                changes.append({'field': field, 'to': new_val})
                setattr(item, field, new_val)

    if item.lineage_path != path:
        changes.append({'field': 'lineage_path', 'reason': reason})
        item.lineage_path = path
    if item.included_reason != reason:
        item.included_reason = reason
    return changes


@transaction.atomic
def recompute_case(case, user, change_reason=''):
    """按当前批次谱系复算案件影响清单并生成新版本快照。

    差异分类：
    - added：谱系中新增（或曾被移出后重新纳入）的批次；
    - removed：不再归属通报批次谱系的批次；
    - changed：仍在范围内但冻结/离库/责任人状态发生变化的批次。
    """
    scope = compute_scope(case.notified_batch_no, case.goods)
    scope_map = {batch.id: (batch, path, reason) for batch, path, reason in scope}

    # 全部后代（含历史节点），用于区分"流转为历史节点"与"脱离谱系"
    seeds = lineage_seed_batches(case.notified_batch_no, case.goods)
    descendant_ids = set(collect_descendants(seeds).keys())

    existing = {item.batch_id: item for item in case.items.all()}
    added, removed, changed = [], [], []

    # 新增 / 更新
    for batch_id, (batch, path, reason) in scope_map.items():
        item = existing.get(batch_id)
        if item is None:
            item = RecallItem(case=case, batch=batch, lineage_path=path,
                              included_reason=reason)
            _apply_item_state(item, batch, path, reason)
            item.save()
            added.append({'batch_id': batch_id, 'batch_no': batch.batch_no,
                          'reason': reason})
            continue

        if not item.is_active:
            # 曾被移出，现重新回到谱系
            item.is_active = True
            item.removed_at = None
            item.remove_reason = ''
            item.lineage_path = path
            item.included_reason = reason
            _apply_item_state(item, batch, path, reason)
            item.save()
            added.append({'batch_id': batch_id, 'batch_no': batch.batch_no,
                          'reason': f'重新纳入：{reason}'})
            continue

        changes = _apply_item_state(item, batch, path, reason)
        if changes:
            item.save()
            changed.append({'batch_id': batch_id, 'batch_no': batch.batch_no,
                            'changes': changes})

    # 移除
    for batch_id, item in existing.items():
        if batch_id in scope_map or not item.is_active:
            continue
        item.is_active = False
        item.is_frozen = False
        item.removed_at = timezone.now()
        if batch_id in descendant_ids:
            reason = '该批次已流转为历史节点（拆分/转移/领用），现存实物由谱系下游节点承接'
        else:
            reason = f'复算时该批次已不在通报批次 {case.notified_batch_no} 的谱系内'
        item.remove_reason = reason
        item.save()
        removed.append({'batch_id': batch_id, 'batch_no': item.batch.batch_no,
                        'reason': reason})

    return _snapshot_version(case, user, change_reason or '按当前批次谱系复算',
                             added, removed, changed)


def _snapshot_version(case, user, change_reason, added, removed, changed):
    active_items = list(
        case.items.filter(is_active=True).select_related('batch')
    )
    snapshot = [_snapshot_entry(item) for item in
                sorted(active_items, key=lambda i: i.batch_id)]
    frozen_count = sum(1 for i in active_items if i.is_frozen)
    out_count = sum(1 for i in active_items if i.impact_status == RecallItem.STATUS_OUT)

    version_no = (case.versions.count() or 0) + 1
    version = RecallVersion.objects.create(
        case=case,
        version_no=version_no,
        snapshot=snapshot,
        added=added,
        removed=removed,
        changed=changed,
        change_reason=change_reason,
        frozen_count=frozen_count,
        out_count=out_count,
        created_by=user,
    )
    return version


# ==================== 案件生命周期 ====================

@transaction.atomic
def create_recall_case(*, title, case_no, notified_batch_no, goods, user,
                       supplier='', basis='', defect_desc=''):
    """建立召回案件并立即依据批次谱系生成首版影响清单与冻结。"""
    if not lineage_seed_batches(notified_batch_no, goods):
        raise RecallError(
            f'未找到通报批次 {notified_batch_no} 对应的批次记录，无法立案'
        )
    case = RecallCase.objects.create(
        title=title,
        case_no=case_no,
        notified_batch_no=notified_batch_no,
        goods=goods,
        supplier=supplier,
        basis=basis,
        defect_desc=defect_desc,
        created_by=user,
    )
    version = recompute_case(case, user, change_reason='立案，依据通报批次谱系首次计算影响范围')
    return case, version


@transaction.atomic
def close_case(case, user, remark=''):
    """关闭案件：仅解除本案件施加的冻结。

    各批次的冻结状态由"未关闭案件 × 有效影响项"派生，因此仍被其他
    未关闭案件召回的对象会继续保持冻结，不受本案件关闭影响。
    """
    if case.status == RecallCase.STATUS_CLOSED:
        raise RecallError('案件已关闭，无需重复操作')
    case.status = RecallCase.STATUS_CLOSED
    case.closed_by = user
    case.closed_at = timezone.now()
    case.close_remark = remark
    case.save()

    lifted = []
    for item in case.items.filter(is_active=True, is_frozen=True):
        item.is_frozen = False
        item.save()
        lifted.append({'batch_id': item.batch_id, 'batch_no': item.batch.batch_no})

    version = _snapshot_version(
        case, user,
        f'案件关闭，解除本案件冻结 {len(lifted)} 项；其他案件限制不受影响。{remark}'.strip(),
        added=[], removed=[],
        changed=[{'batch_id': x['batch_id'], 'batch_no': x['batch_no'],
                  'changes': [{'field': 'is_frozen', 'to': False,
                               'reason': '本案件关闭'}]} for x in lifted],
    )
    return case, version


# ==================== 批次流转（受冻结约束） ====================

def assert_not_frozen(batch):
    """在库批次若被任一未关闭案件冻结，则禁止拆分/转移/领用。"""
    if batch.is_in_stock and batch.is_frozen:
        cases = '、'.join(c.case_no for c in batch.active_freeze_cases)
        raise FrozenBatchError(
            f'批次 {batch.batch_no} 已被召回案件（{cases}）冻结，禁止流转'
        )


@transaction.atomic
def split_batch(*, parent, child_batch_no, quantity, location, user, remark=''):
    """从在库批次拆分出子批次。父批次仍现存，库存数量相应核减。"""
    assert_not_frozen(parent)
    if quantity <= 0:
        raise RecallError('拆分数量必须大于 0')
    if parent.quantity < quantity:
        raise RecallError('拆分数量不能大于批次现存数量')
    child = Batch.objects.create(
        batch_no=child_batch_no,
        goods=parent.goods,
        parent=parent,
        relation=Batch.RELATION_SPLIT,
        supplier=parent.supplier,
        quantity=quantity,
        location=location or parent.location,
        location_status=Batch.LOCATION_IN_STOCK,
        created_by=user,
    )
    parent.quantity = (parent.quantity or Decimal('0')) - quantity
    parent.save(update_fields=['quantity', 'updated_at'])
    BatchMovement.objects.create(
        batch=child, movement_type=Batch.RELATION_SPLIT,
        from_location=parent.location, to_location=child.location,
        quantity=quantity, remark=remark, operator=user,
    )
    return child


@transaction.atomic
def transfer_batch(*, batch, to_location, user, remark=''):
    """在库批次转移库位：生成现存的转移子节点，原节点转为历史节点。"""
    assert_not_frozen(batch)
    if not to_location:
        raise RecallError('目标位置不能为空')
    moved = Batch.objects.create(
        batch_no=batch.batch_no,
        goods=batch.goods,
        parent=batch,
        relation=Batch.RELATION_TRANSFER,
        supplier=batch.supplier,
        quantity=batch.quantity,
        location=to_location,
        location_status=Batch.LOCATION_IN_STOCK,
        created_by=user,
    )
    batch.is_current = False
    batch.save(update_fields=['is_current', 'updated_at'])
    BatchMovement.objects.create(
        batch=moved, movement_type=Batch.RELATION_TRANSFER,
        from_location=batch.location, to_location=to_location,
        quantity=batch.quantity, remark=remark, operator=user,
    )
    return moved


@transaction.atomic
def collect_batch(*, batch, holder_name, holder_dept, holder_contact,
                  last_known_status, user, out_record=None, remark=''):
    """领用出库：生成现存的离库叶子节点，原在库节点转为历史节点。"""
    assert_not_frozen(batch)
    if not holder_name:
        raise RecallError('领用人（离库责任人）不能为空')
    out = Batch.objects.create(
        batch_no=batch.batch_no,
        goods=batch.goods,
        parent=batch,
        relation=Batch.RELATION_COLLECT,
        supplier=batch.supplier,
        quantity=batch.quantity,
        location='',
        location_status=Batch.LOCATION_OUT,
        holder_name=holder_name,
        holder_dept=holder_dept,
        holder_contact=holder_contact,
        last_known_status=last_known_status or '已领用离库',
        out_record=out_record,
        created_by=user,
    )
    batch.is_current = False
    batch.save(update_fields=['is_current', 'updated_at'])
    BatchMovement.objects.create(
        batch=out, movement_type=Batch.RELATION_COLLECT,
        from_location=batch.location, to_location='',
        holder_name=holder_name, holder_dept=holder_dept,
        quantity=batch.quantity, remark=remark, operator=user,
    )
    return out
