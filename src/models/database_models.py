"""
FEL Database Models
SQLAlchemy ORM models for the FEL certification system

Stores all DTE documents, taxpayer information, validation results,
and system data in compliance with SAT requirements.

File: src/models/database_models.py
"""

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Decimal, Boolean, 
    ForeignKey, Index, UniqueConstraint, CheckConstraint,
    JSON, LargeBinary, Enum as SQLEnum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, backref
from sqlalchemy.sql import func
from datetime import datetime
from decimal import Decimal as PyDecimal
from enum import Enum
import uuid

# Import our configuration
from config.fel_config import DTEType, TaxType, PhraseType, ComplementType

Base = declarative_base()

# ========================================
# ENUMS FOR DATABASE
# ========================================

class DTEStatus(Enum):
    """Status of DTE documents"""
    RECEIVED = "RECEIVED"           # Received from emisor
    VALIDATING = "VALIDATING"       # In validation process
    VALIDATED = "VALIDATED"         # Passed validation
    CERTIFIED = "CERTIFIED"         # Certified and signed
    SENT_TO_SAT = "SENT_TO_SAT"    # Sent to SAT
    SAT_ACCEPTED = "SAT_ACCEPTED"   # Accepted by SAT
    SAT_REJECTED = "SAT_REJECTED"   # Rejected by SAT
    CANCELLED = "CANCELLED"         # Cancelled/Anulado
    ERROR = "ERROR"                 # Error in processing

class ValidationResult(Enum):
    """Validation results"""
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"

class SignatureStatus(Enum):
    """Electronic signature status"""
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"
    EXPIRED = "EXPIRED"

# ========================================
# TAXPAYER MANAGEMENT MODELS
# ========================================

class Taxpayer(Base):
    """
    Taxpayer information (Contribuyentes)
    Stores emisor and receptor information
    """
    __tablename__ = 'taxpayers'
    
    id = Column(Integer, primary_key=True)
    nit = Column(String(15), unique=True, nullable=False, index=True)
    name = Column(String(256), nullable=False)
    commercial_name = Column(String(256))
    
    # RTU Information
    rtu_status = Column(String(20), default='ACTIVE')  # ACTIVE, INACTIVE, SUSPENDED
    iva_affiliation = Column(String(10))  # GEN, PEQ, AGR, etc.
    isr_affiliation = Column(String(10))  # REG, OPT, etc.
    
    # Address information
    address = Column(Text)
    department = Column(String(50))
    municipality = Column(String(50))
    
    # System fields
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    is_active = Column(Boolean, default=True)
    
    # Relationships
    establishments = relationship("Establishment", back_populates="taxpayer")
    issued_dtes = relationship("DTE", foreign_keys="DTE.emisor_nit", back_populates="emisor")
    received_dtes = relationship("DTE", foreign_keys="DTE.receptor_id", back_populates="receptor")
    
    # Indexes
    __table_args__ = (
        Index('idx_taxpayer_nit', 'nit'),
        Index('idx_taxpayer_status', 'rtu_status'),
    )

class Establishment(Base):
    """
    Taxpayer establishments (Establecimientos)
    Each taxpayer can have multiple establishments
    """
    __tablename__ = 'establishments'
    
    id = Column(Integer, primary_key=True)
    taxpayer_id = Column(Integer, ForeignKey('taxpayers.id'), nullable=False)
    establishment_code = Column(String(10), nullable=False)
    name = Column(String(256), nullable=False)
    
    # Address
    address = Column(Text)
    department = Column(String(50))
    municipality = Column(String(50))
    
    # Classification
    classification_code = Column(String(10))
    type_code = Column(String(10))
    
    # Status
    status = Column(String(20), default='ACTIVE')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    taxpayer = relationship("Taxpayer", back_populates="establishments")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('taxpayer_id', 'establishment_code'),
        Index('idx_establishment_code', 'establishment_code'),
    )

# ========================================
# ELECTRONIC SIGNATURE MODELS
# ========================================

