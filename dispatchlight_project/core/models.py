# core/models.py
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from phonenumber_field.modelfields import PhoneNumberField
import uuid

class Company(models.Model):
    """Azienda che usa il sistema"""
    name = models.CharField(max_length=200)
    address = models.TextField()
    phone = PhoneNumberField()
    email = models.EmailField()
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_companies')
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name_plural = "Companies"

class Technician(models.Model):
    """Tecnico/operatore mobile"""
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='technicians')
    phone = PhoneNumberField()
    vehicle_plate = models.CharField(max_length=20, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    
    # Posizione GPS corrente
    current_latitude = models.DecimalField(max_digits=10, decimal_places=8, blank=True, null=True)
    current_longitude = models.DecimalField(max_digits=11, decimal_places=8, blank=True, null=True)
    last_location_update = models.DateTimeField(blank=True, null=True)
    
    # Aggiungi questi metodi alla classe Technician esistente in core/models.py:

    def get_current_status(self):
        """Restituisce lo stato corrente del tecnico"""
        if not self.is_active:
            return 'OFFLINE'
        
        active_orders = self.work_orders.filter(
            status__in=['ASSIGNED', 'EN_ROUTE', 'ON_SITE']
        ).count()
        
        if active_orders > 0:
            # Controlla se è in viaggio o sul posto
            current_order = self.work_orders.filter(
                status__in=['EN_ROUTE', 'ON_SITE']
            ).first()
            
            if current_order:
                return current_order.status
            else:
                return 'ASSIGNED'  # Ha ordini assegnati ma non ancora partito
        
        return 'AVAILABLE'  # Online e disponibile
    
    def get_distance_from(self, lat, lng):
        """Calcola distanza da coordinate specifiche"""
        if not self.current_latitude or not self.current_longitude:
            return None
        
        from math import radians, sin, cos, sqrt, atan2
        
        R = 6371  # Raggio Terra in km
        
        lat1 = radians(float(self.current_latitude))
        lng1 = radians(float(self.current_longitude))
        lat2 = radians(lat)
        lng2 = radians(lng)
        
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        
        return R * c
    
    def update_location(self, latitude, longitude):
        """Aggiorna la posizione GPS del tecnico"""
        from django.utils import timezone
        self.current_latitude = latitude
        self.current_longitude = longitude
        self.last_location_update = timezone.now()
        self.save(update_fields=['current_latitude', 'current_longitude', 'last_location_update'])
    
    @property
    def is_online(self):
        """Controlla se il tecnico è online (aggiornamento GPS recente)"""
        if not self.last_location_update:
            return False
        
        # Considera online se l'ultimo aggiornamento è entro 5 minuti
        from datetime import timedelta
        from django.utils import timezone
        threshold = timezone.now() - timedelta(minutes=5)
        return self.last_location_update > threshold
    
    def get_workload_score(self):
        """Calcola score del carico di lavoro (0-100)"""
        active_orders = self.work_orders.filter(
            status__in=['ASSIGNED', 'EN_ROUTE', 'ON_SITE']
        ).count()
        
        # Score basato su numero ordini (massimo teorico 5)
        base_score = min(active_orders * 20, 100)
        
        # Penalità per ordini urgenti
        urgent_orders = self.work_orders.filter(
            status__in=['ASSIGNED', 'EN_ROUTE', 'ON_SITE'],
            priority='URGENT'
        ).count()
        
        urgency_penalty = urgent_orders * 10
        
        return min(base_score + urgency_penalty, 100)
    
    def can_accept_order(self, max_orders=5):
        """Verifica se il tecnico può accettare un nuovo ordine"""
        if not self.is_active:
            return False
        
        current_orders = self.work_orders.filter(
            status__in=['ASSIGNED', 'EN_ROUTE', 'ON_SITE']
        ).count()
        
        return current_orders < max_orders
    
    def get_performance_stats(self, days=30):
        """Statistiche performance degli ultimi N giorni"""
        from datetime import timedelta, date
        from django.utils import timezone
        from django.db.models import Count, Avg, F
        
        start_date = timezone.now().date() - timedelta(days=days)
        
        stats = self.work_orders.filter(
            created_at__date__gte=start_date
        ).aggregate(
            total_orders=Count('id'),
            completed_orders=Count('id', filter=Q(status='COMPLETED')),
            cancelled_orders=Count('id', filter=Q(status='CANCELLED')),
            avg_completion_time=Avg(
                F('completed_at') - F('started_at'),
                filter=Q(status='COMPLETED', started_at__isnull=False, completed_at__isnull=False)
            )
        )
        
        completion_rate = 0
        if stats['total_orders'] > 0:
            completion_rate = (stats['completed_orders'] / stats['total_orders']) * 100
        
        return {
            'total_orders': stats['total_orders'] or 0,
            'completed_orders': stats['completed_orders'] or 0,
            'cancelled_orders': stats['cancelled_orders'] or 0,
            'completion_rate': round(completion_rate, 1),
            'avg_completion_hours': round(stats['avg_completion_time'].total_seconds() / 3600, 1) if stats['avg_completion_time'] else None,
            'efficiency_score': self._calculate_efficiency_score(stats, completion_rate)
        }
    
    def _calculate_efficiency_score(self, stats, completion_rate):
        """Calcola score di efficienza (0-100)"""
        if stats['total_orders'] == 0:
            return 0
        
        # Peso per tasso completamento (70%)
        completion_score = completion_rate * 0.7
        
        # Peso per volume lavoro (30%)
        volume_score = min((stats['total_orders'] / 30) * 100, 100) * 0.3  # 30 ordini = 100%
        
        return round(completion_score + volume_score, 1)
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.company.name}"

