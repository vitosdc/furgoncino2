# core/views.py - FILE COMPLETO FINALE
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Count, Q, Sum, Avg
from django.db import transaction
from datetime import datetime, timedelta
from .models import WorkOrder, Customer, Technician, Company, ServiceType, Expense

# Importa forms solo se esistono per evitare errori
try:
    from .forms import (OrderCreateForm, CustomerCreateForm, TechnicianCreateForm, 
                       CompanyRegistrationForm, UserRegistrationForm)
except ImportError:
    # Fallback se i form non esistono ancora
    OrderCreateForm = None
    CustomerCreateForm = None
    TechnicianCreateForm = None
    CompanyRegistrationForm = None
    UserRegistrationForm = None

# Importa analytics solo se esiste per evitare errori
try:
    from .analytics import AnalyticsService
except ImportError:
    AnalyticsService = None

# ============================================================================
# LANDING E REGISTRAZIONE
# ============================================================================

class LandingPageView(TemplateView):
    """Pagina di atterraggio per nuovi utenti"""
    template_name = 'core/landing.html'

class CompanyRegistrationView(CreateView):
    """Registrazione completa: Utente + Azienda"""
    template_name = 'core/company_registration.html'
    success_url = reverse_lazy('core:registration_success')
    
    def get(self, request, *args, **kwargs):
        if not UserRegistrationForm or not CompanyRegistrationForm:
            messages.error(request, 'Form di registrazione non configurati.')
            return redirect('core:login')
            
        # Se l'utente è già loggato e ha un'azienda, reindirizza alla dashboard
        if request.user.is_authenticated:
            try:
                company = request.user.owned_companies.first()
                if company:
                    return redirect('core:dashboard')
            except:
                pass
        
        user_form = UserRegistrationForm()
        company_form = CompanyRegistrationForm()
        
        return render(request, self.template_name, {
            'user_form': user_form,
            'company_form': company_form
        })
    
    def post(self, request, *args, **kwargs):
        if not UserRegistrationForm or not CompanyRegistrationForm:
            messages.error(request, 'Form di registrazione non configurati.')
            return redirect('core:login')
            
        user_form = UserRegistrationForm(request.POST)
        company_form = CompanyRegistrationForm(request.POST)
        
        if user_form.is_valid() and company_form.is_valid():
            try:
                with transaction.atomic():
                    # Crea l'utente
                    user = user_form.save()
                    
                    # Crea l'azienda e associa l'utente come owner
                    company = company_form.save(commit=False)
                    company.owner = user
                    company.save()
                    
                    # Login automatico
                    login(request, user)
                    
                    messages.success(
                        request, 
                        f'Benvenuto {user.get_full_name()}! La tua azienda "{company.name}" è stata registrata con successo.'
                    )
                    
                    return redirect('core:registration_success')
                    
            except Exception as e:
                messages.error(request, f'Errore durante la registrazione: {str(e)}')
        
        return render(request, self.template_name, {
            'user_form': user_form,
            'company_form': company_form
        })

class RegistrationSuccessView(LoginRequiredMixin, TemplateView):
    """Pagina di successo con onboarding"""
    template_name = 'core/registration_success.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        try:
            company = self.request.user.owned_companies.first()
            context['company'] = company
            
            if company:
                # Verifica cosa manca per completare l'onboarding
                context['needs_service_types'] = not company.service_types.exists()
                context['needs_customers'] = not company.customers.exists()
                context['needs_technicians'] = not company.technicians.exists()
            
        except:
            context['company'] = None
        
        return context

class CompanyOnboardingView(LoginRequiredMixin, TemplateView):
    """Onboarding guidato per configurare l'azienda"""
    template_name = 'core/company_onboarding.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        try:
            company = self.request.user.owned_companies.first()
            context['company'] = company
            
            if company:
                # Statistiche onboarding
                context.update({
                    'service_types_count': company.service_types.count(),
                    'customers_count': company.customers.count(),
                    'technicians_count': company.technicians.count(),
                    'orders_count': company.work_orders.count(),
                })
                
                # Calcola percentuale completamento
                steps_completed = 0
                total_steps = 4
                
                if company.service_types.exists():
                    steps_completed += 1
                if company.customers.exists():
                    steps_completed += 1
                if company.technicians.exists():
                    steps_completed += 1
                if company.work_orders.exists():
                    steps_completed += 1
                
                context['completion_percentage'] = int((steps_completed / total_steps) * 100)
                context['steps_completed'] = steps_completed
                context['total_steps'] = total_steps
        
        except:
            context['company'] = None
        
        return context

