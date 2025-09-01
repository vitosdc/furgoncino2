# core/views.py - FILE COMPLETAMENTE AGGIORNATO CON SISTEMA DI AUTORIZZAZIONI - CORRETTO MRO
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.models import User
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.forms import UserCreationForm
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Count, Q, Sum, Avg
from django.db import transaction
from datetime import datetime, timedelta
import json 
from .models import WorkOrder, Customer, Technician, Company, ServiceType, Expense
from .mixins import CompanyAccessMixin, OwnerRequiredMixin, TechnicianAccessMixin, SmartRedirectMixin

# Importa forms solo se esistono per evitare errori
try:
    from .forms import (OrderCreateForm, CustomerCreateForm, TechnicianCreateForm, 
                       CompanyRegistrationForm, UserRegistrationForm, UserProfileEditForm, 
                       CompanyEditForm, TechnicianEditForm)
except ImportError:
    # Fallback se i form non esistono ancora
    OrderCreateForm = None
    CustomerCreateForm = None
    TechnicianCreateForm = None
    CompanyRegistrationForm = None
    UserRegistrationForm = None
    UserProfileEditForm = None
    CompanyEditForm = None
    TechnicianEditForm = None

# Importa analytics solo se esiste per evitare errori
try:
    from .analytics import AnalyticsService
except ImportError:
    AnalyticsService = None

# ============================================================================
# LANDING E REGISTRAZIONE (Pubbliche)
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
            
        # Se l'utente è già loggato e ha un'azienda, reindirizza alla dashboard appropriata
        if request.user.is_authenticated:
            try:
                company = request.user.owned_companies.first()
                if company:
                    return redirect('core:dashboard')
                # Se è un tecnico
                technician = Technician.objects.get(user=request.user)
                return redirect('core:technician_dashboard')
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

class CompanyOnboardingView(OwnerRequiredMixin, TemplateView):
    """Onboarding guidato per configurare l'azienda - SOLO PROPRIETARI"""
    template_name = 'core/company_onboarding.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        try:
            company = self.get_user_company()
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
        # Reindirizzamento intelligente basato sul ruolo
        user = self.request.user
        
        # Se è proprietario di un'azienda
        if user.owned_companies.exists():
            return reverse_lazy('core:dashboard')
        
        # Se è un tecnico
        try:
            technician = Technician.objects.get(user=user)
            return reverse_lazy('core:technician_dashboard')
        except Technician.DoesNotExist:
            pass
        
        # Default fallback
        return reverse_lazy('core:dashboard')

class CustomLogoutView(LogoutView):
    next_page = 'core:login'

# ============================================================================
# DASHBOARD INTELLIGENTE
# ============================================================================

class DashboardView(LoginRequiredMixin, TemplateView):
    """Dashboard che reindirizza in base al ruolo"""
    
    def dispatch(self, request, *args, **kwargs):
        # Reindirizzamento automatico in base al ruolo
        user = request.user
        
        # Se è proprietario, mostra dashboard proprietario
        if user.owned_companies.exists():
            return self._owner_dashboard(request)
        
        # Se è tecnico, reindirizza al dashboard tecnico
        try:
            technician = Technician.objects.get(user=user)
            return redirect('core:technician_dashboard')
        except Technician.DoesNotExist:
            messages.error(request, 'Account non associato a nessuna azienda.')
            return redirect('core:login')
    
    def _owner_dashboard(self, request):
        """Dashboard per proprietari"""
        template_name = 'core/dashboard.html'
        
        # Controlla onboarding prima di procedere solo se i form esistono
        if CompanyRegistrationForm and UserRegistrationForm:
            onboarding_redirect = self._dashboard_check_onboarding(request)
            if onboarding_redirect:
                return onboarding_redirect
        
        # Ottieni l'azienda dell'utente corrente
        try:
            company = request.user.owned_companies.first()
        except:
            company = None
        
        context = {}
        
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
            last_7_days_data = self._get_last_7_days_orders(company)
            
            # Calcola tasso di completamento reale
            total_orders = WorkOrder.objects.filter(company=company).count()
            completed_orders_count = WorkOrder.objects.filter(
                company=company, 
                status='COMPLETED'
            ).count()
            completion_rate = (completed_orders_count / total_orders * 100) if total_orders > 0 else 0
            
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
                'last_7_days_data': last_7_days_data,
                'completion_rate': round(completion_rate, 1),
                'avg_hours': avg_hours,
                'total_orders': total_orders,
            })
        
        return render(request, template_name, context)
    
    def _dashboard_check_onboarding(self, request):
        """Controlla se l'utente ha completato l'onboarding"""
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
    
    def _get_last_7_days_orders(self, company):
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

