# 监管物资保管服务

该项目为监管仓、证物室和受控物资保管点提供服务端 API，覆盖人员授权、物资分类、批次登记、收发记录、审批、预警、审计日志与统计报表。数据保存在 SQLite，所有测试和接口验收均可在单个 Linux 应用容器内离线完成。

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

## 批次谱系与缺陷召回

供应方通报某批次加密介质存在缺陷时，系统沿**批次谱系**（入库根批次经拆分/转移/领用形成的 parent 链）一次性计算全部去向，立案即冻结尚在库的物资，并列出已离库对象的责任人与最后已知状态。

批次流转（冻结状态下被拦截）：

| 接口 | 说明 |
| --- | --- |
| `POST /api/batches/` | 登记入库批次（谱系根节点，含批次号、供应方） |
| `GET /api/batches/?batch_no=&is_current=` | 按批次号/是否现存查询 |
| `GET /api/batches/{id}/lineage/` | 批次完整谱系（根→当前节点） |
| `POST /api/batches/{id}/split/` | 拆分（生成子批次） |
| `POST /api/batches/{id}/transfer/` | 转移库位（生成现存节点，原节点转历史） |
| `POST /api/batches/{id}/collect/` | 领用离库（登记责任人、部门、联系方式、最后已知状态） |

召回案件：

| 接口 | 说明 |
| --- | --- |
| `POST /api/recalls/` | 立案：按通报批次谱系计算影响范围并冻结在库物资，生成清单 v1 |
| `GET /api/recalls/?status=&notified_batch_no=` | 案件列表 |
| `GET /api/recalls/{id}/items/?impact_status=in_stock\|out` | 影响清单：`in_stock` 为在库冻结项，`out` 含离库责任人快照；`include_removed=true` 可查历史移出项 |
| `POST /api/recalls/{id}/recompute/` | 按当前谱系复算清单，新版本记录新增/移除/变更及原因 |
| `GET /api/recalls/{id}/versions/` | 历次清单版本快照（可复算、可追溯） |
| `POST /api/recalls/{id}/close/` | 关闭案件，**仅解除本案件冻结** |

隔离与复算规则：

- 同一对象被多宗案件召回时，每宗案件各持一条独立依据（`RecallItem`，唯一约束 `case+batch`）；
- 批次冻结状态派生自"未关闭案件 × 有效冻结项"，关闭一宗案件不会解除另一宗案件的限制；
- 复算差异分为新增（谱系新节点/重新纳入）、移除（流转为历史节点或脱离通报谱系，均写明原因）、变更（冻结/离库/责任人状态变化）；离库责任人信息在纳入时快照，后续变更也会被记录到新版本。

