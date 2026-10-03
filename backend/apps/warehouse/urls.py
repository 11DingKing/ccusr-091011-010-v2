"""
仓库管理URL配置
"""
from django.urls import path
from .views import (
    UnitListView, UnitDetailView, UnitBatchDeleteView, UnitAllView,
    CategoryListView, CategoryDetailView, CategoryBatchDeleteView, CategoryAllView,
    VarietyListView, VarietyDetailView, VarietyBatchDeleteView,
    VarietyTemplateView, VarietyImportView,
    DashboardView, GoodsListView, StockInListView, StockOutListView,
    WarningListView, ApprovalListView
)
from .recall_views import (
    BatchListView, BatchDetailView, BatchLineageView, BatchMovementListView,
    BatchSplitView, BatchTransferView, BatchCollectView,
    RecallCaseListView, RecallCaseDetailView, RecallCaseItemsView,
    RecallCaseRecomputeView, RecallCaseCloseView, RecallCaseVersionsView,
)

urlpatterns = [
    # 仪表盘
    path('dashboard/', DashboardView.as_view(), name='dashboard'),

    # 单位管理
    path('units/', UnitListView.as_view(), name='unit-list'),
    path('units/all/', UnitAllView.as_view(), name='unit-all'),
    path('units/batch-delete/', UnitBatchDeleteView.as_view(), name='unit-batch-delete'),
    path('units/<int:pk>/', UnitDetailView.as_view(), name='unit-detail'),

    # 品类管理
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('categories/all/', CategoryAllView.as_view(), name='category-all'),
    path('categories/batch-delete/', CategoryBatchDeleteView.as_view(), name='category-batch-delete'),
    path('categories/<int:pk>/', CategoryDetailView.as_view(), name='category-detail'),

    # 品种管理
    path('varieties/', VarietyListView.as_view(), name='variety-list'),
    path('varieties/batch-delete/', VarietyBatchDeleteView.as_view(), name='variety-batch-delete'),
    path('varieties/template/', VarietyTemplateView.as_view(), name='variety-template'),
    path('varieties/import/', VarietyImportView.as_view(), name='variety-import'),
    path('varieties/<int:pk>/', VarietyDetailView.as_view(), name='variety-detail'),

    # 货物管理
    path('goods/', GoodsListView.as_view(), name='goods-list'),

    # 入库管理
    path('stock-in/', StockInListView.as_view(), name='stock-in-list'),

    # 出库管理
    path('stock-out/', StockOutListView.as_view(), name='stock-out-list'),

    # 预警管理
    path('warnings/', WarningListView.as_view(), name='warning-list'),

    # 审批管理
    path('approvals/', ApprovalListView.as_view(), name='approval-list'),

    # 批次谱系
    path('batches/', BatchListView.as_view(), name='batch-list'),
    path('batches/<int:pk>/', BatchDetailView.as_view(), name='batch-detail'),
    path('batches/<int:pk>/lineage/', BatchLineageView.as_view(), name='batch-lineage'),
    path('batches/<int:pk>/movements/', BatchMovementListView.as_view(), name='batch-movements'),
    path('batches/<int:pk>/split/', BatchSplitView.as_view(), name='batch-split'),
    path('batches/<int:pk>/transfer/', BatchTransferView.as_view(), name='batch-transfer'),
    path('batches/<int:pk>/collect/', BatchCollectView.as_view(), name='batch-collect'),

    # 召回案件
    path('recalls/', RecallCaseListView.as_view(), name='recall-list'),
    path('recalls/<int:pk>/', RecallCaseDetailView.as_view(), name='recall-detail'),
    path('recalls/<int:pk>/items/', RecallCaseItemsView.as_view(), name='recall-items'),
    path('recalls/<int:pk>/recompute/', RecallCaseRecomputeView.as_view(), name='recall-recompute'),
    path('recalls/<int:pk>/close/', RecallCaseCloseView.as_view(), name='recall-close'),
    path('recalls/<int:pk>/versions/', RecallCaseVersionsView.as_view(), name='recall-versions'),
]