# ============================================================================
# PROFILO UTENTE E AZIENDA - CON CONTROLLI DI AUTORIZZAZIONE
# ============================================================================

class UserProfileView(CompanyAccessMixin, TemplateView):
    """Visualizza il profilo dell'utente e dell'azienda"""
    template_name = 'core/user_profile.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Informazioni utente
        context['user'] = self.request.user
        
        # Informazioni azienda
        company = self.get_user_company()
        context['company'] = company
        context['is_owner'] = self.is_company_owner()
        
        if company:
            # Statistiche rapide (solo per proprietari)
            if self.is_company_owner():
                context.update({
                    'total_orders': WorkOrder.objects.filter(company=company).count(),
                    'total_customers': Customer.objects.filter(company=company).count(),
                    'total_technicians': Technician.objects.filter(company=company).count(),
                    'account_created': self.request.user.date_joined,
                })
        
        return context

class UserProfileEditView(LoginRequiredMixin, UpdateView):
    """Modifica il profilo utente"""
    template_name = 'core/user_profile_edit.html'
    success_url = reverse_lazy('core:user_profile')
    
    def get_object(self):
        return self.request.user
    
    def get_form_class(self):
        return UserProfileEditForm if UserProfileEditForm else None
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        response = super().form_valid(form)
        
        # Se ha cambiato la password, aggiorna la sessione
        if form.cleaned_data.get('new_password'):
            update_session_auth_hash(self.request, form.instance)
            messages.success(self.request, 'Profilo e password aggiornati con successo!')
        else:
            messages.success(self.request, 'Profilo aggiornato con successo!')
        
        return response

class CompanyEditView(OwnerRequiredMixin, UpdateView):
    """Modifica i dati dell'azienda - SOLO PROPRIETARI"""
    template_name = 'core/company_edit.html'
    success_url = reverse_lazy('core:user_profile')
    
    def get_form_class(self):
        return CompanyEditForm if CompanyEditForm else None
    
    def get_object(self):
        return self.get_user_company()
    
    def form_valid(self, form):
        messages.success(self.request, f'Dati azienda "{form.instance.name}" aggiornati con successo!')
        return super().form_valid(form)

class CompanySettingsView(OwnerRequiredMixin, TemplateView):
    """Pagina delle impostazioni generali dell'azienda - SOLO PROPRIETARI"""
    template_name = 'core/company_settings.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        company = self.get_user_company()
        context['company'] = company
        
        if company:
            # Statistiche per le impostazioni
            context.update({
                'service_types_count': company.service_types.count(),
                'customers_count': company.customers.count(), 
                'technicians_count': company.technicians.count(),
                'active_technicians_count': company.technicians.filter(is_active=True).count(),
                'completed_orders_count': company.work_orders.filter(status='COMPLETED').count(),
                'total_orders_count': company.work_orders.count(),
            })
        
        return context

# ============================================================================
# ANALYTICS E REPORT - SOLO PROPRIETARI
# ============================================================================

class AnalyticsView(OwnerRequiredMixin, TemplateView):
    """Dashboard Analytics principale - SOLO PROPRIETARI"""
    template_name = 'core/analytics.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.get_user_company()
        
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