class DigitalCertificate(Base):
    """
    Digital certificates for electronic signatures
    Stores both emisor and certificador certificates
    """
    __tablename__ = 'digital_certificates'
    
    id = Column(Integer, primary_key=True)
    owner_nit = Column(String(15), nullable=False, index=True)
    certificate_type = Column(String(20), nullable=False)  # EMISOR, CERTIFICADOR
    
    # Certificate data
    certificate_data = Column(LargeBinary, nullable=False)  # X.509 certificate
    private_key_data = Column(LargeBinary)  # Encrypted private key
    certificate_password_hash = Column(String(255))  # Hashed password
    
    # Certificate information
    serial_number = Column(String(100))
    issuer = Column(String(512))
    subject = Column(String(512))
    valid_from = Column(DateTime, nullable=False)
    valid_until = Column(DateTime, nullable=False)
    
    # Status
    status = Column(SQLEnum(SignatureStatus), default=SignatureStatus.VALID)
    created_at = Column(DateTime, default=func.now())
    revoked_at = Column(DateTime)
    
    # Indexes
    __table_args__ = (
        Index('idx_cert_owner_type', 'owner_nit', 'certificate_type'),
        Index('idx_cert_validity', 'valid_from', 'valid_until'),
    )

# ========================================
# DTE CORE MODELS
# ========================================

class DTE(Base):
    """
    Main DTE document table
    Stores all DTE documents with their core information
    """
    __tablename__ = 'dtes'
    
    id = Column(Integer, primary_key=True)
    
    # Core DTE identification
    uuid = Column(String(36), unique=True, nullable=False, index=True)
    serie = Column(String(8), nullable=False)
    numero = Column(Integer, nullable=False)
    dte_type = Column(SQLEnum(DTEType), nullable=False)
    
    # Document participants
    emisor_nit = Column(String(15), ForeignKey('taxpayers.nit'), nullable=False)
    establishment_code = Column(String(10), nullable=False)
    receptor_id = Column(String(20), nullable=False)  # Can be NIT, CUI, or CF
    receptor_name = Column(String(256))
    receptor_type = Column(String(10))  # NIT, CUI, EXT, CF
    
    # Document dates
    emission_date = Column(DateTime, nullable=False)
    certification_date = Column(DateTime)
    
    # Financial information
    currency = Column(String(3), default='GTQ')
    total_amount = Column(Decimal(15, 2), nullable=False)
    grand_total = Column(Decimal(15, 2), nullable=False)
    
    # Document content
    xml_content = Column(Text, nullable=False)  # Original XML from emisor
    certified_xml = Column(Text)  # Certified XML with signatures
    
    # Validation and processing
    status = Column(SQLEnum(DTEStatus), default=DTEStatus.RECEIVED)
    validation_result = Column(SQLEnum(ValidationResult), default=ValidationResult.PENDING)
    validation_errors = Column(JSON)  # Array of validation errors
    
    # SAT communication
    sat_response = Column(JSON)  # SAT acknowledgment response
    sat_sent_at = Column(DateTime)
    sat_response_at = Column(DateTime)
    
    # Export and special flags
    is_export = Column(Boolean, default=False)
    is_contingency = Column(Boolean, default=False)
    contingency_access_number = Column(String(9))
    
    # System fields
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    processed_by = Column(String(100))  # System user/process
    
    # Relationships
    emisor = relationship("Taxpayer", foreign_keys=[emisor_nit], back_populates="issued_dtes")
    receptor = relationship("Taxpayer", foreign_keys=[receptor_id], back_populates="received_dtes")
    items = relationship("DTEItem", back_populates="dte", cascade="all, delete-orphan")
    taxes = relationship("DTETax", back_populates="dte", cascade="all, delete-orphan")
    phrases = relationship("DTEPhrase", back_populates="dte", cascade="all, delete-orphan")
    complements = relationship("DTEComplement", back_populates="dte", cascade="all, delete-orphan")
    signatures = relationship("DTESignature", back_populates="dte", cascade="all, delete-orphan")
    validations = relationship("DTEValidation", back_populates="dte", cascade="all, delete-orphan")
    
    # Indexes and constraints
    __table_args__ = (
        Index('idx_dte_uuid', 'uuid'),
        Index('idx_dte_emisor_date', 'emisor_nit', 'emission_date'),
        Index('idx_dte_status', 'status'),
        Index('idx_dte_type_date', 'dte_type', 'emission_date'),
        Index('idx_dte_receptor', 'receptor_id'),
        CheckConstraint('total_amount >= 0', name='check_positive_total'),
        CheckConstraint('grand_total >= 0', name='check_positive_grand_total'),
    )

