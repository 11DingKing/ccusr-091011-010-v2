# 监管物资保管服务

该项目为监管仓、证物室和受控物资保管点提供服务端 API，覆盖人员授权、物资分类、批次登记、收发记录、审批、预警、审计日志、统计报表与**批次召回**。数据保存在 SQLite，所有测试和接口验收均可在单个 Linux 应用容器内离线完成。

## 运行环境

- Python 3.11
- Django REST Framework
- SQLite

## 安装与初始化

```bash
python -m pip install -r backend/requirements.txt
cd backend
python manage.py migrate --run-syncdb
```

## 测试

```bash
cd backend
pytest -q
```

## 编译检查

```bash
python -m compileall -q backend
```

## API 验收

```bash
cd backend
python manage.py migrate --run-syncdb
python manage.py shell -c "from rest_framework.test import APIClient; from apps.authentication.models import User; u=User.objects.create_user('smoke','safe-pass',role='admin'); c=APIClient(); r=c.post('/api/auth/login/',{'username':'smoke','password':'safe-pass'},format='json'); print(r.status_code, bool(r.json()['data']['token']))"
```

## 容器

```bash
docker build -t custody-service .
docker run --rm custody-service
```

## 批次召回

供应方通报某批次加密介质存在缺陷时，按批次号建立召回案件。系统以入库单
（批次号）为谱系根，按先进先出（FIFO）追踪该批次被拆分到的所有货物、在库
余量与已离库去向：

- **在库物资**：立案/复算时按案件独立冻结，`Goods.is_frozen`、
  `frozen_quantity`、`available_quantity` 反映汇总冻结；出库可用
  `apps.warehouse.recall.validate_issuance(goods, qty)` 校验。
- **已离库物资**：影响清单列出对应出库单、责任领用人/部门与最后已知状态。
- **多宗召回**：同一对象可被多个案件召回，依据（`RecallBasis`）、清单
  （`RecallItem`）、冻结（`RecallFreeze`）均按案件独立保留；关闭一宗案件
  只解除该案冻结，不影响其他案件。
- **可复算**：追加/移除依据或手动复算后，清单重新计算，每次新增、移除、
  数量变更都写入变更记录并说明原因（`RecallRevision`），同时留存完整快照
  （`RecallSnapshot`）供核对、重放。

接口（均需认证）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/api/recalls/` | 案件列表 / 立案（`title`、`batch_nos`，可带 `case_no`、`supplier`、`notice_no`） |
| GET | `/api/recalls/<id>/` | 案件详情（含各批次依据） |
| POST | `/api/recalls/<id>/close/` | 关闭案件，仅解除本案冻结 |
| POST | `/api/recalls/<id>/recompute/` | 手动复算影响清单 |
| GET/POST | `/api/recalls/<id>/bases/` | 依据列表 / 追加缺陷批次依据并复算 |
| DELETE | `/api/recalls/<id>/bases/<basis_id>/` | 移除依据并复算 |
| GET | `/api/recalls/<id>/items/` | 影响清单（`location_status=in_stock/out`，含责任人/最后状态） |
| GET | `/api/recalls/<id>/revisions/` | 新增/移除/变更原因记录 |
| GET | `/api/recalls/<id>/snapshots/` | 历次复算快照列表 |
| GET | `/api/recalls/<id>/snapshots/<sid>/` | 单次复算快照详情 |
| GET | `/api/recalls/freezes/` | 冻结记录查询（按案件/货物筛选） |

