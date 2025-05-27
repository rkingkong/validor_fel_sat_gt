"""
FEL (Factura Electrónica en Línea) System Configuration
Core constants, validation rules, and system configuration for SAT compliance

Based on:
- Acuerdo de Directorio SAT 13-2018
- Documento Técnico Informático para certificadores del Régimen FEL Versión 1.2
- FEL Reglas y Validaciones Versión 1.7.9
"""

from enum import Enum
from typing import Dict, List, Optional, Union
from decimal import Decimal
import re

# ========================================
# SYSTEM CONFIGURATION
# ========================================

class SystemConfig:
    # SAT API Configuration (Development Environment)
    SAT_API_BASE_URL = "https://api.desa.sat.gob.gt"
    SAT_API_TOKEN_ENDPOINT = "/getToken"
    SAT_API_DTE_ENDPOINT = "/postFactura"
    SAT_API_ANULACION_ENDPOINT = "/postAnulacionDTE"
    SAT_API_TEST_ENDPOINT = "/test"
    
    # XSD Schema URLs (Development Environment)
    XSD_BASE_URL = "https://cat.desa.sat.gob.gt/xsd/alfa/"
    CATALOGS_BASE_URL = "https://cat.desa.sat.gob.gt/catalogos/"
    
    # Schema Files
    XSD_SCHEMAS = {
        'GT_DOCUMENTO': 'GT_Documento-0.1.0.xsd',
        'GT_COMPLEMENTO_REFERENCIA_NOTA': 'GT_Complemento_Referencia_Nota-0.1.0.xsd',
        'GT_COMPLEMENTO_FAC_ESPECIAL': 'GT_Complemento_Fac_Especial-0.1.0.xsd',
        'GT_COMPLEMENTO_EXPORTACIONES': 'GT_Complemento_Exportaciones-0.1.0.xsd',
        'GT_COMPLEMENTO_CAMBIARIA': 'GT_Complemento_Cambiaria-0.1.0.xsd',
        'GT_ANULACION_DOCUMENTO': 'GT_AnulacionDocumento-0.1.0.xsd'
    }
    
    # System Limits
    MAX_DTE_PER_BATCH = 1000
    TOKEN_EXPIRY_MINUTES = 60
    MAX_RETRY_ATTEMPTS = 3
    
    # Validation Tolerances
    MONETARY_TOLERANCE = Decimal('0.01')  # 1 centavo tolerance for calculations

# ========================================
# DTE TYPES AND CODES
# ========================================

class DTEType(Enum):
    """Document Types as defined in FEL regulations"""
    FACT = "FACT"           # Factura
    FCAM = "FCAM"           # Factura Cambiaria
    FPEQ = "FPEQ"           # Factura Pequeño Contribuyente
    FCAP = "FCAP"           # Factura Cambiaria Pequeño Contribuyente
    FESP = "FESP"           # Factura Especial
    NABN = "NABN"           # Nota de Abono
    RDON = "RDON"           # Recibo por Donación
    RECI = "RECI"           # Recibo
    NDEB = "NDEB"           # Nota de Débito
    NCRE = "NCRE"           # Nota de Crédito
    FACA = "FACA"           # Factura Contribuyente Agropecuario
    FCCA = "FCCA"           # Factura Cambiaria Contribuyente Agropecuario
    FAPE = "FAPE"           # Factura Pequeño Contribuyente Régimen Electrónico
    FCPE = "FCPE"           # Factura Cambiaria Pequeño Contribuyente Régimen Electrónico
    FAAE = "FAAE"           # Factura Contribuyente Agropecuario Régimen Electrónico Especial
    FCAE = "FCAE"           # Factura Cambiaria Contribuyente Agropecuario Régimen Electrónico Especial
    CIVA = "CIVA"           # Constancia de Exención de IVA
    CAIS = "CAIS"           # Constancia de Adquisición de Insumos y Servicios
    NEV = "NEV"             # Nota de Envío
    RANT = "RANT"           # Recibo de Anticipos

# ========================================
# TAX TYPES AND CONFIGURATIONS
# ========================================

class TaxType(Enum):
    """Tax types supported by the system"""
    IVA = "IVA"                     # Impuesto al Valor Agregado
    PETROLEO = "PETROLEO"           # Impuesto a la Distribución de Petróleo
    TURISMO_HOSPEDAJE = "TURISMO HOSPEDAJE"    # Impuesto al Turismo Hospedaje
    TURISMO_PASAJES = "TURISMO PASAJES"        # Impuesto al Turismo Pasajes
    TIMBRE_PRENSA = "TIMBRE DE PRENSA"         # Timbre de Prensa
    BOMBEROS = "BOMBEROS"           # Impuesto a Favor del Cuerpo Voluntario de Bomberos
    TASA_MUNICIPAL = "TASA MUNICIPAL"          # Tasa Municipal
    BEBIDAS_ALCOHOLICAS = "BEBIDAS ALCOHÓLICAS"    # Impuesto sobre Bebidas Alcohólicas
    TABACO = "TABACO"               # Impuesto al Tabaco
    CEMENTO = "CEMENTO"             # Impuesto Específico a la Distribución de Cemento
    BEBIDAS_NO_ALCOHOLICAS = "BEBIDAS NO ALCOHÓLICAS"  # Impuesto Específico sobre Bebidas No Alcohólicas
    TARIFA_PORTUARIA = "TARIFA PORTUARIA"      # Tarifa Portuaria

