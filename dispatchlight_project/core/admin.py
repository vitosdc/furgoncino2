from django.contrib import admin
from .models import Company, Technician, Customer, ServiceType, WorkOrder, Expense

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'owner', 'phone', 'created_at']
    search_fields = ['name', 'owner__username']

@admin.register(Technician)
class TechnicianAdmin(admin.ModelAdmin):
    list_display = ['user', 'company', 'phone', 'vehicle_plate', 'is_active']
    list_filter = ['company', 'is_active']
    search_fields = ['user__first_name', 'user__last_name', 'phone']

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['name', 'company', 'phone', 'created_at']
    list_filter = ['company']
    search_fields = ['name', 'phone', 'email']

@admin.register(ServiceType)
class ServiceTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'company', 'estimated_duration_minutes', 'default_price']
    list_filter = ['company']

@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'title', 'customer', 'technician', 'status', 'priority', 'created_at']
    list_filter = ['status', 'priority', 'company', 'created_at']
    search_fields = ['order_number', 'title', 'customer__name']
    readonly_fields = ['order_number', 'created_at']

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ['work_order', 'technician', 'expense_type', 'amount', 'created_at']
    list_filter = ['expense_type', 'created_at']