class DTEItem(Base):
    """
    DTE line items (Items/Líneas)
    Each DTE can have multiple items
    """
    __tablename__ = 'dte_items'
    
    id = Column(Integer, primary_key=True)
    dte_id = Column(Integer, ForeignKey('dtes.id'), nullable=False)
    line_number = Column(Integer, nullable=False)
    
    # Item information
    item_type = Column(String(1), nullable=False)  # B = Bien, S = Servicio
    quantity = Column(Decimal(15, 6), nullable=False)
    unit_of_measure = Column(String(50))
    description = Column(String(500), nullable=False)
    
    # Pricing
    unit_price = Column(Decimal(15, 6), nullable=False)
    price = Column(Decimal(15, 2), nullable=False)
    discount = Column(Decimal(15, 2), default=0)
    other_discounts = Column(Decimal(15, 2), default=0)
    total = Column(Decimal(15, 2), nullable=False)
    
    # Product coding (optional)
    product_code = Column(String(50))
    
    # Relationship
    dte = relationship("DTE", back_populates="items")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('dte_id', 'line_number'),
        CheckConstraint('quantity > 0', name='check_positive_quantity'),
        CheckConstraint('unit_price >= 0', name='check_non_negative_unit_price'),
        CheckConstraint('price >= 0', name='check_non_negative_price'),
    )

class DTETax(Base):
    """
    Tax information for DTE documents
    Each DTE can have multiple taxes applied
    """
    __tablename__ = 'dte_taxes'
    
    id = Column(Integer, primary_key=True)
    dte_id = Column(Integer, ForeignKey('dtes.id'), nullable=False)
    tax_type = Column(SQLEnum(TaxType), nullable=False)
    
    # Tax calculation
    taxable_amount = Column(Decimal(15, 2))  # Monto gravable
    tax_unit_code = Column(Integer)  # Código unidad gravable
    tax_units_quantity = Column(Decimal(15, 6))  # Cantidad unidades gravables
    tax_amount = Column(Decimal(15, 2), nullable=False)  # Monto impuesto
    
    # Total for this tax type
    total_tax_amount = Column(Decimal(15, 2), nullable=False)
    
    # Relationship
    dte = relationship("DTE", back_populates="taxes")
    
    # Constraints
    __table_args__ = (
        Index('idx_dte_tax_type', 'dte_id', 'tax_type'),
        CheckConstraint('tax_amount >= 0', name='check_non_negative_tax'),
    )

class DTEPhrase(Base):
    """
    Phrases (Frases) included in DTE documents
    Each DTE can have multiple phrases for different scenarios
    """
    __tablename__ = 'dte_phrases'
    
    id = Column(Integer, primary_key=True)
    dte_id = Column(Integer, ForeignKey('dtes.id'), nullable=False)
    phrase_type = Column(SQLEnum(PhraseType), nullable=False)
    scenario_code = Column(Integer, nullable=False)
    
    # Additional phrase data
    resolution_number = Column(String(50))  # For certain phrase types
    resolution_date = Column(DateTime)  # For certain phrase types
    phrase_text = Column(Text)  # The actual phrase text
    
    # Relationship
    dte = relationship("DTE", back_populates="phrases")
    
    # Constraints
    __table_args__ = (
        Index('idx_dte_phrase_type', 'dte_id', 'phrase_type'),
    )

class DTEComplement(Base):
    """
    Complements (Complementos) for DTE documents
    Stores additional structured data for specific document types
    """
    __tablename__ = 'dte_complements'
    
    id = Column(Integer, primary_key=True)
    dte_id = Column(Integer, ForeignKey('dtes.id'), nullable=False)
    complement_type = Column(SQLEnum(ComplementType), nullable=False)
    
    # Complement data stored as JSON for flexibility
    complement_data = Column(JSON, nullable=False)
    
    # Relationship
    dte = relationship("DTE", back_populates="complements")
    
    # Constraints
    __table_args__ = (
        Index('idx_dte_complement_type', 'dte_id', 'complement_type'),
    )

