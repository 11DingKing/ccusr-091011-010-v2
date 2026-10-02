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
    RecallCaseListView, RecallCaseDetailView, RecallCaseCloseView,
    RecallBasisListView, RecallBasisDetailView, RecallRecomputeView,
    RecallItemListView, RecallRevisionListView,
    RecallSnapshotListView, RecallSnapshotDetailView, RecallFreezeListView,
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

    # 召回案件管理
    path('recalls/', RecallCaseListView.as_view(), name='recall-list'),
    path('recalls/freezes/', RecallFreezeListView.as_view(), name='recall-freeze-list'),
    path('recalls/<int:pk>/', RecallCaseDetailView.as_view(), name='recall-detail'),
    path('recalls/<int:pk>/close/', RecallCaseCloseView.as_view(), name='recall-close'),
    path('recalls/<int:pk>/recompute/', RecallRecomputeView.as_view(), name='recall-recompute'),
    path('recalls/<int:pk>/bases/', RecallBasisListView.as_view(), name='recall-basis-list'),
    path('recalls/<int:pk>/bases/<int:basis_id>/',
         RecallBasisDetailView.as_view(), name='recall-basis-detail'),
    path('recalls/<int:pk>/items/', RecallItemListView.as_view(), name='recall-item-list'),
    path('recalls/<int:pk>/revisions/', RecallRevisionListView.as_view(), name='recall-revision-list'),
    path('recalls/<int:pk>/snapshots/', RecallSnapshotListView.as_view(), name='recall-snapshot-list'),
    path('recalls/<int:pk>/snapshots/<int:snapshot_id>/',
         RecallSnapshotDetailView.as_view(), name='recall-snapshot-detail'),
]