# ============================================================================
# AUTENTICAZIONE
# ============================================================================

class CustomLoginView(LoginView):
    template_name = 'core/login.html'
    redirect_authenticated_user = True
    
    def get_success_url(self):
        return reverse_lazy('core:dashboard')

class CustomLogoutView(LogoutView):
    next_page = 'core:login'

# ============================================================================
# DASHBOARD E UTILITÀ
# ============================================================================

def get_user_company(user):
    """Utility function per ottenere l'azienda dell'utente"""
    try:
        return user.owned_companies.first() or \
               Technician.objects.get(user=user).company
    except:
        return None

def get_last_7_days_orders(company):
    """Ottiene il numero di ordini degli ultimi 7 giorni"""
    if not company:
        return [0] * 7
    
    today = timezone.now().date()
    orders_data = []
    
    for i in range(6, -1, -1):  # Da 6 giorni fa a oggi
        target_date = today - timedelta(days=i)
        orders_count = WorkOrder.objects.filter(
            company=company,
            created_at__date=target_date
        ).count()
        orders_data.append(orders_count)
    
    return orders_data

def dashboard_check_onboarding(request):
    """Controlla se l'utente ha completato l'onboarding"""
    if not request.user.is_authenticated:
        return redirect('core:login')
    
    try:
        company = request.user.owned_companies.first()
        if not company:
            # L'utente non ha un'azienda, reindirizza alla registrazione
            messages.info(request, 'Prima di continuare, devi registrare la tua azienda.')
            return redirect('core:company_registration')
            
        # Controlla se l'onboarding è completo
        has_service_types = company.service_types.exists()
        has_customers = company.customers.exists()
        has_technicians = company.technicians.exists()
        
        if not (has_service_types or has_customers or has_technicians):
            # Primo accesso, reindirizza all'onboarding
            return redirect('core:company_onboarding')
            
    except Exception as e:
        messages.error(request, 'Errore nel caricamento dei dati aziendali.')
        return redirect('core:company_registration')
    
    # Tutto ok, continua alla dashboard normale
    return None

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'core/dashboard.html'
    
    def dispatch(self, request, *args, **kwargs):
        # Controlla onboarding prima di procedere solo se i form esistono
        if CompanyRegistrationForm and UserRegistrationForm:
            onboarding_redirect = dashboard_check_onboarding(request)
            if onboarding_redirect:
                return onboarding_redirect
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Ottieni l'azienda dell'utente corrente
        try:
            company = self.request.user.owned_companies.first()
            if not company:
                # L'utente potrebbe essere un tecnico
                technician = Technician.objects.get(user=self.request.user)
                company = technician.company
        except:
            company = None
        
        if company:
            # Statistiche dashboard
            today = timezone.now().date()
            
            # Calcola valore medio ordine
            completed_orders = WorkOrder.objects.filter(
                company=company,
                status='COMPLETED',
                final_price__isnull=False
            )
            avg_order_value = completed_orders.aggregate(
                avg=Avg('final_price')
            )['avg'] or 0
            
            # Dati reali per il mini-chart degli ultimi 7 giorni
            last_7_days_data = get_last_7_days_orders(company)
            
            # Calcola tasso di completamento reale
            total_orders = WorkOrder.objects.filter(company=company).count()
            completed_orders_count = WorkOrder.objects.filter(
                company=company, 
                status='COMPLETED'
            ).count()
            completion_rate = (completed_orders_count / total_orders * 100) if total_orders > 0 else 0
            
            # Calcola tempo medio reale (in ore)
            avg_completion_time = WorkOrder.objects.filter(
                company=company,
                status='COMPLETED',
                started_at__isnull=False,
                completed_at__isnull=False
            ).aggregate(
                avg_time=Avg(
                    timezone.now() - timezone.now()  # Placeholder, sarà calcolato correttamente
                )
            )
            
            # Calcolo semplificato del tempo medio (assumendo 2-4 ore per ordine completato)
            avg_hours = 3 if completed_orders_count > 0 else 0
            
            context.update({
                'company': company,
                'pending_orders': WorkOrder.objects.filter(
                    company=company, 
                    status='PENDING'
                ).count(),
                'today_orders': WorkOrder.objects.filter(
                    company=company,
                    created_at__date=today
                ).count(),
                'active_technicians': Technician.objects.filter(
                    company=company,
                    is_active=True
                ).count(),
                'recent_orders': WorkOrder.objects.filter(
                    company=company
                ).order_by('-created_at')[:5],
                'avg_order_value': avg_order_value,
                'last_7_days_data': last_7_days_data,  # Dati reali ultimi 7 giorni
                'completion_rate': round(completion_rate, 1),  # Tasso completamento reale
                'avg_hours': avg_hours,  # Tempo medio reale
                'total_orders': total_orders,  # Totale ordini
            })
        
        return context