# Tax configurations
TAX_CONFIGS = {
    TaxType.IVA: {
        'code': 1,
        'name': 'Impuesto al Valor Agregado (IVA)',
        'short_name': 'IVA',
        'base_legal': 'Decreto 27-92',
        'add_to_total': False,  # Already included in price
        'show_in_representation': False,
        'gravable_units': {
            1: {'name': 'Tasa 12.00%', 'short': 'IVA 12%', 'rate': 12},
            2: {'name': 'Tasa 0 (Cero)', 'short': 'IVA 0%', 'rate': 0}
        }
    },
    TaxType.PETROLEO: {
        'code': 2,
        'name': 'Impuesto a la Distribución de Petróleo Crudo y Combustibles Derivados del Petróleo (IDP)',
        'short_name': 'PETROLEO',
        'base_legal': 'Decreto 38-92',
        'add_to_total': True,
        'show_in_representation': True,
        'gravable_units': {
            1: {'name': 'Gasolina superior', 'rate': 4.70},
            2: {'name': 'Gasolina regular', 'rate': 4.60},
            3: {'name': 'Gasolina de aviación', 'rate': 4.70},
            4: {'name': 'Diésel', 'rate': 1.30},
            5: {'name': 'Gas Oil', 'rate': 1.30},
            6: {'name': 'Kerosina', 'rate': 0.50},
            7: {'name': 'Nafta', 'rate': 0.50},
            8: {'name': 'Fuel Oil (Bunker C)', 'rate': 0.00},
            9: {'name': 'Gas licuado de petróleo a granel', 'rate': 0.50},
            10: {'name': 'Gas licuado petróleo carburación', 'rate': 0.50},
            11: {'name': 'Petróleo crudo usado como combustible', 'rate': 0.00},
            12: {'name': 'Otros combustibles derivados del petróleo', 'rate': 0.00},
            13: {'name': 'Asfaltos', 'rate': 0.00}
        }
    }
    # Additional tax configurations would be added here for other tax types...
}

# ========================================
# PHRASE TYPES AND SCENARIOS
# ========================================

class PhraseType(Enum):
    """Phrase types for DTE documents"""
    ISR_RETENTION = 1       # Frases de retención del ISR
    IVA_AGENT = 2          # Frases de Agente de retención del IVA
    NO_CREDIT_FISCAL = 3   # Frases de no genera derecho a crédito fiscal del IVA
    IVA_EXEMPT = 4         # Frases de exento o no afecto al IVA
    SPECIAL_INVOICE = 5    # Frases de facturas especiales
    AGRICULTURAL = 6       # Frases de contribuyente agropecuario
    ELECTRONIC_REGIME = 7  # Frases de regímenes electrónicos
    ISR_EXEMPT = 8         # Frases de exento de ISR
    SPECIAL = 9            # Frases especiales

# IVA Exemption scenarios (Phrase Type 4)
IVA_EXEMPTION_SCENARIOS = {
    1: {
        'description': 'Exportaciones',
        'legal_base': 'Exenta del IVA (art. 7 num. 2 Ley del IVA)',
        'allowed_dte': ['FACT', 'FCAM']
    },
    2: {
        'description': 'Servicios instituciones fiscalizadas por Superintendencia de Bancos',
        'legal_base': 'Exenta del IVA (art. 7 num. 4 Ley del IVA)',
        'allowed_dte': ['FACT', 'FCAM']
    },
    3: {
        'description': 'Ventas de cooperativas',
        'legal_base': 'Exenta del IVA (art. 7 num. 5 Ley del IVA)',
        'allowed_dte': ['FACT', 'FCAM']
    },
    4: {
        'description': 'Donaciones',
        'legal_base': 'Exenta del IVA (art. 7 num. 9 Ley del IVA)',
        'allowed_dte': ['RDON']
    },
    # Additional scenarios would be defined here...
}

# ========================================
# VALIDATION RULES
# ========================================