# ========================================
# SIGNATURE AND VALIDATION MODELS
# ========================================

class DTESignature(Base):
    """
    Electronic signatures for DTE documents
    Stores both emisor and certificador signatures
    """
    __tablename__ = 'dte_signatures'
    
    id = Column(Integer, primary_key=True)
    dte_id = Column(Integer, ForeignKey('dtes.id'), nullable=False)
    signature_type = Column(String(20), nullable=False)  # EMISOR, CERTIFICADOR
    
    # Signature information
    signer_nit = Column(String(15), nullable=False)
    certificate_id = Column(Integer, ForeignKey('digital_certificates.id'))
    signature_data = Column(Text, nullable=False)  # Base64 encoded signature
    signature_algorithm = Column(String(50), default='RSA-SHA256')
    
    # Validation
    is_valid = Column(Boolean, default=False)
    validation_date = Column(DateTime)
    validation_details = Column(JSON)
    
    # Timestamps
    signed_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    dte = relationship("DTE", back_populates="signatures")
    certificate = relationship("DigitalCertificate")
    
    # Constraints
    __table_args__ = (
        Index('idx_signature_dte_type', 'dte_id', 'signature_type'),
    )

class DTEValidation(Base):
    """
    Validation results for DTE documents
    Stores detailed validation information for audit purposes
    """
    __tablename__ = 'dte_validations'
    
    id = Column(Integer, primary_key=True)
    dte_id = Column(Integer, ForeignKey('dtes.id'), nullable=False)
    
    # Validation information
    validation_type = Column(String(50), nullable=False)  # SCHEMA, BUSINESS_RULE, etc.
    validation_rule = Column(String(100), nullable=False)  # Specific rule validated
    result = Column(SQLEnum(ValidationResult), nullable=False)
    
    # Details
    error_code = Column(String(20))
    error_message = Column(Text)
    field_name = Column(String(100))  # Field that failed validation
    expected_value = Column(String(500))
    actual_value = Column(String(500))
    
    # Timestamps
    validated_at = Column(DateTime, default=func.now())
    validated_by = Column(String(100))  # System component that performed validation
    
    # Relationship
    dte = relationship("DTE", back_populates="validations")
    
    # Indexes
    __table_args__ = (
        Index('idx_validation_dte_result', 'dte_id', 'result'),
        Index('idx_validation_type', 'validation_type'),
    )

# ========================================
# SYSTEM ADMINISTRATION MODELS
# ========================================

class CertificadorUser(Base):
    """
    System users (certificador staff)
    """
    __tablename__ = 'certificador_users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    
    # User information
    full_name = Column(String(256), nullable=False)
    role = Column(String(50), nullable=False)  # ADMIN, OPERATOR, VIEWER
    
    # Status
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Indexes
    __table_args__ = (
        Index('idx_user_username', 'username'),
        Index('idx_user_email', 'email'),
    )

class SystemConfiguration(Base):
    """
    System configuration parameters
    """
    __tablename__ = 'system_config'
    
    id = Column(Integer, primary_key=True)
    config_key = Column(String(100), unique=True, nullable=False)
    config_value = Column(Text, nullable=False)
    config_type = Column(String(20), default='STRING')  # STRING, INTEGER, BOOLEAN, JSON
    description = Column(Text)
    
    # Metadata
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    updated_by = Column(String(100))

class AuditLog(Base):
    """
    Audit trail for all system operations
    """
    __tablename__ = 'audit_logs'
    
    id = Column(Integer, primary_key=True)
    
    # Operation details
    operation = Column(String(100), nullable=False)  # CREATE_DTE, VALIDATE_DTE, etc.
    entity_type = Column(String(50), nullable=False)  # DTE, TAXPAYER, etc.
    entity_id = Column(String(50), nullable=False)  # ID of the affected entity
    
    # User and system info
    user_id = Column(Integer, ForeignKey('certificador_users.id'))
    user_ip = Column(String(45))  # IPv4 or IPv6
    user_agent = Column(String(500))
    
    # Operation details
    old_values = Column(JSON)  # Previous state
    new_values = Column(JSON)  # New state
    additional_data = Column(JSON)  # Any additional context
    
    # Status
    success = Column(Boolean, nullable=False)
    error_message = Column(Text)
    
    # Timestamp
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    user = relationship("CertificadorUser")
    
    # Indexes
    __table_args__ = (
        Index('idx_audit_operation_date', 'operation', 'created_at'),
        Index('idx_audit_entity', 'entity_type', 'entity_id'),
        Index('idx_audit_user_date', 'user_id', 'created_at'),
    )