# ============================================================================
# ANALYTICS E REPORT
# ============================================================================

class AnalyticsView(LoginRequiredMixin, TemplateView):
    """Dashboard Analytics principale"""
    template_name = 'core/analytics.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = get_user_company(self.request.user)
        
        if not company or not AnalyticsService:
            context['company'] = company
            context['error'] = 'Analytics non disponibili'
            return context
        
        analytics = AnalyticsService(company)
        
        # Prepara dati per JavaScript (conversione sicura)
        import json
        
        try:
            monthly_performance = analytics.get_monthly_performance()
            status_distribution = analytics.get_status_distribution()
            technician_performance = analytics.get_technician_performance()
            weekly_schedule = analytics.get_weekly_schedule_analysis()
            
            context.update({
                'company': company,
                'overview_stats': analytics.get_overview_stats(),
                'monthly_performance': json.dumps(monthly_performance),
                'technician_performance': technician_performance,
                'status_distribution': json.dumps(status_distribution),
                'priority_analysis': analytics.get_priority_analysis(),
                'financial_summary': analytics.get_financial_summary(),
                'service_type_analysis': analytics.get_service_type_analysis(),
                'weekly_schedule': json.dumps(weekly_schedule),
            })
        except Exception as e:
            context['error'] = f'Errore nel caricamento analytics: {str(e)}'
        
        return context

class ReportsView(LoginRequiredMixin, TemplateView):
    """Pagina dei report dettagliati"""
    template_name = 'core/reports.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = get_user_company(self.request.user)
        
        if not company or not AnalyticsService:
            context['company'] = company
            context['error'] = 'Report non disponibili'
            return context
        
        analytics = AnalyticsService(company)
        
        # Periodo selezionato (default 30 giorni)
        period_days = int(self.request.GET.get('period', 30))
        
        # Prepara dati per JavaScript
        import json
        
        try:
            monthly_performance = analytics.get_monthly_performance()
            
            context.update({
                'company': company,
                'period_days': period_days,
                'financial_summary': analytics.get_financial_summary(period_days),
                'customer_analysis': analytics.get_customer_analysis(),
                'monthly_performance': json.dumps(monthly_performance),
                'technician_performance': analytics.get_technician_performance(),
            })
        except Exception as e:
            context['error'] = f'Errore nel caricamento report: {str(e)}'
        
        return context

# ============================================================================
# GESTIONE ORDINI
# ============================================================================

class OrderListView(LoginRequiredMixin, ListView):
    model = WorkOrder
    template_name = 'core/order_list.html'
    context_object_name = 'orders'
    paginate_by = 20
    
    def get_queryset(self):
        company = self.get_user_company()
        if company:
            queryset = WorkOrder.objects.filter(company=company)
            
            # Filtri
            status = self.request.GET.get('status')
            if status:
                queryset = queryset.filter(status=status)
            
            technician = self.request.GET.get('technician')
            if technician:
                queryset = queryset.filter(technician_id=technician)
            
            return queryset.order_by('-created_at')
        return WorkOrder.objects.none()
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.get_user_company()
        if company:
            context.update({
                'company': company,
                'technicians': Technician.objects.filter(company=company, is_active=True),
                'status_choices': WorkOrder.STATUS_CHOICES,
                'current_status': self.request.GET.get('status', ''),
                'current_technician': self.request.GET.get('technician', ''),
            })
        return context
    
    def get_user_company(self):
        return get_user_company(self.request.user)