class ValidationRules:
    """Core validation rules for DTE processing"""
    
    # NIT validation pattern
    NIT_PATTERN = re.compile(r'^\d{1,12}[0-9K]$')
    
    # CUI validation pattern
    CUI_PATTERN = re.compile(r'^\d{13}$')
    
    # UUID validation pattern
    UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$', re.IGNORECASE)
    
    # Maximum amounts for CF (Consumidor Final)
    MAX_CF_AMOUNT_GTQ = Decimal('2500.00')
    
    # Date validation rules
    MAX_EMISSION_DAYS_BACK = 5  # Maximum days back for emission date
    
    # Monetary validation
    DECIMAL_PLACES = 2
    MAX_MONETARY_VALUE = Decimal('999999999999.99')
    
    # Text field limits
    MAX_DESCRIPTION_LENGTH = 500
    MAX_NAME_LENGTH = 256
    MAX_ADDRESS_LENGTH = 256
    
    @staticmethod
    def validate_nit(nit: str) -> bool:
        """Validate NIT format and check digit"""
        if not ValidationRules.NIT_PATTERN.match(nit):
            return False
        
        # Calculate check digit
        if len(nit) < 2:
            return False
            
        number_part = nit[:-1]
        check_digit = nit[-1]
        
        # Calculate expected check digit
        total = 0
        multiplier = len(number_part) + 1
        
        for digit in number_part:
            total += int(digit) * multiplier
            multiplier -= 1
        
        remainder = total % 11
        expected_digit = '0' if remainder == 0 else 'K' if remainder == 1 else str(11 - remainder)
        
        return check_digit == expected_digit
    
    @staticmethod
    def validate_cui(cui: str) -> bool:
        """Validate CUI format and check digit"""
        if not ValidationRules.CUI_PATTERN.match(cui):
            return False
        
        # CUI validation algorithm implementation
        if len(cui) == 13:
            # Extract parts for validation
            verification_digit = int(cui[8])  # 9th digit (0-based index 8)
            
            # Calculate check digit
            total = 0
            multipliers = [2, 3, 4, 5, 6, 7, 8, 9] if len(cui) == 13 else [3, 4, 5, 6, 7, 8, 9]
            
            digits_to_check = cui[:8] if len(cui) == 13 else cui[:7]
            
            for i, digit in enumerate(digits_to_check):
                total += int(digit) * multipliers[i]
            
            calculated = (total * 10) % 11
            expected_digit = 0 if calculated == 10 else calculated
            
            return verification_digit == expected_digit
            
        return False

# ========================================
# COMPLEMENT CONFIGURATIONS
# ========================================

class ComplementType(Enum):
    """Available complements for DTE documents"""
    EXPORTACION = 1
    RETENC_FACTURA_ESPECIAL = 2
    ABONOS_FACTURA_CAMBIARIA = 3
    REFERENCIAS_NOTA = 4
    COBRO_CUENTA_AJENA = 5
    ESPECTACULOS_PUBLICOS = 6
    REFERENCIAS_CONSTANCIA = 7
    MEDIOS_PAGO = 8
    DECRETO_31_2022 = 9
    ORGANIZACIONES_POLITICAS = 10
    TRASLADO_MERCANCIAS = 11

# INCOTERMS for exports
INCOTERMS = {
    'EXW': 'En fábrica',
    'FCA': 'Libre transportista',
    'FAS': 'Libre al costado del buque',
    'FOB': 'Libre a bordo',
    'CFR': 'Costo y flete',
    'CIF': 'Costo, seguro y flete',
    'CPT': 'Flete pagado hasta',
    'CIP': 'Flete y seguro pagado hasta',
    'DDP': 'Entregado en destino con derechos pagados',
    'DAP': 'Entregada en lugar',
    'DPU': 'Entregada en el lugar de la descarga',
    'ZZZ': 'Otros'
}

# ========================================
# ERROR CODES AND MESSAGES
# ========================================

class ErrorCodes:
    """Standard error codes for the FEL system"""
    
    # Schema validation errors
    SCHEMA_VALIDATION_ERROR = "ERR_001"
    INVALID_XML_FORMAT = "ERR_002"
    
    # Business rule validation errors
    INVALID_DATE_RANGE = "ERR_101"
    INVALID_NIT_FORMAT = "ERR_102"
    INVALID_AMOUNTS = "ERR_103"
    INVALID_TAX_CALCULATION = "ERR_104"
    
    # Authentication errors
    INVALID_CREDENTIALS = "ERR_201"
    TOKEN_EXPIRED = "ERR_202"
    
    # SAT API errors
    SAT_API_ERROR = "ERR_301"
    SAT_REJECTION = "ERR_302"
    
    # System errors
    DATABASE_ERROR = "ERR_401"
    SIGNATURE_ERROR = "ERR_402"