# ========================================
# ANULATION MODELS
# ========================================

class DTEAnulation(Base):
    """
    DTE Anulation transactions (Anulaciones)
    """
    __tablename__ = 'dte_anulations'
    
    id = Column(Integer, primary_key=True)
    
    # Anulation identification
    anulation_uuid = Column(String(36), unique=True, nullable=False)
    original_dte_uuid = Column(String(36), ForeignKey('dtes.uuid'), nullable=False)
    
    # Anulation details
    emisor_nit = Column(String(15), nullable=False)
    receptor_id = Column(String(20), nullable=False)
    certificador_nit = Column(String(15), nullable=False)
    
    # Dates
    original_emission_date = Column(DateTime, nullable=False)
    anulation_date = Column(DateTime, nullable=False)
    certification_date = Column(DateTime)
    
    # Reason and justification
    reason = Column(Text, nullable=False)
    
    # XML content
    anulation_xml = Column(Text, nullable=False)
    certified_anulation_xml = Column(Text)
    
    # Status
    status = Column(SQLEnum(DTEStatus), default=DTEStatus.RECEIVED)
    sat_response = Column(JSON)
    sat_sent_at = Column(DateTime)
    sat_response_at = Column(DateTime)
    
    # System fields
    created_at = Column(DateTime, default=func.now())
    processed_by = Column(String(100))
    
    # Relationships
    original_dte = relationship("DTE")
    
    # Indexes
    __table_args__ = (
        Index('idx_anulation_uuid', 'anulation_uuid'),
        Index('idx_anulation_original_dte', 'original_dte_uuid'),
        Index('idx_anulation_date', 'anulation_date'),
    )

# ========================================
# UTILITY FUNCTIONS
# ========================================

def create_all_tables(engine):
    """
    Create all database tables
    """
    Base.metadata.create_all(engine)

def generate_uuid() -> str:
    """
    Generate a UUID v4 for DTE authorization numbers
    """
    return str(uuid.uuid4()).upper()

def generate_serie_from_uuid(uuid_str: str) -> str:
    """
    Generate serie from UUID (first 8 characters)
    """
    return uuid_str.replace('-', '')[:8].upper()

def generate_numero_from_uuid(uuid_str: str) -> int:
    """
    Generate numero from UUID (positions 9-16 as decimal)
    """
    clean_uuid = uuid_str.replace('-', '')
    hex_portion = clean_uuid[8:16]  # Characters 9-16 (0-based indexing)
    return int(hex_portion, 16) % 999999999  # Ensure it fits in integer range

# ========================================
# DATABASE INITIALIZATION
# ========================================

if __name__ == "__main__":
    # Example of how to use these models
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    # Create in-memory SQLite database for testing
    engine = create_engine('sqlite:///:memory:', echo=True)
    create_all_tables(engine)
    
    # Create session
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Example: Create a test taxpayer
    taxpayer = Taxpayer(
        nit="1234567K",
        name="Empresa de Prueba S.A.",
        commercial_name="Empresa Prueba",
        iva_affiliation="GEN",
        address="Ciudad de Guatemala"
    )
    
    session.add(taxpayer)
    session.commit()
    
    print(f"Created taxpayer: {taxpayer.name} with NIT: {taxpayer.nit}")
    
    # Test UUID generation
    test_uuid = generate_uuid()
    serie = generate_serie_from_uuid(test_uuid)
    numero = generate_numero_from_uuid(test_uuid)
    
    print(f"Test UUID: {test_uuid}")
    print(f"Serie: {serie}")
    print(f"Numero: {numero}")
    
    session.close()