class ReportsView(OwnerRequiredMixin, TemplateView):
    """Pagina dei report dettagliati - SOLO PROPRIETARI"""
    template_name = 'core/reports.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.get_user_company()
        
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
# GESTIONE ORDINI - CON AUTORIZZAZIONI
# ============================================================================

class OrderListView(CompanyAccessMixin, ListView):
    """Lista ordini con filtro basato sui permessi"""
    model = WorkOrder
    template_name = 'core/order_list.html'
    context_object_name = 'orders'
    paginate_by = 20
    
    def get_queryset(self):
        company = self.get_user_company()
        if not company:
            return WorkOrder.objects.none()
        
        # Proprietari vedono tutti gli ordini dell'azienda
        if self.is_company_owner():
            queryset = WorkOrder.objects.filter(company=company)
        else:
            # Tecnici vedono solo i propri ordini
            technician = self.get_user_technician()
            if technician:
                queryset = WorkOrder.objects.filter(technician=technician)
            else:
                return WorkOrder.objects.none()
        
        # Filtri
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        technician_filter = self.request.GET.get('technician')
        if technician_filter and self.is_company_owner():
            queryset = queryset.filter(technician_id=technician_filter)
        
        return queryset.order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.get_user_company()
        
        if company:
            context.update({
                'company': company,
                'is_owner': self.is_company_owner(),
                'status_choices': WorkOrder.STATUS_CHOICES,
                'current_status': self.request.GET.get('status', ''),
                'current_technician': self.request.GET.get('technician', ''),
            })
            
            # Solo i proprietari vedono la lista completa dei tecnici
            if self.is_company_owner():
                context['technicians'] = Technician.objects.filter(company=company, is_active=True)
        
        return context

class OrderCreateView(OwnerRequiredMixin, CreateView):
    """Creazione ordini - SOLO PROPRIETARI"""
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

class OrderDetailView(CompanyAccessMixin, DetailView):
    """Dettaglio ordine con controllo accesso"""
    model = WorkOrder
    template_name = 'core/order_detail.html'
    context_object_name = 'order'
    
    def get_queryset(self):
        company = self.get_user_company()
        if not company:
            return WorkOrder.objects.none()
        
        # Proprietari vedono tutti gli ordini dell'azienda
        if self.is_company_owner():
            return WorkOrder.objects.filter(company=company)
        else:
            # Tecnici vedono solo i propri ordini
            technician = self.get_user_technician()
            if technician:
                return WorkOrder.objects.filter(technician=technician)
            else:
                return WorkOrder.objects.none()
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['expenses'] = self.object.expenses.all()
        context['is_owner'] = self.is_company_owner()
        return context

class OrderUpdateView(OwnerRequiredMixin, UpdateView):
    """Modifica ordini - SOLO PROPRIETARI"""
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

@login_required
def assign_order(request, pk, technician_id):
    """Assegna un ordine a un tecnico - SOLO PROPRIETARI"""
    # Verifica che sia proprietario
    if not request.user.owned_companies.exists():
        messages.error(request, 'Solo il proprietario può assegnare ordini.')
        return redirect('core:order_list')
    
    company = request.user.owned_companies.first()
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
# GESTIONE CLIENTI - SOLO PROPRIETARI
# ============================================================================

class CustomerListView(OwnerRequiredMixin, ListView):
    """Lista clienti - SOLO PROPRIETARI"""
    model = Customer
    template_name = 'core/customer_list.html'
    context_object_name = 'customers'
    paginate_by = 20
    
    def get_queryset(self):
        company = self.get_user_company()
        if company:
            return Customer.objects.filter(company=company).order_by('name')
        return Customer.objects.none()

class CustomerCreateView(OwnerRequiredMixin, CreateView):
    """Creazione clienti - SOLO PROPRIETARI"""
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

class CustomerDetailView(OwnerRequiredMixin, DetailView):
    """Dettaglio cliente - SOLO PROPRIETARI"""
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

