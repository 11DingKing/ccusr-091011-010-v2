"""
召回案件测试

覆盖：批次谱系拆分追溯、在库冻结、离库责任人与最后状态、
同一对象多宗召回独立依据与独立冻结、关闭一案不影响另一案、
案件更新后影响清单复算及新增/移除原因。
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from apps.warehouse.models import (
    Goods, RecallCase, RecallRevision,
    StockIn, StockOut,
)
from apps.warehouse.recall import compute_impact, validate_issuance
from apps.warehouse.tests import WarehouseFixture


def make_stock_in(goods, user, qty, batch_no, supplier='供应方甲',
                  days_ago=None):
    """直接创建入库单并指定入库时间（绕过 auto_now_add）"""
    stock_in = StockIn(goods=goods, operator=user, quantity=Decimal(qty),
                       batch_no=batch_no, supplier=supplier)
    stock_in.save()
    if days_ago is not None:
        ts = timezone.now() - timedelta(days=days_ago)
        StockIn.objects.filter(pk=stock_in.pk).update(stock_in_time=ts)
        stock_in.refresh_from_db()
    return stock_in


def make_stock_out(goods, user, qty, receiver='张三', dept='一队',
                   status='completed', days_ago=None):
    stock_out = StockOut(
        goods=goods, operator=user, receiver=receiver, receiver_dept=dept,
        quantity=Decimal(qty), status=status,
        stock_out_time=timezone.now() - timedelta(days=days_ago or 0),
    )
    stock_out.save()
    if days_ago is not None:
        ts = timezone.now() - timedelta(days=days_ago)
        StockOut.objects.filter(pk=stock_out.pk).update(
            stock_out_time=ts, created_at=ts
        )
        stock_out.refresh_from_db()
    return stock_out


class RecallFixture(WarehouseFixture):
    def setUp(self):
        super().setUp()
        # 货物初始账面库存由入库单构成；先清零默认库存再按批次入库
        self.goods.quantity = Decimal('0')
        self.goods.save()
        # 批次 B2026-09 入库 10（较早），批次 B2026-10 入库 10（较新）
        self.in_old = make_stock_in(self.goods, self.user, '10', 'B2026-09', days_ago=20)
        self.in_new = make_stock_in(self.goods, self.user, '10', 'B2026-10', days_ago=10)
        self.goods.quantity = Decimal('20')
        self.goods.save()
        # 从批次 B2026-09 中 FIFO 领用 4
        self.out1 = make_stock_out(self.goods, self.user, '4',
                                   receiver='李四', dept='办案二队', days_ago=5)

    def create_case(self, batches, case_no=None, title='缺陷介质召回'):
        payload = {
            'title': title,
            'supplier': '供应方甲',
            'description': '加密芯片存在缺陷',
            'batch_nos': batches,
            'notice_no': 'TN-2026-001',
        }
        if case_no:
            payload['case_no'] = case_no
        resp = self.client.post('/api/recalls/', payload, format='json')
        return resp


class RecallLineageTest(RecallFixture):
    """批次谱系直接计算测试"""

    def test_trace_split_batch_to_in_stock_and_out(self):
        entries, unknown = compute_impact(['B2026-09'])
        self.assertEqual(unknown, [])
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry['goods'].id, self.goods.id)
        self.assertEqual(entry['inbound_qty'], Decimal('10'))
        # 10 入库 - 4 已出库 = 6 在库
        self.assertEqual(entry['in_stock_qty'], Decimal('6'))
        self.assertEqual(len(entry['outbounds']), 1)
        self.assertEqual(entry['outbounds'][0]['stock_out'].id, self.out1.id)
        self.assertEqual(entry['outbounds'][0]['quantity'], Decimal('4'))

    def test_new_batch_fully_in_stock(self):
        entries, _ = compute_impact(['B2026-10'])
        self.assertEqual(entries[0]['in_stock_qty'], Decimal('10'))
        self.assertEqual(entries[0]['outbounds'], [])

    def test_batch_split_across_goods(self):
        """同一批次拆分登记到多个货物时均应命中"""
        goods2 = Goods.objects.create(
            variety=self.variety, name='备用介质', code='DEV-002',
            quantity=Decimal('5'),
        )
        make_stock_in(goods2, self.user, '5', 'B2026-09')
        entries, _ = compute_impact(['B2026-09'])
        goods_ids = {e['goods'].id for e in entries}
        self.assertEqual(goods_ids, {self.goods.id, goods2.id})

    def test_unknown_batch_reported(self):
        entries, unknown = compute_impact(['B-NOT-EXIST'])
        self.assertEqual(entries, [])
        self.assertEqual(unknown, ['B-NOT-EXIST'])


class RecallCaseAPITest(RecallFixture):
    def test_create_case_freezes_in_stock_and_lists_outbound(self):
        resp = self.create_case(['B2026-09'], case_no='RC-T-001')
        self.assertEqual(resp.status_code, 200, resp.json())
        recompute = resp.json()['data']['recompute']
        self.assertEqual(recompute['in_stock_item_count'], 1)
        self.assertEqual(recompute['out_item_count'], 1)
        self.assertEqual(recompute['frozen_quantity_total'], '6')

        self.goods.refresh_from_db()
        self.assertTrue(self.goods.is_frozen)
        self.assertEqual(self.goods.frozen_quantity, Decimal('6'))
        self.assertEqual(self.goods.available_quantity, Decimal('14'))

        # 影响清单：在库冻结 + 离库责任人
        items_resp = self.client.get('/api/recalls/1/items/')
        items = items_resp.json()['data']['list']
        in_stock = next(i for i in items if i['location_status'] == 'in_stock')
        out_item = next(i for i in items if i['location_status'] == 'out')
        self.assertEqual(in_stock['frozen_qty'], '6.00')
        self.assertEqual(out_item['receiver'], '李四')
        self.assertEqual(out_item['receiver_dept'], '办案二队')
        self.assertIn('已完成', out_item['last_known_status'])
        self.assertEqual(out_item['stock_out_id'], self.out1.id)
        self.assertTrue(in_stock['is_active'])

    def test_case_requires_authentication(self):
        resp = APIClient().get('/api/recalls/')
        self.assertEqual(resp.status_code, 401)

    def test_create_case_requires_batch(self):
        resp = self.client.post('/api/recalls/', {
            'title': '无依据案件', 'batch_nos': [],
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_basis_is_preserved_per_case(self):
        self.create_case(['B2026-09'], case_no='RC-A')
        case = RecallCase.objects.get(case_no='RC-A')
        basis = case.bases.get()
        self.assertEqual(basis.batch_no, 'B2026-09')
        self.assertEqual(basis.source, 'supplier_notice')
        self.assertEqual(basis.notice_no, 'TN-2026-001')
        self.assertEqual(basis.created_by, self.user)


class MultipleRecallTest(RecallFixture):
    """同一对象被多次召回：依据分别保留、限制互不影响"""

    def test_two_cases_independent_basis_and_freeze(self):
        # 案件一召回旧批次（在库 6）
        self.create_case(['B2026-09'], case_no='RC-M-1', title='第一次召回')
        case1 = RecallCase.objects.get(case_no='RC-M-1')
        # 案件二召回新批次（在库 10）
        self.create_case(['B2026-10'], case_no='RC-M-2', title='第二次召回')
        case2 = RecallCase.objects.get(case_no='RC-M-2')

        # 依据分别保留
        self.assertEqual(case1.bases.count(), 1)
        self.assertEqual(case2.bases.count(), 1)
        self.assertEqual(case1.bases.get().batch_no, 'B2026-09')
        self.assertEqual(case2.bases.get().batch_no, 'B2026-10')

        # 冻结按案独立存在
        self.assertEqual(case1.freezes.get().quantity, Decimal('6'))
        self.assertEqual(case2.freezes.get().quantity, Decimal('10'))
        # 货物汇总冻结 16，可动用 4
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.frozen_quantity, Decimal('16'))
        self.assertEqual(self.goods.available_quantity, Decimal('4'))

        # 关闭案件一：仅解除案件一冻结，案件二仍冻结
        resp = self.client.post(f'/api/recalls/{case1.id}/close/')
        self.assertEqual(resp.status_code, 200)
        self.goods.refresh_from_db()
        case1.refresh_from_db()
        case2.refresh_from_db()
        self.assertEqual(case1.status, 'closed')
        self.assertEqual(case2.status, 'open')
        self.assertTrue(self.goods.is_frozen)
        self.assertEqual(self.goods.frozen_quantity, Decimal('10'))
        self.assertFalse(case1.freezes.get().is_active)
        self.assertTrue(case2.freezes.get().is_active)

        # 案件一依据与清单仍保留备查
        self.assertEqual(case1.bases.count(), 1)
        self.assertEqual(case1.items.filter(is_active=True).count(), 2)

    def test_same_batch_two_cases_close_one_keeps_other_freeze(self):
        """两个案件召回同一批次，关闭一个不得解除另一限制"""
        self.create_case(['B2026-09'], case_no='RC-DUP-1')
        self.create_case(['B2026-09'], case_no='RC-DUP-2')
        c1 = RecallCase.objects.get(case_no='RC-DUP-1')
        c2 = RecallCase.objects.get(case_no='RC-DUP-2')
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.frozen_quantity, Decimal('12'))  # 每案 6，不去重

        self.client.post(f'/api/recalls/{c1.id}/close/')
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.frozen_quantity, Decimal('6'))
        self.assertTrue(c2.freezes.get().is_active)

    def test_closed_case_cannot_add_basis_or_close_again(self):
        self.create_case(['B2026-09'], case_no='RC-CL-1')
        case = RecallCase.objects.get(case_no='RC-CL-1')
        self.client.post(f'/api/recalls/{case.id}/close/')
        again = self.client.post(f'/api/recalls/{case.id}/close/')
        self.assertEqual(again.status_code, 400)
        add = self.client.post(f'/api/recalls/{case.id}/bases/', {
            'batch_no': 'B-NEW',
        }, format='json')
        self.assertEqual(add.status_code, 400)


class RecallRecomputeTest(RecallFixture):
    """案件更新后复算：新增/移除原因可查"""

    def test_add_basis_expands_impact_with_reason(self):
        self.create_case(['B2026-09'], case_no='RC-R-1')
        case = RecallCase.objects.get(case_no='RC-R-1')
        # 追加批次 B2026-10（全在库 10）
        resp = self.client.post(f'/api/recalls/{case.id}/bases/', {
            'batch_no': 'B2026-10', 'notice_no': 'TN-2',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        summary = resp.json()['data']['recompute']
        self.assertEqual(summary['changes']['added'], 1)
        self.assertEqual(summary['frozen_quantity_total'], '16')

        added = case.revisions.filter(change_type='added')
        self.assertTrue(added.filter(batch_no='B2026-10').exists())
        rev = added.get(batch_no='B2026-10')
        self.assertIn('B2026-10', rev.reason)
        self.assertIn('新增', rev.reason)

    def test_remove_basis_removes_items_with_reason_and_unfreezes(self):
        self.create_case(['B2026-09'], case_no='RC-R-2')
        case = RecallCase.objects.get(case_no='RC-R-2')
        basis_id = case.bases.get(batch_no='B2026-09').id

        resp = self.client.delete(f'/api/recalls/{case.id}/bases/{basis_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['changes']['removed'], 2)

        self.goods.refresh_from_db()
        self.assertFalse(self.goods.is_frozen)
        removed = case.revisions.filter(change_type='removed')
        self.assertEqual(removed.count(), 2)
        for rev in removed:
            self.assertIn('依据已移除', rev.reason)
            self.assertIn('B2026-09', rev.reason)
        # 旧条目保留但标记失效
        self.assertEqual(case.items.filter(is_active=False).count(), 2)

    def test_manual_recompute_after_new_stockout_records_outbound_owner(self):
        self.create_case(['B2026-10'], case_no='RC-R-3')
        case = RecallCase.objects.get(case_no='RC-R-3')
        # 初始：新批次 10 全部在库并冻结
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.frozen_quantity, Decimal('10'))

        # 冻结校验：超出可动用数量的领用应被阻止
        allowed, _ = validate_issuance(self.goods, Decimal('10'))
        self.assertTrue(allowed)
        allowed, msg = validate_issuance(self.goods, Decimal('11'))
        self.assertFalse(allowed)
        self.assertIn('RC-R-3', msg)

        # 模拟业务放行后的领用：旧批次余量 6 + 新批次 3，共领用 9（FIFO）
        make_stock_out(self.goods, self.user, '9', receiver='王五',
                       dept='技侦队', days_ago=1)
        self.goods.quantity = Decimal('11')
        self.goods.save()
        resp = self.client.post(f'/api/recalls/{case.id}/recompute/',
                                {'note': '补充离库登记'}, format='json')
        self.assertEqual(resp.status_code, 200)
        summary = resp.json()['data']
        # 在库 10->7 更新；新增一条离库去向
        self.assertEqual(summary['in_stock_item_count'], 1)
        self.assertEqual(summary['out_item_count'], 1)
        self.assertEqual(summary['frozen_quantity_total'], '7')

        out_item = case.items.get(location_status='out')
        self.assertEqual(out_item.affected_qty, Decimal('3'))
        self.assertEqual(out_item.receiver, '王五')
        self.assertEqual(out_item.receiver_dept, '技侦队')
        self.assertIn('已完成', out_item.last_known_status)

        updated = case.revisions.filter(change_type='updated').latest('id')
        self.assertIn('10', updated.reason)
        self.assertIn('7', updated.reason)

    def test_snapshot_taken_and_replayable(self):
        resp = self.create_case(['B2026-09'], case_no='RC-R-4')
        case = RecallCase.objects.get(case_no='RC-R-4')
        snap_id = resp.json()['data']['recompute']['snapshot_id']
        snapshot = case.snapshots.get(pk=snap_id)
        self.assertEqual(snapshot.trigger, 'create')
        self.assertEqual(snapshot.batch_basis, ['B2026-09'])
        self.assertEqual(len(snapshot.items), 2)
        detail = self.client.get(
            f'/api/recalls/{case.id}/snapshots/{snap_id}/'
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['data']['summary']['changes']['added'], 2)

    def test_revision_list_filterable(self):
        self.create_case(['B2026-09'], case_no='RC-R-5')
        case = RecallCase.objects.get(case_no='RC-R-5')
        resp = self.client.get(f'/api/recalls/{case.id}/revisions/?change_type=added')
        self.assertEqual(resp.status_code, 200)
        for item in resp.json()['data']['list']:
            self.assertEqual(item['change_type'], 'added')

    def test_duplicate_basis_rejected(self):
        self.create_case(['B2026-09'], case_no='RC-R-6')
        case = RecallCase.objects.get(case_no='RC-R-6')
        resp = self.client.post(f'/api/recalls/{case.id}/bases/', {
            'batch_no': 'B2026-09',
        }, format='json')
        self.assertEqual(resp.status_code, 400)


class RecallFreezeGuardTest(RecallFixture):
    def test_frozen_quantity_blocks_excess_issuance(self):
        self.create_case(['B2026-09'], case_no='RC-G-1')
        self.goods.refresh_from_db()
        allowed, _ = validate_issuance(self.goods, Decimal('14'))
        self.assertTrue(allowed)
        allowed, msg = validate_issuance(self.goods, Decimal('15'))
        self.assertFalse(allowed)
        self.assertIn('冻结', msg)

    def test_pending_stockout_not_consumed(self):
        """待审批/已拒绝出库单不消耗批次，物资仍视为在库并冻结"""
        goods = Goods.objects.create(
            variety=self.variety, name='其他介质', code='DEV-003',
            quantity=Decimal('8'),
        )
        make_stock_in(goods, self.user, '8', 'B-PENDING')
        make_stock_out(goods, self.user, '8', receiver='赵六', status='pending')
        entries, _ = compute_impact(['B-PENDING'])
        self.assertEqual(entries[0]['in_stock_qty'], Decimal('8'))
        self.assertEqual(entries[0]['outbounds'], [])

    def test_recompute_revives_freeze_when_stockout_rejected(self):
        """出库单被拒（未离库）后复算：离库行移除，在库余量恢复冻结"""
        goods = Goods.objects.create(
            variety=self.variety, name='待拒介质', code='DEV-004',
            quantity=Decimal('6'),
        )
        make_stock_in(goods, self.user, '6', 'B-REV')
        out = make_stock_out(goods, self.user, '6', receiver='钱七',
                             status='completed')
        resp = self.client.post('/api/recalls/', {
            'title': '撤销出库复核', 'batch_nos': ['B-REV'],
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        case_id = resp.json()['data']['case']['id']

        # 出库单改判为拒绝且物资退回库存
        out.status = 'rejected'
        out.save(update_fields=['status'])
        goods.quantity = Decimal('6')
        goods.save()
        recompute = self.client.post(f'/api/recalls/{case_id}/recompute/',
                                     {}, format='json')
        self.assertEqual(recompute.status_code, 200)
        data = recompute.json()['data']
        self.assertEqual(data['in_stock_item_count'], 1)
        self.assertEqual(data['out_item_count'], 0)
        self.assertEqual(data['frozen_quantity_total'], '6')

        removed = RecallRevision.objects.filter(
            case_id=case_id, change_type='removed'
        ).first()
        self.assertIsNotNone(removed)
        self.assertIn('未实际离库', removed.reason)
