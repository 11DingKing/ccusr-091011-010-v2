"""
召回案件批次谱系服务

批次谱系以入库单（StockIn，携带 batch_no）为根，物资在同一货物编码下
按"先进先出"（FIFO）被出库单（StockOut）消耗。供应方通报缺陷批次后，
本模块依据批次号正向追踪：

    入库批次 ──拆分──> 多个货物（入库单）
          │
          ├── 在库余量 ............ 召回时冻结
          └── FIFO 消耗 ─> 出库单 .. 已离库对象（责任人 / 最后已知状态）

复算结果与案件既有影响清单逐条比对，生成新增 / 移除 / 数量变更记录，
并说明原因；冻结按"案件 × 货物 × 批次"独立施加与解除。
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import (
    StockIn, StockOut, Goods,
    RecallItem, RecallFreeze, RecallRevision, RecallSnapshot,
)

# 视为"已实际离库"的出库单状态：待审批 / 已拒绝不消耗批次库存
EFFECTIVE_OUT_STATUSES = ('completed', 'approved')
ZERO = Decimal('0')


def _stock_out_status_label(status):
    return dict(StockOut.STATUS_CHOICES).get(status, status)


# ==================== 批次谱系追溯 ====================

def _trace_goods(goods):
    """对单个货物做 FIFO 谱系还原。

    返回 {inbound_id: {'inbound': StockIn, 'remaining': Decimal,
                        'consumptions': [(StockOut, Decimal), ...]}}
    """
    inbounds = list(
        StockIn.objects.filter(goods=goods).order_by('stock_in_time', 'id')
    )
    outs = list(
        StockOut.objects.filter(goods=goods)
        .filter(status__in=EFFECTIVE_OUT_STATUSES)
        .annotate(effective_time=Coalesce('stock_out_time', 'created_at'))
        .order_by('effective_time', 'id')
    )

    buckets = []
    for inbound in inbounds:
        buckets.append({
            'inbound': inbound,
            'remaining': Decimal(inbound.quantity) or ZERO,
            'consumptions': [],
        })

    cursor = 0
    for out in outs:
        need = Decimal(out.quantity) or ZERO
        while need > ZERO and cursor < len(buckets):
            bucket = buckets[cursor]
            if bucket['remaining'] <= ZERO:
                cursor += 1
                continue
            take = min(bucket['remaining'], need)
            bucket['remaining'] -= take
            bucket['consumptions'].append((out, take))
            need -= take
            if bucket['remaining'] <= ZERO:
                cursor += 1
    return {b['inbound'].id: b for b in buckets}


def compute_impact(batch_nos):
    """根据批次号集合计算影响范围。

    返回 (entries, unknown_batches)：
    entries: [{
        'goods', 'batch_no', 'inbound_qty', 'in_stock_qty',
        'inbound_refs': [{'id', 'quantity', 'stock_in_time', 'supplier'}],
        'outbounds': [{'stock_out', 'quantity', 'trace'}],
    }, ...]
    """
    batch_nos = [b for b in dict.fromkeys(batch_nos) if b]
    if not batch_nos:
        return [], []

    inbound_qs = StockIn.objects.filter(batch_no__in=batch_nos).select_related('goods')
    goods_ids = sorted(set(inbound_qs.values_list('goods_id', flat=True)))

    # 批次 -> 命中的入库单（按货物分组）
    hit_batches = set(inbound_qs.values_list('batch_no', flat=True))
    unknown_batches = [b for b in batch_nos if b not in hit_batches]

    entries = []
    for goods_id in goods_ids:
        goods = Goods.objects.get(pk=goods_id)
        traced = _trace_goods(goods)
        all_buckets = sorted(traced.values(), key=lambda b: (b['inbound'].stock_in_time,
                                                             b['inbound'].id))

        # 账面各批次剩余 = 入库 - FIFO 已消耗；其合计可能与当前实物库存不一致。
        # 按 FIFO 语义，现存实物优先归属最新入库桶，从最新批次向前分配实物库存，
        # 得到每个入库桶"当前仍在库且可冻结"的数量。
        physical = max(Decimal(goods.quantity) or ZERO, ZERO)
        freezable_by_inbound = {}
        left = physical
        for bucket in reversed(all_buckets):
            if left <= ZERO:
                freezable_by_inbound[bucket['inbound'].id] = ZERO
            else:
                allocated = min(bucket['remaining'], left)
                freezable_by_inbound[bucket['inbound'].id] = allocated
                left -= allocated

        # 该货物下属于缺陷批次的入库桶
        target_bucket_ids = [
            inbound_id for inbound_id, bucket in traced.items()
            if bucket['inbound'].batch_no in batch_nos
        ]

        # 按批次聚合（同一批次可能多次入库）
        per_batch = {}
        for inbound_id in target_bucket_ids:
            bucket = traced[inbound_id]
            inbound = bucket['inbound']
            agg = per_batch.setdefault(inbound.batch_no, {
                'inbound_qty': ZERO,
                'in_stock_qty': ZERO,
                'inbound_refs': [],
                'outbounds': [],
            })
            qty = Decimal(inbound.quantity) or ZERO
            agg['inbound_qty'] += qty
            agg['in_stock_qty'] += freezable_by_inbound.get(inbound_id, ZERO)
            agg['inbound_refs'].append({
                'id': inbound.id,
                'quantity': qty,
                'stock_in_time': inbound.stock_in_time,
                'supplier': inbound.supplier,
            })
            for out, consumed in bucket['consumptions']:
                agg['outbounds'].append({
                    'stock_out': out,
                    'quantity': consumed,
                })

        for batch_no, agg in per_batch.items():
            entries.append({
                'goods': goods,
                'batch_no': batch_no,
                **agg,
            })

    return entries, unknown_batches


# ==================== 案件影响清单同步 ====================

def _in_stock_key(goods_id, batch_no):
    return (goods_id, batch_no, None)


def _out_key(goods_id, batch_no, stock_out_id):
    return (goods_id, batch_no, stock_out_id)


def _desired_rows(case, entries):
    """把追溯结果展开为清单行：在库行（冻结）+ 离库行（责任人）。"""
    rows = []
    for entry in entries:
        goods = entry['goods']
        batch_no = entry['batch_no']
        inbound_total = entry['inbound_qty']
        out_total = sum((o['quantity'] for o in entry['outbounds']), ZERO)

        if entry['in_stock_qty'] > ZERO:
            inbound_ids = '、'.join(f"#{r['id']}" for r in entry['inbound_refs'])
            rows.append({
                'key': _in_stock_key(goods.id, batch_no),
                'goods': goods,
                'batch_no': batch_no,
                'stock_out': None,
                'location_status': 'in_stock',
                'affected_qty': entry['in_stock_qty'],
                'frozen_qty': entry['in_stock_qty'],
                'receiver': '',
                'receiver_dept': '',
                'last_known_status': '在库（召回冻结）',
                'trace_detail': (
                    f"批次 {batch_no} 入库单 {inbound_ids} 共入库 {inbound_total}，"
                    f"FIFO 追溯已出库 {out_total}，当前在库余量 "
                    f"{entry['in_stock_qty']}，由案件 {case.case_no} 冻结"
                ),
            })

        for out_ref in entry['outbounds']:
            out = out_ref['stock_out']
            consumed = out_ref['quantity']
            out_time = timezone.localtime(out.stock_out_time).strftime('%Y-%m-%d %H:%M') \
                if out.stock_out_time else '时间未登记'
            rows.append({
                'key': _out_key(goods.id, batch_no, out.id),
                'goods': goods,
                'batch_no': batch_no,
                'stock_out': out,
                'location_status': 'out',
                'affected_qty': consumed,
                'frozen_qty': ZERO,
                'receiver': out.receiver or '',
                'receiver_dept': out.receiver_dept or '',
                'last_known_status': f"{_stock_out_status_label(out.status)}（{out_time}）",
                'trace_detail': (
                    f"批次 {batch_no} 经 FIFO 谱系追溯至出库单 #{out.id}，"
                    f"{out_time} 由 {out.receiver or '未登记领用人'}"
                    f"/{out.receiver_dept or '未登记部门'} 领用 {consumed}，"
                    f"当前状态：{_stock_out_status_label(out.status)}"
                ),
            })
    return rows


def _removed_reason(case, old_item):
    """清单行在复算后消失时，给出可核对的移除原因。"""
    batch_no = old_item.batch_no
    if not case.bases.filter(batch_no=batch_no).exists():
        return f"案件依据已移除批次 {batch_no}，复算后不再纳入影响清单"
    if not StockIn.objects.filter(
        goods_id=old_item.goods_id, batch_no=batch_no
    ).exists():
        return f"批次 {batch_no} 针对该货物的入库登记已不存在，谱系无法追溯"
    if old_item.location_status == 'out':
        linked = StockOut.objects.filter(pk=old_item.stock_out_id).first() \
            if old_item.stock_out_id else None
        if linked is None:
            return f"原离库去向对应的出库单已删除或作废，批次 {batch_no} 该去向消失"
        if linked.status not in EFFECTIVE_OUT_STATUSES:
            return (
                f"出库单 #{linked.id} 状态变更为"
                f"“{_stock_out_status_label(linked.status)}”，物资未实际离库，"
                f"转回批次 {batch_no} 在库追溯"
            )
    return f"按批次 {batch_no} 最新谱系复算，未再发现该去向（库存或出库数据已变化）"


def _added_reason(new_row, basis_map):
    basis = basis_map.get(new_row['batch_no'])
    basis_desc = f"依据「{basis.get_source_display()}：{basis.notice_no or basis.evidence or '供应方缺陷通报'}」" \
        if basis else "依据缺陷批次通报"
    if new_row['location_status'] == 'in_stock':
        return (
            f"{basis_desc}，批次 {new_row['batch_no']} 谱系追溯命中在库余量 "
            f"{new_row['affected_qty']}，新增并冻结"
        )
    return (
        f"{basis_desc}，批次 {new_row['batch_no']} 经谱系追溯至已离库出库单 "
        f"#{new_row['stock_out'].id}（责任人：{new_row['receiver'] or '未登记'}），新增离库去向"
    )


def _updated_reason(old_item, new_row):
    if new_row['location_status'] == 'in_stock':
        return (
            f"批次谱系复算：批次 {new_row['batch_no']} 在库余量 "
            f"{old_item.affected_qty} → {new_row['affected_qty']}，"
            f"冻结数量同步调整"
        )
    return (
        f"批次谱系复算：出库单 #{new_row['stock_out'].id} 消耗批次 "
        f"{new_row['batch_no']} 的数量 {old_item.affected_qty} → "
        f"{new_row['affected_qty']}；最后状态：{new_row['last_known_status']}"
    )


@transaction.atomic
def apply_case_impact(case, operator, reason_note='', trigger='recompute'):
    """按案件当前依据重新计算影响清单并同步冻结，返回变更摘要。

    - 新增 / 移除 / 数量变更分别写入 RecallRevision 并说明原因；
    - 冻结仅作用于本案件，其他案件的冻结不受影响；
    - 每次复算留存 RecallSnapshot 快照，历史影响范围可核对、重放；
    - 返回值可直接作为复算接口的响应数据。
    """
    batch_nos = list(case.bases.values_list('batch_no', flat=True))
    entries, unknown_batches = compute_impact(batch_nos)
    desired_rows = _desired_rows(case, entries)
    desired_map = {row['key']: row for row in desired_rows}
    basis_map = {b.batch_no: b for b in case.bases.all()}

    existing_map = {
        _in_stock_key(item.goods_id, item.batch_no)
        if item.location_status == 'in_stock'
        else _out_key(item.goods_id, item.batch_no, item.stock_out_id): item
        for item in case.items.all()
    }

    stats = {'added': 0, 'removed': 0, 'updated': 0}

    # 新增 / 变更影响清单条目
    for key, row in desired_map.items():
        old = existing_map.get(key)
        common = {
            'location_status': row['location_status'],
            'affected_qty': row['affected_qty'],
            'receiver': row['receiver'],
            'receiver_dept': row['receiver_dept'],
            'last_known_status': row['last_known_status'],
            'trace_detail': row['trace_detail'],
            'is_active': True,
        }
        suffix = f"（{reason_note}）" if reason_note else ''

        if old is None:
            RecallItem.objects.create(
                case=case, goods=row['goods'], batch_no=row['batch_no'],
                stock_out=row['stock_out'], frozen_qty=row['frozen_qty'],
                **common,
            )
            RecallRevision.objects.create(
                case=case, goods=row['goods'], batch_no=row['batch_no'],
                location_status=row['location_status'], change_type='added',
                qty_before=None, qty_after=row['affected_qty'],
                reason=_added_reason(row, basis_map) + suffix,
                created_by=operator,
            )
            stats['added'] += 1
            continue

        old_qty = old.affected_qty
        changed = (
            old_qty != row['affected_qty']
            or old.frozen_qty != row['frozen_qty']
            or old.last_known_status != row['last_known_status']
            or old.receiver != row['receiver']
            or old.receiver_dept != row['receiver_dept']
            or not old.is_active
        )
        reason_text = _updated_reason(old, row) + suffix if changed else ''
        old.frozen_qty = row['frozen_qty']
        for field, value in common.items():
            setattr(old, field, value)
        old.save()
        if changed:
            RecallRevision.objects.create(
                case=case, goods=row['goods'], batch_no=row['batch_no'],
                location_status=row['location_status'], change_type='updated',
                qty_before=old_qty, qty_after=row['affected_qty'],
                reason=reason_text,
                created_by=operator,
            )
            stats['updated'] += 1

    # 移除
    for key, old in existing_map.items():
        if key in desired_map:
            continue
        reason = _removed_reason(case, old)
        if reason_note:
            reason = f"{reason}（{reason_note}）"
        RecallRevision.objects.create(
            case=case, goods=old.goods, batch_no=old.batch_no,
            location_status=old.location_status, change_type='removed',
            qty_before=old.affected_qty, qty_after=None,
            reason=reason, created_by=operator,
        )
        old.is_active = False
        old.frozen_qty = ZERO
        old.save(update_fields=['is_active', 'frozen_qty', 'updated_at'])
        stats['removed'] += 1

    # 冻结统一对账：仅同步本案件的冻结，与其他案件互不影响
    active_freeze_keys = {
        (row['goods'].id, row['batch_no']): row['frozen_qty']
        for row in desired_rows
        if row['location_status'] == 'in_stock' and row['frozen_qty'] > ZERO
    }
    for freeze in case.freezes.all():
        wanted = active_freeze_keys.get((freeze.goods_id, freeze.batch_no))
        if wanted is None:
            if freeze.is_active:
                freeze.is_active = False
                freeze.quantity = ZERO
                freeze.save(update_fields=['is_active', 'quantity', 'updated_at'])
        else:
            if not freeze.is_active or freeze.quantity != wanted:
                freeze.is_active = True
                freeze.quantity = wanted
                freeze.save(update_fields=['is_active', 'quantity', 'updated_at'])
        active_freeze_keys.pop((freeze.goods_id, freeze.batch_no), None)

    for (goods_id, batch_no), qty in active_freeze_keys.items():
        RecallFreeze.objects.create(
            case=case, goods_id=goods_id, batch_no=batch_no,
            quantity=qty, is_active=True,
        )

    summary = {
        'batch_count': len(batch_nos),
        'unknown_batches': unknown_batches,
        'in_stock_item_count': sum(
            1 for r in desired_rows if r['location_status'] == 'in_stock'
        ),
        'out_item_count': sum(
            1 for r in desired_rows if r['location_status'] == 'out'
        ),
        'frozen_quantity_total': str(
            case.freezes.filter(is_active=True, case__status='open')
            .aggregate(t=Sum('quantity'))['t']
            or ZERO
        ),
        'changes': stats,
    }

    snapshot_items = [
        {
            'goods_id': r['goods'].id,
            'goods_code': r['goods'].code,
            'goods_name': r['goods'].name,
            'batch_no': r['batch_no'],
            'stock_out_id': r['stock_out'].id if r['stock_out'] else None,
            'location_status': r['location_status'],
            'affected_qty': str(r['affected_qty']),
            'frozen_qty': str(r['frozen_qty']),
            'receiver': r['receiver'],
            'receiver_dept': r['receiver_dept'],
            'last_known_status': r['last_known_status'],
            'trace_detail': r['trace_detail'],
        }
        for r in desired_rows
    ]
    RecallSnapshot.objects.create(
        case=case, trigger=trigger,
        batch_basis=batch_nos,
        items=snapshot_items,
        summary={
            **summary,
            'frozen_quantity_total': summary['frozen_quantity_total'],
            'note': reason_note,
        },
        created_by=operator,
    )
    summary['snapshot_id'] = case.snapshots.first().id
    return summary


@transaction.atomic
def close_case(case, operator):
    """关闭案件：只解除本案件施加的冻结，保留清单与依据备查。"""
    if not case.is_open:
        return False
    case.status = 'closed'
    case.closed_by = operator
    case.closed_at = timezone.now()
    case.save(update_fields=['status', 'closed_by', 'closed_at', 'updated_at'])
    case.freezes.filter(is_active=True).update(is_active=False, quantity=ZERO)
    return True


def validate_issuance(goods, quantity):
    """出库前校验：执行中案件冻结的库存不得领用。

    返回 (allowed: bool, message: str)。
    """
    quantity = Decimal(quantity)
    free_now = goods.recall_freezes.filter(
        is_active=True, case__status='open'
    ).select_related('case')
    frozen_total = sum((Decimal(f.quantity) for f in free_now), ZERO)
    if frozen_total <= ZERO:
        return True, ''
    available = (Decimal(goods.quantity) - frozen_total)
    if quantity > available:
        case_nos = '、'.join(sorted({f.case.case_no for f in free_now}))
        return False, (
            f"货物 {goods.code} 处于召回冻结中（案件 {case_nos}），"
            f"冻结 {frozen_total}，可动用 {max(available, ZERO)}，"
            f"本次申请 {quantity}"
        )
    return True, ''