# Error messages in Spanish
ERROR_MESSAGES = {
    ErrorCodes.SCHEMA_VALIDATION_ERROR: "El XML enviado no cumple con el esquema del XSD",
    ErrorCodes.INVALID_XML_FORMAT: "Formato XML inválido",
    ErrorCodes.INVALID_DATE_RANGE: "La diferencia entre la fecha de emisión y de certificación excede los cinco días",
    ErrorCodes.INVALID_NIT_FORMAT: "El NIT no tiene un formato válido",
    ErrorCodes.INVALID_AMOUNTS: "Los montos calculados son incorrectos",
    ErrorCodes.INVALID_TAX_CALCULATION: "El cálculo de impuestos es incorrecto",
    ErrorCodes.INVALID_CREDENTIALS: "Credenciales inválidas",
    ErrorCodes.TOKEN_EXPIRED: "Token de acceso expirado",
    ErrorCodes.SAT_API_ERROR: "Error en la comunicación con SAT",
    ErrorCodes.SAT_REJECTION: "Documento rechazado por SAT",
    ErrorCodes.DATABASE_ERROR: "Error en la base de datos",
    ErrorCodes.SIGNATURE_ERROR: "Error en la firma electrónica"
}

# ========================================
# CURRENCY CONFIGURATIONS
# ========================================

SUPPORTED_CURRENCIES = {
    'GTQ': {'name': 'Quetzal Guatemalteco', 'symbol': 'Q', 'decimal_places': 2},
    'USD': {'name': 'Dólar Estadounidense', 'symbol': '$', 'decimal_places': 2},
    'EUR': {'name': 'Euro', 'symbol': '€', 'decimal_places': 2}
}

# ========================================
# ESTABLISHMENT CLASSIFICATIONS
# ========================================

ESTABLISHMENT_CLASSIFICATIONS = {
    'CIVA_ALLOWED': {
        1703: [1704],  # Persona individual - Centros educativos privados
        969: [],       # Agentes diplomáticos
        971: [],       # Empleados diplomáticos
        970: [],       # Funcionarios diplomáticos
        887: [962, 963, 1084],  # Persona jurídica - Centros educativos, Universidades
        # Additional classifications would be added here...
    }
}

# ========================================
# PRODUCT CODES
# ========================================

PRODUCT_CODES = {
    'CGP10LBS': {'name': 'Subsidio cilindro 10 libras', 'discount': 8.00},
    'CGP20LBS': {'name': 'Subsidio cilindro 20 libras', 'discount': 16.00},
    'CGP25LBS': {'name': 'Subsidio cilindro 25 libras', 'discount': 20.00},
    'CGP35LBS': {'name': 'Subsidio cilindro 35 libras', 'discount': 28.00},
    'CGP100LBS': {'name': 'Cilindro de gas envasado propano de 100 lbs', 'discount': 0.00},
    'GALDIESEL': {'name': 'Galón de diesel con apoyo social', 'discount': 0.00}
}

# ========================================
# LOGGING CONFIGURATION
# ========================================

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
        'detailed': {
            'format': '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s'
        }
    },
    'handlers': {
        'default': {
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
        },
        'file': {
            'level': 'DEBUG',
            'formatter': 'detailed',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'fel_system.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5,
        }
    },
    'loggers': {
        '': {
            'handlers': ['default', 'file'],
            'level': 'DEBUG',
            'propagate': False
        }
    }
}

# ========================================
# SYSTEM CONSTANTS
# ========================================

class Constants:
    """System-wide constants"""
    
    # Version information
    SYSTEM_VERSION = "1.0.0"
    FEL_REGULATION_VERSION = "1.7.9"
    
    # Default values
    DEFAULT_CURRENCY = "GTQ"
    DEFAULT_TIMEZONE = "America/Guatemala"
    
    # File paths
    TEMP_DIR = "/tmp/fel_system"
    LOG_DIR = "/var/log/fel_system"
    BACKUP_DIR = "/backup/fel_system"
    
    # Database configuration
    DB_CONNECTION_POOL_SIZE = 20
    DB_CONNECTION_TIMEOUT = 30
    
    # Security
    JWT_EXPIRY_HOURS = 24
    PASSWORD_HASH_ROUNDS = 12
    
    # Performance
    CACHE_TTL_SECONDS = 3600  # 1 hour
    MAX_CONCURRENT_REQUESTS = 100

if __name__ == "__main__":
    # Basic configuration validation
    print(f"FEL System Configuration Loaded")
    print(f"System Version: {Constants.SYSTEM_VERSION}")
    print(f"FEL Regulation Version: {Constants.FEL_REGULATION_VERSION}")
    print(f"Supported DTE Types: {len(DTEType)}")
    print(f"Supported Tax Types: {len(TaxType)}")
    print(f"Available Complements: {len(ComplementType)}")
    
    # Test NIT validation
    test_nits = ["1234567K", "987654321", "CF"]
    for nit in test_nits:
        is_valid = ValidationRules.validate_nit(nit) if nit != "CF" else True
        print(f"NIT {nit}: {'Valid' if is_valid else 'Invalid'}")