class Customer(models.Model):
    """Cliente finale"""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='customers')
    name = models.CharField(max_length=200)
    phone = PhoneNumberField()
    email = models.EmailField(blank=True, null=True)
    address = models.TextField()
    
    # Coordinate per ottimizzare i percorsi
    latitude = models.DecimalField(max_digits=10, decimal_places=8, blank=True, null=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, blank=True, null=True)
    
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} - {self.company.name}"

class ServiceType(models.Model):
    """Tipologia di servizio/intervento"""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='service_types')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    estimated_duration_minutes = models.PositiveIntegerField(default=60)
    default_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    
    def __str__(self):
        return f"{self.name} - {self.company.name}"

class WorkOrder(models.Model):
    """Ordine di lavoro/intervento"""
    
    STATUS_CHOICES = [
        ('PENDING', 'Da Assegnare'),
        ('ASSIGNED', 'Assegnato'),
        ('EN_ROUTE', 'In Viaggio'),
        ('ON_SITE', 'Sul Posto'),
        ('COMPLETED', 'Completato'),
        ('CANCELLED', 'Annullato'),
    ]
    
    PRIORITY_CHOICES = [
        ('LOW', 'Bassa'),
        ('NORMAL', 'Normale'),
        ('HIGH', 'Alta'),
        ('URGENT', 'Urgente'),
    ]
    
    # Identificativo univoco
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=20, unique=True)
    
    # Relazioni
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='work_orders')
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='work_orders')
    technician = models.ForeignKey(Technician, on_delete=models.SET_NULL, blank=True, null=True, related_name='work_orders')
    service_type = models.ForeignKey(ServiceType, on_delete=models.SET_NULL, blank=True, null=True)
    
    # Dettagli intervento
    title = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='NORMAL')
    
    # Pianificazione
    scheduled_date = models.DateTimeField(blank=True, null=True)
    estimated_duration_minutes = models.PositiveIntegerField(default=60)
    
    # Tracking temporale
    created_at = models.DateTimeField(auto_now_add=True)
    assigned_at = models.DateTimeField(blank=True, null=True)
    started_at = models.DateTimeField(blank=True, null=True)  # Quando il tecnico arriva
    completed_at = models.DateTimeField(blank=True, null=True)
    
    # Indirizzo specifico dell'intervento (può essere diverso da quello del cliente)
    service_address = models.TextField()
    service_latitude = models.DecimalField(max_digits=10, decimal_places=8, blank=True, null=True)
    service_longitude = models.DecimalField(max_digits=11, decimal_places=8, blank=True, null=True)
    
    # Note e risultato
    technician_notes = models.TextField(blank=True, null=True)
    work_performed = models.TextField(blank=True, null=True)
    materials_used = models.TextField(blank=True, null=True)
    
    # Pricing
    estimated_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    final_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    
    def save(self, *args, **kwargs):
        if not self.order_number:
            # Genera numero ordine automatico
            year = timezone.now().year
            count = WorkOrder.objects.filter(
                company=self.company,
                created_at__year=year
            ).count() + 1
            self.order_number = f"{self.company.name[:3].upper()}{year}{count:04d}"
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.order_number} - {self.title}"
    
    class Meta:
        ordering = ['-created_at']

class Expense(models.Model):
    """Spese sostenute durante l'intervento"""
    EXPENSE_TYPES = [
        ('PARKING', 'Parcheggio'),
        ('FUEL', 'Carburante'),
        ('MATERIALS', 'Materiali'),
        ('TOLLS', 'Pedaggi'),
        ('OTHER', 'Altro'),
    ]
    
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name='expenses')
    technician = models.ForeignKey(Technician, on_delete=models.CASCADE)
    expense_type = models.CharField(max_length=20, choices=EXPENSE_TYPES)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    receipt_image = models.ImageField(upload_to='receipts/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.expense_type} - €{self.amount} - {self.work_order.order_number}"