class CustomerUpdateView(OwnerRequiredMixin, UpdateView):
    """Modifica cliente - SOLO PROPRIETARI"""
    model = Customer
    template_name = 'core/customer_form.html'
    
    def get_form_class(self):
        return CustomerCreateForm if CustomerCreateForm else None
    
    def get_success_url(self):
        messages.success(self.request, f'Cliente {self.object.name} aggiornato con successo!')
        return reverse_lazy('core:customer_detail', kwargs={'pk': self.object.pk})
    
    def get_queryset(self):
        company = self.get_user_company()
        if company:
            return Customer.objects.filter(company=company)
        return Customer.objects.none()

# ============================================================================
# GESTIONE TECNICI - SOLO PROPRIETARI
# ============================================================================

class TechnicianListView(OwnerRequiredMixin, ListView):
    """Lista tecnici - SOLO PROPRIETARI"""
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

class TechnicianCreateView(OwnerRequiredMixin, CreateView):
    """Creazione tecnico - SOLO PROPRIETARI"""
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

class TechnicianDetailView(OwnerRequiredMixin, DetailView):
    """Dettaglio tecnico - SOLO PROPRIETARI"""
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

class TechnicianUpdateView(OwnerRequiredMixin, UpdateView):
    """Modifica tecnico completa - SOLO PROPRIETARI"""
    model = Technician
    template_name = 'core/technician_edit.html'
    
    def get_form_class(self):
        return TechnicianEditForm if TechnicianEditForm else None
    
    def get_success_url(self):
        return reverse_lazy('core:technician_detail', kwargs={'pk': self.object.pk})
    
    def get_queryset(self):
        company = self.get_user_company()
        if company:
            return Technician.objects.filter(company=company)
        return Technician.objects.none()
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Passa l'istanza dell'utente associato al tecnico
        if self.object and self.object.user:
            kwargs['user_instance'] = self.object.user
        return kwargs
    
    def form_valid(self, form):
        try:
            with transaction.atomic():
                technician = form.save()
                
                # Messaggio di successo personalizzato
                success_msg = f'Tecnico {technician.user.get_full_name()} aggiornato con successo!'
                
                # Aggiungi dettagli su cosa è stato modificato
                changes = []
                if form.cleaned_data.get('change_password'):
                    changes.append('password modificata')
                
                latitude = form.cleaned_data.get('current_latitude')
                longitude = form.cleaned_data.get('current_longitude')
                if latitude is not None and longitude is not None:
                    changes.append(f'posizione GPS aggiornata ({latitude:.6f}, {longitude:.6f})')
                
                if changes:
                    success_msg += f' Modifiche: {", ".join(changes)}.'
                
                messages.success(self.request, success_msg)
                return super().form_valid(form)
                
        except Exception as e:
            messages.error(self.request, f'Errore durante la modifica del tecnico: {str(e)}')
            return self.form_invalid(form)

@login_required
def technician_locate(request, pk):
    """Localizza tecnico sulla mappa - SOLO PROPRIETARI"""
    # Verifica che sia proprietario
    if not request.user.owned_companies.exists():
        messages.error(request, 'Solo il proprietario può localizzare i tecnici.')
        return redirect('core:technician_list')
    
    company = request.user.owned_companies.first()
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
# MAPPA LIVE - SOLO PROPRIETARI
# ============================================================================