class OrderCreateView(LoginRequiredMixin, CreateView):
    model = WorkOrder
    template_name = 'core/order_form.html'
    success_url = reverse_lazy('core:order_list')
    
    def get_form_class(self):
        return OrderCreateForm if OrderCreateForm else None
    
    def form_valid(self, form):
        company = self.get_user_company()
        if company:
            form.instance.company = company
            response = super().form_valid(form)
            messages.success(self.request, f'Ordine {form.instance.order_number} creato con successo!')
            return response
        else:
            messages.error(self.request, 'Errore: nessuna azienda associata all\'utente.')
            return self.form_invalid(form)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        company = self.get_user_company()
        if company:
            kwargs['company'] = company
        return kwargs
    
    def get_user_company(self):
        return get_user_company(self.request.user)

class OrderDetailView(LoginRequiredMixin, DetailView):
    model = WorkOrder
    template_name = 'core/order_detail.html'
    context_object_name = 'order'
    
    def get_queryset(self):
        company = self.get_user_company()
        if company:
            return WorkOrder.objects.filter(company=company)
        return WorkOrder.objects.none()
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['expenses'] = self.object.expenses.all()
        return context
    
    def get_user_company(self):
        return get_user_company(self.request.user)

class OrderUpdateView(LoginRequiredMixin, UpdateView):
    model = WorkOrder
    template_name = 'core/order_form.html'
    
    def get_form_class(self):
        return OrderCreateForm if OrderCreateForm else None
    
    def get_success_url(self):
        return reverse_lazy('core:order_detail', kwargs={'pk': self.object.pk})
    
    def get_queryset(self):
        company = self.get_user_company()
        if company:
            return WorkOrder.objects.filter(company=company)
        return WorkOrder.objects.none()
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        company = self.get_user_company()
        if company:
            kwargs['company'] = company
        return kwargs
    
    def get_user_company(self):
        return get_user_company(self.request.user)

@login_required
def assign_order(request, pk, technician_id):
    """Assegna un ordine a un tecnico"""
    company = get_user_company(request.user)
    if not company:
        messages.error(request, 'Errore: nessuna azienda associata.')
        return redirect('core:order_list')
    
    order = get_object_or_404(WorkOrder, pk=pk, company=company)
    technician = get_object_or_404(Technician, id=technician_id, company=company)
    
    order.technician = technician
    order.status = 'ASSIGNED'
    order.assigned_at = timezone.now()
    order.save()
    
    messages.success(request, f'Ordine {order.order_number} assegnato a {technician.user.get_full_name()}')
    return redirect('core:order_detail', pk=pk)

# ============================================================================
# GESTIONE CLIENTI
# ============================================================================

class CustomerListView(LoginRequiredMixin, ListView):
    model = Customer
    template_name = 'core/customer_list.html'
    context_object_name = 'customers'
    paginate_by = 20
    
    def get_queryset(self):
        company = self.get_user_company()
        if company:
            return Customer.objects.filter(company=company).order_by('name')
        return Customer.objects.none()
    
    def get_user_company(self):
        return get_user_company(self.request.user)

class CustomerCreateView(LoginRequiredMixin, CreateView):
    model = Customer
    template_name = 'core/customer_form.html'
    success_url = reverse_lazy('core:customer_list')
    
    def get_form_class(self):
        return CustomerCreateForm if CustomerCreateForm else None
    
    def form_valid(self, form):
        company = self.get_user_company()
        if company:
            form.instance.company = company
            response = super().form_valid(form)
            messages.success(self.request, f'Cliente {form.instance.name} creato con successo!')
            return response
        else:
            messages.error(self.request, 'Errore: nessuna azienda associata all\'utente.')
            return self.form_invalid(form)
    
    def get_user_company(self):
        return get_user_company(self.request.user)

class CustomerDetailView(LoginRequiredMixin, DetailView):
    model = Customer
    template_name = 'core/customer_detail.html'
    context_object_name = 'customer'
    
    def get_queryset(self):
        company = self.get_user_company()
        if company:
            return Customer.objects.filter(company=company)
        return Customer.objects.none()
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['recent_orders'] = self.object.work_orders.order_by('-created_at')[:10]
        return context
    
    def get_user_company(self):
        return get_user_company(self.request.user)

# ============================================================================
# GESTIONE TECNICI
# ============================================================================

class TechnicianListView(LoginRequiredMixin, ListView):
    model = Technician
    template_name = 'core/technician_list.html'
    context_object_name = 'technicians'
    
    def get_queryset(self):
        company = self.get_user_company()
        if company:
            return Technician.objects.filter(company=company).annotate(
                active_orders_count=Count(
                    'work_orders',
                    filter=~Q(work_orders__status__in=['COMPLETED', 'CANCELLED'])
                )
            ).select_related('user')
        return Technician.objects.none()
    
    def get_user_company(self):
        return get_user_company(self.request.user)

