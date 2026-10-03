"""批次谱系与召回案件测试。"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from .models import (
    Batch, Category, Goods, RecallCase, RecallItem, Unit, Variety,
)
from . import recall_service


class RecallFixture(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("recall-user", "testpass123", role="admin")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")
        unit = Unit.objects.create(name="件", created_by=self.user)
        category = Category.objects.create(name="加密介质", unit=unit, created_by=self.user)
        variety = Variety.objects.create(name="加密U盘", category=category, created_by=self.user)
        self.goods = Goods.objects.create(
            variety=variety, name="警用加密U盘", code="USB-001",
            quantity=Decimal("10"),
        )
        # 通报批次根节点（入库 10 件，库房A）
        self.root = Batch.objects.create(
            batch_no="B2026-01", goods=self.goods, relation=Batch.RELATION_ROOT,
            supplier="安恒厂商", quantity=Decimal("10"), location="库房A",
            created_by=self.user,
        )

    def _build_lineage(self):
        """构造 拆分→转移、拆分→领用 的混合去向：

        - root 拆分 S1(4)，S1 转移至库房B（现存 T1）
        - root 拆分 S2(3)，S2 领用给张三（现存离库节点 OUT2）
        - root 余 3 件仍在库房A
        现存去向：root(在库3)、T1(在库4)、OUT2(离库3)
        """
        s1 = recall_service.split_batch(
            parent=self.root, child_batch_no="B2026-01-S1",
            quantity=Decimal("4"), location="库房A柜1", user=self.user)
        t1 = recall_service.transfer_batch(
            batch=s1, to_location="库房B", user=self.user)
        s2 = recall_service.split_batch(
            parent=self.root, child_batch_no="B2026-01-S2",
            quantity=Decimal("3"), location="库房A柜2", user=self.user)
        out2 = recall_service.collect_batch(
            batch=s2, holder_name="张三", holder_dept="网安大队",
            holder_contact="13800000000", last_known_status="已配发使用",
            user=self.user)
        return s1, t1, s2, out2


class LineageScopeTest(RecallFixture):
    def test_scope_covers_split_transfer_collect(self):
        s1, t1, s2, out2 = self._build_lineage()
        scope = recall_service.compute_scope("B2026-01", self.goods)
        current_ids = {b.id for b, _, _ in scope}
        # 现存去向：根、转移节点、离库节点；历史节点 S1/S2 不计入
        self.assertEqual(current_ids, {self.root.id, t1.id, out2.id})
        self.assertNotIn(s1.id, current_ids)
        self.assertNotIn(s2.id, current_ids)
        # 谱系路径保留完整去向链
        out_entry = next((b, p, r) for b, p, r in scope if b.id == out2.id)
        batch, path, reason = out_entry
        self.assertEqual([n["batch_id"] for n in path],
                         [self.root.id, s2.id, out2.id])
        self.assertIn("拆分", reason)
        self.assertIn("领用", reason)


class CreateRecallTest(RecallFixture):
    def test_create_case_freezes_in_stock_and_snapshots_holder(self):
        _, t1, _, out2 = self._build_lineage()
        case, version = recall_service.create_recall_case(
            title="缺陷U盘召回", case_no="RC-2026-001",
            notified_batch_no="B2026-01", goods=self.goods, user=self.user,
            supplier="安恒厂商", basis="厂商通报函[2026]7号")

        items = {it.batch_id: it for it in case.items.filter(is_active=True)}
        self.assertEqual(len(items), 3)

        # 尚在库的 root / t1 被冻结
        self.root.refresh_from_db()
        t1.refresh_from_db()
        self.assertTrue(items[self.root.id].is_frozen)
        self.assertTrue(items[t1.id].is_frozen)
        self.assertTrue(self.root.is_frozen)
        self.assertTrue(t1.is_frozen)
        self.assertEqual(items[self.root.id].impact_status, RecallItem.STATUS_IN_STOCK)

        # 已离库对象：不冻结，但保留责任人与最后已知状态
        out_item = items[out2.id]
        self.assertFalse(out_item.is_frozen)
        self.assertEqual(out_item.impact_status, RecallItem.STATUS_OUT)
        self.assertEqual(out_item.holder_name, "张三")
        self.assertEqual(out_item.holder_dept, "网安大队")
        self.assertEqual(out_item.holder_contact, "13800000000")
        self.assertEqual(out_item.last_known_status, "已配发使用")

        # 首版清单快照
        self.assertEqual(version.version_no, 1)
        self.assertEqual(version.frozen_count, 2)
        self.assertEqual(version.out_count, 1)
        self.assertEqual(len(version.added), 3)

    def test_create_case_requires_known_batch(self):
        with self.assertRaises(recall_service.RecallError):
            recall_service.create_recall_case(
                title="x", case_no="RC-X", notified_batch_no="NOPE",
                goods=self.goods, user=self.user)

    def test_frozen_batch_blocks_movement(self):
        self._build_lineage()
        recall_service.create_recall_case(
            title="冻结", case_no="RC-F", notified_batch_no="B2026-01",
            goods=self.goods, user=self.user)
        self.root.refresh_from_db()
        with self.assertRaises(recall_service.FrozenBatchError):
            recall_service.split_batch(
                parent=self.root, child_batch_no="X",
                quantity=Decimal("1"), location="库房A", user=self.user)
        # 离库节点本身不在库，不触发在库流转
        with self.assertRaises(recall_service.FrozenBatchError):
            recall_service.transfer_batch(
                batch=self.root, to_location="库房C", user=self.user)


class MultiRecallIsolationTest(RecallFixture):
    def test_same_object_recalled_twice_keeps_separate_basis(self):
        recall_service.create_recall_case(
            title="第一次召回", case_no="RC-A",
            notified_batch_no="B2026-01", goods=self.goods, user=self.user,
            basis="通报函A")
        recall_service.create_recall_case(
            title="第二次召回", case_no="RC-B",
            notified_batch_no="B2026-01", goods=self.goods, user=self.user,
            basis="通报函B")

        # 同一批次在两宗案件下各有一条独立依据
        item_qs = RecallItem.objects.filter(
            batch=self.root, is_active=True).select_related("case")
        self.assertEqual(item_qs.count(), 2)
        bases = {i.case.basis for i in item_qs}
        self.assertEqual(bases, {"通报函A", "通报函B"})
        self.assertTrue(all(i.is_frozen for i in item_qs))
        self.root.refresh_from_db()
        self.assertEqual(set(self.root.active_freeze_cases.values_list("case_no", flat=True)),
                         {"RC-A", "RC-B"})

        # 关闭 A：仅解除 A 的冻结，B 的限制仍在
        case_a = RecallCase.objects.get(case_no="RC-A")
        recall_service.close_case(case_a, self.user, remark="已处置完毕")
        item_a = RecallItem.objects.get(case=case_a, batch=self.root)
        item_b = RecallItem.objects.get(case__case_no="RC-B", batch=self.root)
        self.assertFalse(item_a.is_frozen)
        self.assertTrue(item_b.is_frozen)
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_frozen)  # 仍被 B 冻结
        self.assertEqual(set(self.root.active_freeze_cases.values_list("case_no", flat=True)),
                         {"RC-B"})
        case_a.refresh_from_db()
        self.assertEqual(case_a.status, RecallCase.STATUS_CLOSED)

        # 关闭 B 后才真正解冻
        case_b = RecallCase.objects.get(case_no="RC-B")
        recall_service.close_case(case_b, self.user)
        self.root.refresh_from_db()
        self.assertFalse(self.root.is_frozen)

    def test_close_then_new_recall_refreezes(self):
        case, _ = recall_service.create_recall_case(
            title="召回", case_no="RC-C", notified_batch_no="B2026-01",
            goods=self.goods, user=self.user)
        self.assertTrue(self.root.is_frozen)
        recall_service.close_case(case, self.user)
        self.root.refresh_from_db()
        self.assertFalse(self.root.is_frozen)
        recall_service.create_recall_case(
            title="再次召回", case_no="RC-D", notified_batch_no="B2026-01",
            goods=self.goods, user=self.user, basis="新缺陷通报")
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_frozen)


class RecomputeTest(RecallFixture):
    def test_recompute_explains_added_and_removed(self):
        _, t1, _, out2 = self._build_lineage()
        case, v1 = recall_service.create_recall_case(
            title="召回", case_no="RC-R", notified_batch_no="B2026-01",
            goods=self.goods, user=self.user)
        self.assertEqual(len(v1.snapshot), 3)

        # 谱系更新（补录一次转移）：t1 转为历史节点，新增现存节点 t2
        t2 = Batch.objects.create(
            batch_no=t1.batch_no, goods=self.goods, parent=t1,
            relation=Batch.RELATION_TRANSFER, quantity=t1.quantity,
            location="库房C", created_by=self.user)
        t1.is_current = False
        t1.save(update_fields=["is_current"])

        v2 = recall_service.recompute_case(case, self.user, change_reason="补录库房C转移记录")
        added_nos = {a["batch_id"] for a in v2.added}
        removed_nos = {r["batch_id"] for r in v2.removed}
        self.assertEqual(added_nos, {t2.id})
        self.assertEqual(removed_nos, {t1.id})
        self.assertTrue(all("历史节点" in r["reason"] for r in v2.removed))
        self.assertTrue(all("转移" in a["reason"] or "重新纳入" in a["reason"]
                            for a in v2.added))
        # 清单仍可复算：现存数量不变（3），新在库节点被冻结
        self.assertEqual(len(v2.snapshot), 3)
        self.assertEqual(v2.frozen_count, 2)
        self.assertTrue(RecallItem.objects.get(case=case, batch=t2).is_frozen)
        # t1 的影响项保留但标记移出，移出原因可查
        old = RecallItem.objects.get(case=case, batch=t1)
        self.assertFalse(old.is_active)
        self.assertTrue(old.remove_reason)
        self.assertIsNotNone(old.removed_at)

    def test_recompute_records_changed_holder(self):
        _, _, _, out2 = self._build_lineage()
        case, _ = recall_service.create_recall_case(
            title="召回", case_no="RC-H", notified_batch_no="B2026-01",
            goods=self.goods, user=self.user)
        out2.holder_name = "李四"
        out2.last_known_status = "转交技侦"
        out2.save(update_fields=["holder_name", "last_known_status"])

        version = recall_service.recompute_case(case, self.user, change_reason="更新离库责任人")
        flat = [c["field"] for entry in version.changed for c in entry["changes"]]
        self.assertIn("holder_name", flat)
        item = RecallItem.objects.get(case=case, batch=out2)
        self.assertEqual(item.holder_name, "李四")
        self.assertEqual(item.last_known_status, "转交技侦")
        # 上一版本仍保留旧快照
        v1 = case.versions.get(version_no=1)
        old_holder = next(s for s in v1.snapshot if s["batch_id"] == out2.id)
        self.assertEqual(old_holder["holder_name"], "张三")


class RecallAPITest(RecallFixture):
    def test_full_api_flow(self):
        self._build_lineage()
        # 立案
        resp = self.client.post("/api/recalls/", {
            "title": "API召回", "case_no": "RC-API-1",
            "notified_batch_no": "B2026-01", "goods": self.goods.id,
            "supplier": "安恒厂商", "basis": "通报函",
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        case_id = resp.json()["data"]["case"]["id"]
        self.assertEqual(resp.json()["data"]["version"]["frozen_count"], 2)

        # 影响清单：在库冻结
        frozen = self.client.get(f"/api/recalls/{case_id}/items/?impact_status=in_stock")
        self.assertEqual(frozen.json()["data"]["total"], 2)
        # 已离库责任人
        out = self.client.get(f"/api/recalls/{case_id}/items/?impact_status=out")
        row = out.json()["data"]["list"][0]
        self.assertEqual(row["holder_name"], "张三")
        self.assertEqual(row["last_known_status"], "已配发使用")

        # 冻结拦截拆分
        blocked = self.client.post(
            f"/api/batches/{self.root.id}/split/",
            {"child_batch_no": "X", "quantity": "1"}, format="json")
        self.assertEqual(blocked.status_code, 400)

        # 复算（无变化也产生版本）
        rc = self.client.post(f"/api/recalls/{case_id}/recompute/",
                              {"change_reason": "例行复算"}, format="json")
        self.assertEqual(rc.status_code, 200)
        self.assertEqual(rc.json()["data"]["version_no"], 2)

        # 关闭案件
        closed = self.client.post(f"/api/recalls/{case_id}/close/",
                                  {"remark": "完成"}, format="json")
        self.assertEqual(closed.status_code, 200)
        # 关闭后不能再复算
        again = self.client.post(f"/api/recalls/{case_id}/recompute/", {}, format="json")
        self.assertEqual(again.status_code, 400)
        # 版本历史可追溯：立案 v1、复算 v2、关闭 v3
        versions = self.client.get(f"/api/recalls/{case_id}/versions/")
        self.assertEqual(len(versions.json()["data"]), 3)

    def test_unknown_batch_rejected(self):
        resp = self.client.post("/api/recalls/", {
            "title": "x", "case_no": "RC-404",
            "notified_batch_no": "MISSING", "goods": self.goods.id,
        }, format="json")
        self.assertEqual(resp.status_code, 400)