class LiveMapView(OwnerRequiredMixin, TemplateView):
    """Mappa live - SOLO PROPRIETARI"""
    template_name = 'core/live_map.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.get_user_company()
        
        if company:
            # Prepara dati tecnici per JavaScript
            technicians_data = []
            technicians = Technician.objects.filter(
                company=company, 
                is_active=True
            ).select_related('user').annotate(
                current_orders=Count('work_orders', filter=Q(work_orders__status__in=['ASSIGNED', 'EN_ROUTE', 'ON_SITE']))
            )
            
            for tech in technicians:
                # Coordinate simulate per demo (sostituire con dati GPS reali)
                lat, lng = self._get_demo_coordinates(tech.id)
                
                technicians_data.append({
                    'id': tech.id,
                    'name': tech.user.get_full_name(),
                    'phone': str(tech.phone),
                    'vehicle': tech.vehicle_plate,
                    'is_active': tech.is_active,
                    'current_orders': tech.current_orders,
                    'completed_today': self._get_completed_today_count(tech),
                    'lat': lat,
                    'lng': lng,
                    'last_update': tech.last_location_update.isoformat() if tech.last_location_update else None,
                    'status': tech.get_current_status() if hasattr(tech, 'get_current_status') else 'AVAILABLE'
                })
            
            # Prepara dati ordini per JavaScript
            orders_data = []
            orders = WorkOrder.objects.filter(
                company=company,
                status__in=['PENDING', 'ASSIGNED']
            ).select_related('customer', 'technician__user')
            
            for order in orders:
                # Coordinate simulate per demo (sostituire con geocoding dell'indirizzo)
                lat, lng = self._geocode_address(order.service_address)
                
                orders_data.append({
                    'id': str(order.id),
                    'order_number': order.order_number,
                    'title': order.title,
                    'description': order.description,
                    'customer_name': order.customer.name,
                    'customer_phone': str(order.customer.phone),
                    'priority': order.priority,
                    'priority_display': order.get_priority_display(),
                    'status': order.status,
                    'service_address': order.service_address,
                    'created_at': order.created_at.isoformat(),
                    'technician_id': order.technician.id if order.technician else None,
                    'technician_name': order.technician.user.get_full_name() if order.technician else None,
                    'lat': lat,
                    'lng': lng,
                    'estimated_price': float(order.estimated_price) if order.estimated_price else None
                })
            
            # Informazioni azienda
            company_data = {
                'name': company.name,
                'address': company.address,
                'phone': str(company.phone),
                'center_lat': 41.9028,  # Roma come default
                'center_lng': 12.4964
            }
            
            context.update({
                'company': company,
                'technicians': technicians,
                'orders': orders,
                'technicians_json': json.dumps(technicians_data),
                'orders_json': json.dumps(orders_data),
                'company_json': json.dumps(company_data),
                'focus_technician': self.request.GET.get('focus_technician'),
            })
        else:
            context.update({
                'technicians_json': '[]',
                'orders_json': '[]',
                'company_json': '{}',
            })
        
        return context
    
    def _get_demo_coordinates(self, tech_id):
        """
        Genera coordinate simulate per demo.
        In produzione, sostituire con tech.current_latitude, tech.current_longitude
        """
        # Coordinate simulate intorno a Roma
        base_lat = 41.9028
        base_lng = 12.4964
        
        # Offset basato sull'ID per posizioni diverse
        import random
        random.seed(tech_id)  # Seed fisso per coordinate consistenti
        
        lat_offset = random.uniform(-0.1, 0.1)  # ~11km range
        lng_offset = random.uniform(-0.1, 0.1)
        
        return base_lat + lat_offset, base_lng + lng_offset
    
    def _geocode_address(self, address):
        """
        Geocoding semplificato per demo.
        In produzione, usare Google Maps Geocoding API o simili
        """
        # Coordinate simulate intorno a Roma
        base_lat = 41.9028
        base_lng = 12.4964
        
        # Hash dell'indirizzo per coordinate consistenti
        import hashlib
        hash_obj = hashlib.md5(address.encode())
        hash_int = int(hash_obj.hexdigest()[:8], 16)
        
        # Offset basato sull'hash
        lat_offset = ((hash_int % 200) - 100) / 1000  # Range ±0.1
        lng_offset = (((hash_int // 200) % 200) - 100) / 1000
        
        return base_lat + lat_offset, base_lng + lng_offset
    
    def _get_completed_today_count(self, technician):
        """Conta ordini completati oggi dal tecnico"""
        from datetime import date
        return WorkOrder.objects.filter(
            technician=technician,
            status='COMPLETED',
            completed_at__date=date.today()
        ).count()