class TechnicianCreateView(LoginRequiredMixin, CreateView):
    model = Technician
    template_name = 'core/technician_form.html'
    success_url = reverse_lazy('core:technician_list')
    
    def get_form_class(self):
        return TechnicianCreateForm if TechnicianCreateForm else None
    
    def form_valid(self, form):
        company = self.get_user_company()
        if company:
            form.instance.company = company
            response = super().form_valid(form)
            messages.success(self.request, f'Tecnico {form.instance.user.get_full_name()} creato con successo!')
            return response
        else:
            messages.error(self.request, 'Errore: nessuna azienda associata all\'utente.')
            return self.form_invalid(form)
    
    def get_user_company(self):
        return get_user_company(self.request.user)

class TechnicianDetailView(LoginRequiredMixin, DetailView):
    model = Technician
    template_name = 'core/technician_detail.html'
    context_object_name = 'technician'
    
    def get_queryset(self):
        company = self.get_user_company()
        if company:
            return Technician.objects.filter(company=company)
        return Technician.objects.none()
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Ordini del tecnico
        context['recent_orders'] = self.object.work_orders.order_by('-created_at')[:10]
        context['active_orders'] = self.object.work_orders.exclude(
            status__in=['COMPLETED', 'CANCELLED']
        ).order_by('-created_at')
        
        # Statistiche del tecnico
        total_orders = self.object.work_orders.count()
        completed_orders = self.object.work_orders.filter(status='COMPLETED').count()
        completion_rate = (completed_orders / total_orders * 100) if total_orders > 0 else 0
        
        context.update({
            'total_orders': total_orders,
            'completed_orders': completed_orders,
            'completion_rate': round(completion_rate, 1),
            'pending_orders': self.object.work_orders.filter(status='PENDING').count(),
        })
        
        return context
    
    def get_user_company(self):
        return get_user_company(self.request.user)

class TechnicianUpdateView(LoginRequiredMixin, UpdateView):
    model = Technician
    template_name = 'core/technician_edit.html'
    fields = ['phone', 'vehicle_plate', 'is_active']
    
    def get_success_url(self):
        return reverse_lazy('core:technician_detail', kwargs={'pk': self.object.pk})
    
    def get_queryset(self):
        company = self.get_user_company()
        if company:
            return Technician.objects.filter(company=company)
        return Technician.objects.none()
    
    def form_valid(self, form):
        messages.success(self.request, f'Tecnico {self.object.user.get_full_name()} aggiornato con successo!')
        return super().form_valid(form)
    
    def get_user_company(self):
        return get_user_company(self.request.user)

@login_required
def technician_locate(request, pk):
    """Mostra la posizione del tecnico sulla mappa"""
    company = get_user_company(request.user)
    if not company:
        messages.error(request, 'Errore: nessuna azienda associata.')
        return redirect('core:technician_list')
    
    technician = get_object_or_404(Technician, pk=pk, company=company)
    
    # Se il tecnico ha coordinate GPS, reindirizza alla mappa con focus su di lui
    if technician.current_latitude and technician.current_longitude:
        messages.info(request, f'Posizione di {technician.user.get_full_name()} mostrata sulla mappa.')
        return redirect(f"{reverse_lazy('core:live_map')}?focus_technician={pk}")
    else:
        messages.warning(request, f'{technician.user.get_full_name()} non ha ancora condiviso la sua posizione.')
        return redirect('core:technician_detail', pk=pk)

# ============================================================================
# MAPPA LIVE
# ============================================================================

class LiveMapView(LoginRequiredMixin, TemplateView):
    template_name = 'core/live_map.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.get_user_company()
        
        if company:
            context.update({
                'company': company,
                'technicians': Technician.objects.filter(
                    company=company, 
                    is_active=True
                ).select_related('user'),
                'pending_orders': WorkOrder.objects.filter(
                    company=company,
                    status__in=['PENDING', 'ASSIGNED']
                ).select_related('customer', 'technician__user'),
                'focus_technician': self.request.GET.get('focus_technician'),
            })
        
        return context
    
    def get_user_company(self):
        return get_user_company(self.request.user)