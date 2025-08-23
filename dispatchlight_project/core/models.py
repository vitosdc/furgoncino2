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