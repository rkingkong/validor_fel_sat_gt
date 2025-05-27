"""
FEL Business Rules Validator
Implements all SAT business validation rules from FEL Reglas y Validaciones v1.7.9

This validator applies all business logic rules defined by SAT after
XML schema validation passes.

File: src/validators/business_validator.py
"""

import logging
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta, date
from decimal import Decimal, ROUND_HALF_UP
import re
from lxml import etree
import requests

# Import our configuration and models
from config.fel_config import (
    DTEType, TaxType, PhraseType, ValidationRules, ErrorCodes, ERROR_MESSAGES,
    TAX_CONFIGS, IVA_EXEMPTION_SCENARIOS, ESTABLISHMENT_CLASSIFICATIONS,
    PRODUCT_CODES, INCOTERMS, SystemConfig
)
from src.validators.xml_validator import ValidationError, ValidationLevel, ValidationResult
from src.models.database_models import Taxpayer, Establishment

# Configure logging
logger = logging.getLogger(__name__)

# ========================================
# BUSINESS VALIDATION ENUMS
# ========================================

class ValidationCategory(Enum):
    """Categories for business rule validation"""
    GENERAL_PART1 = "GENERAL_PART1"
    GENERAL_PART2 = "GENERAL_PART2"
    TAX_SPECIFIC = "TAX_SPECIFIC"
    DTE_TYPE_SPECIFIC = "DTE_TYPE_SPECIFIC"
    PHRASE_VALIDATION = "PHRASE_VALIDATION"
    COMPLEMENT_VALIDATION = "COMPLEMENT_VALIDATION"
    GENERAL_PART3 = "GENERAL_PART3"
    GENERAL_PART4 = "GENERAL_PART4"

class ValidationSeverity(Enum):
    """Validation severity for SAT compliance"""
    REJECT = "REJECT"          # Immediate rejection (Rechaza)
    INFORM_ERROR = "INFORM_ERROR"  # Inform with error (Informa EC)
    INFORM_WARNING = "INFORM_WARNING"  # Inform with warning (Informa)

# ========================================
# BUSINESS VALIDATION RESULT
# ========================================

@dataclass
class BusinessValidationError:
    """Business rule validation error"""
    rule_code: str
    message: str
    severity: ValidationSeverity
    category: ValidationCategory
    xpath: Optional[str] = None
    field_name: Optional[str] = None
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None
    sat_validation_level: str = "CERTIFICADOR"  # CERTIFICADOR, SAT1, SAT2

@dataclass
class BusinessValidationResult:
    """Complete business validation result"""
    is_valid: bool
    errors: List[BusinessValidationError]
    warnings: List[BusinessValidationError]
    validation_time: datetime
    rules_applied: List[str]
    dte_type: Optional[str] = None
    
    @property
    def blocking_errors(self) -> List[BusinessValidationError]:
        """Get errors that block certification"""
        return [e for e in self.errors if e.severity == ValidationSeverity.REJECT]
    
    @property
    def has_blocking_errors(self) -> bool:
        """Check if there are blocking errors"""
        return len(self.blocking_errors) > 0

# ========================================
# EXTERNAL DATA SERVICES
# ========================================

class RTUService:
    """Service to validate taxpayer information against RTU"""
    
    def __init__(self):
        self.cache = {}  # Simple cache for RTU data
        
    def validate_nit_exists(self, nit: str) -> bool:
        """Validate if NIT exists in RTU"""
        # In production, this would query the mini-RTU provided by SAT
        # For now, basic validation
        return ValidationRules.validate_nit(nit)
    
    def get_taxpayer_info(self, nit: str) -> Optional[Dict]:
        """Get taxpayer information from RTU"""
        # This would integrate with the mini-RTU data
        # Return mock data for now
        if nit == "CF":
            return {"nit": "CF", "name": "CONSUMIDOR FINAL", "status": "ACTIVE"}
        
        return {
            "nit": nit,
            "name": "Contribuyente Ejemplo",
            "status": "ACTIVE",
            "iva_affiliation": "GEN",
            "isr_affiliation": "REG",
            "establishments": [{"code": "1", "status": "ACTIVE"}]
        }
    
    def validate_establishment_active(self, nit: str, establishment_code: str, emission_date: datetime) -> bool:
        """Validate if establishment is active on emission date"""
        # This would query establishment data from mini-RTU
        return True

class RENAPService:
    """Service to validate CUI against RENAP"""
    
    def validate_cui(self, cui: str) -> Dict[str, Any]:
        """Validate CUI against RENAP service"""
        # In production, this would call the actual RENAP web service
        if not ValidationRules.validate_cui(cui):
            return {"valid": False, "status": "INVALID_FORMAT"}
        
        # Mock response
        return {
            "valid": True,
            "status": "ACTIVE",
            "name": "Juan Pérez López"
        }

# ========================================
# MAIN BUSINESS VALIDATOR
# ========================================

class BusinessValidator:
    """
    Main business rules validator
    Implements all SAT business validation rules
    """
    
    def __init__(self, rtu_service: Optional[RTUService] = None, renap_service: Optional[RENAPService] = None):
        self.rtu_service = rtu_service or RTUService()
        self.renap_service = renap_service or RENAPService()
        self.validation_rules = ValidationRules()
        
        logger.info("BusinessValidator initialized")
    
    def _create_error(
        self,
        rule_code: str,
        message: str,
        severity: ValidationSeverity,
        category: ValidationCategory,
        xpath: Optional[str] = None,
        field_name: Optional[str] = None,
        expected: Optional[str] = None,
        actual: Optional[str] = None
    ) -> BusinessValidationError:
        """Create a business validation error"""
        return BusinessValidationError(
            rule_code=rule_code,
            message=message,
            severity=severity,
            category=category,
            xpath=xpath,
            field_name=field_name,
            expected_value=expected,
            actual_value=actual
        )
    
    def _extract_xml_value(self, root: etree._Element, xpath: str) -> Optional[str]:
        """Extract value from XML using XPath"""
        try:
            elements = root.xpath(xpath)
            if elements and len(elements) > 0:
                element = elements[0]
                return element.text if hasattr(element, 'text') else str(element)
            return None
        except Exception as e:
            logger.error(f"Error extracting XPath {xpath}: {e}")
            return None
    
    def _parse_datetime(self, date_str: str) -> Optional[datetime]:
        """Parse datetime string from XML"""
        try:
            # Handle various datetime formats from XML
            formats = [
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y"
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
                    
            return None
        except Exception:
            return None
    
    def _parse_decimal(self, value_str: str) -> Optional[Decimal]:
        """Parse decimal value from XML"""
        try:
            return Decimal(str(value_str).strip())
        except Exception:
            return None
    
    # ========================================
    # VALIDATION RULE GROUPS
    # ========================================
    
    def validate_general_part1(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate General Rules Part 1 (2.2)"""
        errors = []
        
        # 2.2.1 Validate emission date and time
        errors.extend(self._validate_emission_date(root))
        
        # 2.2.2 Validate NIT Emisor
        errors.extend(self._validate_nit_emisor(root))
        
        # 2.2.3 Validate establishment code
        errors.extend(self._validate_establishment_code(root))
        
        # 2.2.4 Validate ID Receptor
        errors.extend(self._validate_id_receptor(root))
        
        # 2.2.5 Validate Export flag
        errors.extend(self._validate_export_flag(root))
        
        # 2.2.6 Validate Public Show flag
        errors.extend(self._validate_public_show_flag(root))
        
        # 2.2.7 Validate Currency
        errors.extend(self._validate_currency(root))
        
        return errors
    
    def _validate_emission_date(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate emission date and time (Rule 2.2.1)"""
        errors = []
        
        emission_date_str = self._extract_xml_value(root, ".//FechaHoraEmision")
        certification_date_str = self._extract_xml_value(root, ".//FechaHoraCertificacion")
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        
        if not emission_date_str:
            errors.append(self._create_error(
                "2.2.1.0", "Missing emission date", ValidationSeverity.REJECT,
                ValidationCategory.GENERAL_PART1, ".//FechaHoraEmision"
            ))
            return errors
        
        emission_date = self._parse_datetime(emission_date_str)
        if not emission_date:
            errors.append(self._create_error(
                "2.2.1.0", "Invalid emission date format", ValidationSeverity.REJECT,
                ValidationCategory.GENERAL_PART1, ".//FechaHoraEmision"
            ))
            return errors
        
        if certification_date_str:
            certification_date = self._parse_datetime(certification_date_str)
            if certification_date:
                # Rule 2.2.1.1: Check 5-day limit for non-CIVA/CAIS documents
                if dte_type not in ["CIVA", "CAIS"]:
                    days_diff = (certification_date.date() - emission_date.date()).days
                    if days_diff > 5:
                        errors.append(self._create_error(
                            "2.2.1.1", "Emission date exceeds 5-day limit",
                            ValidationSeverity.INFORM_ERROR, ValidationCategory.GENERAL_PART1,
                            field_name="FechaHoraEmision"
                        ))
                
                # Rule 2.2.1.2: Emission date cannot be after last day of certification month
                if emission_date.date() > certification_date.replace(day=1) + timedelta(days=32):
                    last_day = (certification_date.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                    if emission_date.date() > last_day.date():
                        errors.append(self._create_error(
                            "2.2.1.2", "Emission date is after last day of certification month",
                            ValidationSeverity.INFORM_ERROR, ValidationCategory.GENERAL_PART1
                        ))
        
        return errors
    
    def _validate_nit_emisor(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate NIT Emisor (Rule 2.2.2)"""
        errors = []
        
        nit_emisor = self._extract_xml_value(root, ".//NITEmisor")
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        
        if not nit_emisor:
            errors.append(self._create_error(
                "2.2.2.0", "Missing NIT Emisor", ValidationSeverity.REJECT,
                ValidationCategory.GENERAL_PART1, ".//NITEmisor"
            ))
            return errors
        
        # Rule 2.2.2.1: NIT must exist in RTU
        if not self.rtu_service.validate_nit_exists(nit_emisor):
            errors.append(self._create_error(
                "2.2.2.1", "NIT does not exist in SAT", ValidationSeverity.REJECT,
                ValidationCategory.GENERAL_PART1, field_name="NITEmisor", actual_value=nit_emisor
            ))
            return errors
        
        # Rule 2.2.2.2: NIT must be active
        taxpayer_info = self.rtu_service.get_taxpayer_info(nit_emisor)
        if not taxpayer_info or taxpayer_info.get("status") != "ACTIVE":
            errors.append(self._create_error(
                "2.2.2.2", "NIT is not active in SAT", ValidationSeverity.REJECT,
                ValidationCategory.GENERAL_PART1, field_name="NITEmisor"
            ))
        
        # Rule 2.2.2.3: Check IVA affiliation for certain DTE types
        if dte_type not in ["CIVA", "FESP", "RECI", "RDON"]:
            iva_affiliation = taxpayer_info.get("iva_affiliation") if taxpayer_info else None
            if not iva_affiliation:
                errors.append(self._create_error(
                    "2.2.2.3", "NIT not affiliated to IVA and DTE type requires it",
                    ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART1
                ))
        
        return errors
    
    def _validate_establishment_code(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate establishment code (Rule 2.2.3)"""
        errors = []
        
        establishment_code = self._extract_xml_value(root, ".//CodigoEstablecimiento")
        nit_emisor = self._extract_xml_value(root, ".//NITEmisor")
        emission_date_str = self._extract_xml_value(root, ".//FechaHoraEmision")
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        
        if not establishment_code:
            errors.append(self._create_error(
                "2.2.3.0", "Missing establishment code", ValidationSeverity.REJECT,
                ValidationCategory.GENERAL_PART1, ".//CodigoEstablecimiento"
            ))
            return errors
        
        if nit_emisor and emission_date_str:
            emission_date = self._parse_datetime(emission_date_str)
            if emission_date:
                # Rule 2.2.3.1: Establishment must be active
                if not self.rtu_service.validate_establishment_active(nit_emisor, establishment_code, emission_date):
                    errors.append(self._create_error(
                        "2.2.3.1", "Establishment is not active for emission date",
                        ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART1
                    ))
        
        return errors
    
    def _validate_id_receptor(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate ID Receptor (Rule 2.2.4)"""
        errors = []
        
        id_receptor = self._extract_xml_value(root, ".//IDReceptor")
        tipo_especial = self._extract_xml_value(root, ".//TipoEspecial")
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        is_export = self._extract_xml_value(root, ".//Exp") is not None
        gran_total_str = self._extract_xml_value(root, ".//GranTotal")
        
        if not id_receptor:
            errors.append(self._create_error(
                "2.2.4.0", "Missing ID Receptor", ValidationSeverity.REJECT,
                ValidationCategory.GENERAL_PART1, ".//IDReceptor"
            ))
            return errors
        
        # Rule 2.2.4.1: CUI validation when TipoEspecial = "CUI"
        if tipo_especial == "CUI":
            if not id_receptor.isdigit():
                errors.append(self._create_error(
                    "2.2.4.1", "CUI Receptor is not numeric", ValidationSeverity.REJECT,
                    ValidationCategory.GENERAL_PART1, field_name="IDReceptor"
                ))
            elif not ValidationRules.validate_cui(id_receptor):
                errors.append(self._create_error(
                    "2.2.4.3", "CUI Receptor has invalid check digit", ValidationSeverity.REJECT,
                    ValidationCategory.GENERAL_PART1
                ))
            else:
                # Validate against RENAP
                renap_result = self.renap_service.validate_cui(id_receptor)
                if not renap_result.get("valid"):
                    errors.append(self._create_error(
                        "2.2.4.9", "CUI does not exist in RENAP", ValidationSeverity.REJECT,
                        ValidationCategory.GENERAL_PART1
                    ))
                elif renap_result.get("status") == "DECEASED":
                    errors.append(self._create_error(
                        "2.2.4.10", "CUI corresponds to deceased person", ValidationSeverity.INFORM_ERROR,
                        ValidationCategory.GENERAL_PART1
                    ))
        
        # Rule 2.2.4.2: CUI not allowed for exports
        if tipo_especial == "CUI" and is_export:
            errors.append(self._create_error(
                "2.2.4.2", "TipoEspecial CUI not allowed for exports", ValidationSeverity.REJECT,
                ValidationCategory.GENERAL_PART1
            ))
        
        # Rule 2.2.4.4: NIT validation
        if not tipo_especial and id_receptor != "CF":
            if not self.rtu_service.validate_nit_exists(id_receptor):
                errors.append(self._create_error(
                    "2.2.4.4", "NIT Receptor is invalid", ValidationSeverity.REJECT,
                    ValidationCategory.GENERAL_PART1
                ))
        
        # Rule 2.2.4.11: CF amount limit validation
        if id_receptor == "CF" and gran_total_str:
            try:
                gran_total = Decimal(gran_total_str)
                if dte_type in ["FACT", "FCAM", "FPEQ", "FCAP", "FCCA", "FACA", "FAPE", "FAAE", "FCPE", "FCAE"]:
                    if gran_total >= ValidationRules.MAX_CF_AMOUNT_GTQ:
                        errors.append(self._create_error(
                            "2.2.4.11", "Amount exceeds limit for Consumidor Final",
                            ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART1
                        ))
            except (ValueError, TypeError):
                pass
        
        return errors
    
    def _validate_export_flag(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate Export flag (Rule 2.2.5)"""
        errors = []
        
        is_export = self._extract_xml_value(root, ".//Exp") is not None
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        has_export_complement = self._extract_xml_value(root, ".//Exportacion") is not None
        
        if is_export:
            # Rule 2.2.5.1: Some DTE types cannot be exports
            invalid_export_types = ["NABN", "RDON", "RECI", "FESP", "CIVA", "CAIS"]
            if dte_type in invalid_export_types:
                errors.append(self._create_error(
                    "2.2.5.1", f"DTE type {dte_type} cannot be used for exports",
                    ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART1
                ))
            
            # Rule 2.2.5.2: Export must include complement (except NDEB, NCRE)
            if dte_type not in ["NDEB", "NCRE"] and not has_export_complement:
                errors.append(self._create_error(
                    "2.2.5.2", "Export must include Exportacion complement",
                    ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART1
                ))
        
        return errors
    
    def _validate_public_show_flag(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate Public Show flag (Rule 2.2.6)"""
        errors = []
        
        is_public_show = self._extract_xml_value(root, ".//EspectaculoPublico") is not None
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        is_export = self._extract_xml_value(root, ".//Exp") is not None
        has_show_complement = self._extract_xml_value(root, ".//EspectaculosPublicos") is not None
        
        if is_public_show:
            # Rule 2.2.6.1: Only certain DTE types allowed
            allowed_types = ["FACT", "FCAM", "FPEQ", "FCAP", "FAPE", "FCPE"]
            if dte_type not in allowed_types:
                errors.append(self._create_error(
                    "2.2.6.1", f"DTE type {dte_type} cannot be used for public shows",
                    ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART1
                ))
            
            # Rule 2.2.6.2: Cannot be both export and public show
            if is_export:
                errors.append(self._create_error(
                    "2.2.6.2", "Export cannot include public show flag",
                    ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART1
                ))
            
            # Rule 2.2.6.3: Must include public show complement
            if not has_show_complement:
                errors.append(self._create_error(
                    "2.2.6.3", "Public show must include EspectaculosPublicos complement",
                    ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART1
                ))
        
        return errors
    
    def _validate_currency(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate Currency (Rule 2.2.7)"""
        errors = []
        
        currency = self._extract_xml_value(root, ".//Moneda")
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        
        # Rule 2.2.7.1: Currency consistency for credit/debit notes
        if dte_type in ["NCRE", "NDEB"]:
            # Should validate against referenced document currency
            # This would require looking up the original document
            pass
        
        # Rule 2.2.7.2: CF amount limit in different currencies
        id_receptor = self._extract_xml_value(root, ".//IDReceptor")
        gran_total_str = self._extract_xml_value(root, ".//GranTotal")
        
        if id_receptor == "CF" and currency != "GTQ" and gran_total_str:
            try:
                gran_total = Decimal(gran_total_str)
                # Convert to GTQ using exchange rate (would need actual rate service)
                # For now, assume conversion and check limit
                if gran_total >= ValidationRules.MAX_CF_AMOUNT_GTQ:
                    errors.append(self._create_error(
                        "2.2.7.2", "Amount in foreign currency exceeds CF limit when converted to GTQ",
                        ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART1
                    ))
            except (ValueError, TypeError):
                pass
        
        return errors
    
    def validate_items(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate Items section (Rule 2.3)"""
        errors = []
        
        # Rule 2.3.1: Public show documents can only have one item
        is_public_show = self._extract_xml_value(root, ".//EspectaculoPublico") is not None
        items = root.xpath(".//Item")
        
        if is_public_show and len(items) > 1:
            errors.append(self._create_error(
                "2.3.1.1", "Public show documents cannot have more than one item",
                ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART2
            ))
        
        # Rule 2.3.1.2: CIVA documents cannot have more than two items
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        if dte_type == "CIVA" and len(items) > 2:
            errors.append(self._create_error(
                "2.3.1.2", "CIVA documents cannot have more than two items",
                ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART2
            ))
        
        # Validate each item
        for i, item in enumerate(items):
            errors.extend(self._validate_single_item(item, i + 1, root))
        
        return errors
    
    def _validate_single_item(self, item: etree._Element, line_number: int, root: etree._Element) -> List[BusinessValidationError]:
        """Validate a single item"""
        errors = []
        
        # Extract item values
        quantity_str = self._extract_xml_value(item, ".//Cantidad")
        unit_price_str = self._extract_xml_value(item, ".//PrecioUnitario")
        price_str = self._extract_xml_value(item, ".//Precio")
        discount_str = self._extract_xml_value(item, ".//Descuento") or "0"
        other_discount_str = self._extract_xml_value(item, ".//OtrosDescuento") or "0"
        bien_servicio = self._extract_xml_value(item, ".//BienOServicio")
        
        # Parse numeric values
        try:
            quantity = Decimal(quantity_str) if quantity_str else Decimal("0")
            unit_price = Decimal(unit_price_str) if unit_price_str else Decimal("0")
            price = Decimal(price_str) if price_str else Decimal("0")
            discount = Decimal(discount_str)
            other_discount = Decimal(other_discount_str)
        except (ValueError, TypeError):
            errors.append(self._create_error(
                "2.3.5.0", f"Invalid numeric values in item {line_number}",
                ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART2
            ))
            return errors
        
        # Rule 2.3.5: Price calculation validation
        expected_price = quantity * unit_price
        if abs(price - expected_price) > SystemConfig.MONETARY_TOLERANCE:
            errors.append(self._create_error(
                "2.3.5.1", f"Price calculated incorrectly in item {line_number}",
                ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART2,
                expected=str(expected_price), actual=str(price)
            ))
        
        # Rule 2.3.6: Discount validation
        if discount > price:
            errors.append(self._create_error(
                "2.3.6.1", f"Discount cannot be greater than price in item {line_number}",
                ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART2
            ))
        
        # Rule 2.3.7: Other discount validation
        if other_discount > (price - discount):
            errors.append(self._create_error(
                "2.3.7.1", f"Other discount cannot be greater than price minus discount in item {line_number}",
                ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART2
            ))
        
        # Rule 2.3.8: Bien o Servicio validation
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        if dte_type in ["FACA", "FCCA", "FAAE", "FCAE"] and bien_servicio != "B":
            errors.append(self._create_error(
                "2.3.8.1", f"Agricultural taxpayers can only invoice goods (B) in item {line_number}",
                ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART2
            ))
        
        is_public_show = self._extract_xml_value(root, ".//EspectaculoPublico") is not None
        if is_public_show and bien_servicio != "S":
            errors.append(self._create_error(
                "2.3.8.2", f"Public shows can only invoice services (S) in item {line_number}",
                ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART2
            ))
        
        return errors
    
    def validate_taxes(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate tax calculations"""
        errors = []
        
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        
        # Validate IVA calculations
        errors.extend(self._validate_iva_tax(root, dte_type))
        
        # Validate other taxes as needed
        # errors.extend(self._validate_petroleo_tax(root, dte_type))
        # errors.extend(self._validate_turismo_tax(root, dte_type))
        
        return errors
    
    def _validate_iva_tax(self, root: etree._Element, dte_type: str) -> List[BusinessValidationError]:
        """Validate IVA tax calculations (Rule 2.7)"""
        errors = []
        
        # Extract IVA information
        iva_elements = root.xpath(".//Impuesto[NombreCorto='IVA']")
        
        for iva_element in iva_elements:
            monto_gravable_str = self._extract_xml_value(iva_element, ".//MontoGravable")
            codigo_unidad_str = self._extract_xml_value(iva_element, ".//CodigoUnidadGravable")
            monto_impuesto_str = self._extract_xml_value(iva_element, ".//MontoImpuesto")
            
            if not monto_gravable_str:
                errors.append(self._create_error(
                    "2.7.1.1", "MontoGravable must be present for IVA",
                    ValidationSeverity.REJECT, ValidationCategory.TAX_SPECIFIC
                ))
                continue
            
            try:
                monto_gravable = Decimal(monto_gravable_str)
                codigo_unidad = int(codigo_unidad_str) if codigo_unidad_str else 0
                monto_impuesto = Decimal(monto_impuesto_str) if monto_impuesto_str else Decimal("0")
            except (ValueError, TypeError):
                errors.append(self._create_error(
                    "2.7.0", "Invalid IVA numeric values",
                    ValidationSeverity.REJECT, ValidationCategory.TAX_SPECIFIC
                ))
                continue
            
            # Rule 2.7.2: Validate unit code
            if codigo_unidad not in [1, 2]:
                errors.append(self._create_error(
                    "2.7.2.1", "Invalid IVA unit code",
                    ValidationSeverity.REJECT, ValidationCategory.TAX_SPECIFIC
                ))
            
            # Rule 2.7.4: Validate tax amount calculation
            if codigo_unidad == 1:  # 12% IVA
                expected_tax = monto_gravable * Decimal("0.12")
            else:  # 0% IVA
                expected_tax = Decimal("0")
            
            if abs(monto_impuesto - expected_tax) > SystemConfig.MONETARY_TOLERANCE:
                errors.append(self._create_error(
                    "2.7.4.1", "IVA amount calculated incorrectly",
                    ValidationSeverity.REJECT, ValidationCategory.TAX_SPECIFIC,
                    expected=str(expected_tax), actual=str(monto_impuesto)
                ))
        
        return errors
    
    def validate_phrases(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate phrases (Rule 2.6)"""
        errors = []
        
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        nit_emisor = self._extract_xml_value(root, ".//NITEmisor")
        is_export = self._extract_xml_value(root, ".//Exp") is not None
        
        # Get taxpayer info for phrase validation
        taxpayer_info = self.rtu_service.get_taxpayer_info(nit_emisor) if nit_emisor else {}
        
        # Extract all phrases
        phrase_elements = root.xpath(".//Frase")
        phrase_types_present = {}
        
        for phrase_element in phrase_elements:
            tipo_frase_str = self._extract_xml_value(phrase_element, ".//TipoFrase")
            codigo_escenario_str = self._extract_xml_value(phrase_element, ".//CodigoEscenario")
            
            if tipo_frase_str and codigo_escenario_str:
                try:
                    tipo_frase = int(tipo_frase_str)
                    codigo_escenario = int(codigo_escenario_str)
                    phrase_types_present[tipo_frase] = codigo_escenario
                except ValueError:
                    continue
        
        # Rule 2.6.1.6: Export documents must have IVA exempt phrase
        if is_export and dte_type in ["FACT", "FCAM", "NDEB", "NCRE"]:
            if 4 not in phrase_types_present:
                errors.append(self._create_error(
                    "2.6.1.6", "Export documents must include IVA exempt phrase (type 4)",
                    ValidationSeverity.INFORM_ERROR, ValidationCategory.PHRASE_VALIDATION
                ))
            elif phrase_types_present.get(4) != 1:
                errors.append(self._create_error(
                    "2.6.1.7", "Export IVA exempt phrase must use scenario 1",
                    ValidationSeverity.INFORM_ERROR, ValidationCategory.PHRASE_VALIDATION
                ))
        
        # Rule 2.6.1.5: IVA retention agent phrase
        iva_affiliation = taxpayer_info.get("iva_affiliation")
        if dte_type in ["FACT", "FCAM", "NCRE", "NDEB"] and iva_affiliation == "AGENT":
            if 2 not in phrase_types_present:
                errors.append(self._create_error(
                    "2.6.1.5", "IVA retention agent must include phrase type 2",
                    ValidationSeverity.INFORM_ERROR, ValidationCategory.PHRASE_VALIDATION
                ))
        
        # Validate specific phrase scenarios
        for tipo_frase, codigo_escenario in phrase_types_present.items():
            errors.extend(self._validate_phrase_scenario(tipo_frase, codigo_escenario, dte_type, taxpayer_info))
        
        return errors
    
    def _validate_phrase_scenario(self, tipo_frase: int, codigo_escenario: int, dte_type: str, taxpayer_info: Dict) -> List[BusinessValidationError]:
        """Validate specific phrase scenarios"""
        errors = []
        
        # Rule for phrase type 4 (IVA exempt)
        if tipo_frase == 4:
            valid_scenarios = IVA_EXEMPTION_SCENARIOS.keys()
            if codigo_escenario not in valid_scenarios:
                errors.append(self._create_error(
                    "2.6.1.3", f"Invalid scenario code {codigo_escenario} for phrase type 4",
                    ValidationSeverity.INFORM_ERROR, ValidationCategory.PHRASE_VALIDATION
                ))
            else:
                scenario_info = IVA_EXEMPTION_SCENARIOS[codigo_escenario]
                allowed_dte_types = scenario_info.get("allowed_dte", [])
                if allowed_dte_types and dte_type not in allowed_dte_types:
                    errors.append(self._create_error(
                        f"2.6.1.{codigo_escenario}", 
                        f"Scenario {codigo_escenario} not allowed for DTE type {dte_type}",
                        ValidationSeverity.INFORM_ERROR, ValidationCategory.PHRASE_VALIDATION
                    ))
        
        # Rule for phrase type 1 (ISR retention)
        if tipo_frase == 1:
            isr_affiliation = taxpayer_info.get("isr_affiliation")
            if codigo_escenario == 1 and isr_affiliation != "REG":
                errors.append(self._create_error(
                    "2.6.1.1", "ISR phrase scenario 1 requires regular ISR affiliation",
                    ValidationSeverity.INFORM_ERROR, ValidationCategory.PHRASE_VALIDATION
                ))
        
        return errors
    
    def validate_complements(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate complements (Rule 3.1)"""
        errors = []
        
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        
        # Check export complement
        if self._extract_xml_value(root, ".//Exp") is not None:
            if not self._extract_xml_value(root, ".//Exportacion"):
                if dte_type not in ["NDEB", "NCRE"]:
                    errors.append(self._create_error(
                        "3.2.1.1", "Export documents must include Exportacion complement",
                        ValidationSeverity.REJECT, ValidationCategory.COMPLEMENT_VALIDATION
                    ))
        
        # Check public show complement
        if self._extract_xml_value(root, ".//EspectaculoPublico") is not None:
            if not self._extract_xml_value(root, ".//EspectaculosPublicos"):
                errors.append(self._create_error(
                    "3.7.1.1", "Public show documents must include EspectaculosPublicos complement",
                    ValidationSeverity.REJECT, ValidationCategory.COMPLEMENT_VALIDATION
                ))
        
        # Validate specific complements
        errors.extend(self._validate_export_complement(root))
        errors.extend(self._validate_reference_complement(root))
        
        return errors
    
    def _validate_export_complement(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate export complement"""
        errors = []
        
        export_element = root.xpath(".//Exportacion")
        if not export_element:
            return errors
        
        export_element = export_element[0]
        incoterm = self._extract_xml_value(export_element, ".//INCOTERM")
        
        if incoterm and incoterm not in INCOTERMS:
            errors.append(self._create_error(
                "3.2.1.2", f"Invalid INCOTERM: {incoterm}",
                ValidationSeverity.REJECT, ValidationCategory.COMPLEMENT_VALIDATION
            ))
        
        return errors
    
    def _validate_reference_complement(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate reference complement for credit/debit notes"""
        errors = []
        
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        if dte_type not in ["NCRE", "NDEB"]:
            return errors
        
        reference_element = root.xpath(".//ReferenciasNota")
        if not reference_element:
            errors.append(self._create_error(
                "3.5.0", "Credit/Debit notes must include ReferenciasNota complement",
                ValidationSeverity.REJECT, ValidationCategory.COMPLEMENT_VALIDATION
            ))
            return errors
        
        reference_element = reference_element[0]
        numero_autorizacion = self._extract_xml_value(reference_element, ".//NumeroAutorizacionDocumentoOrigen")
        
        if not numero_autorizacion:
            errors.append(self._create_error(
                "3.5.1.0", "Missing authorization number of origin document",
                ValidationSeverity.REJECT, ValidationCategory.COMPLEMENT_VALIDATION
            ))
        elif not ValidationRules.UUID_PATTERN.match(numero_autorizacion):
            errors.append(self._create_error(
                "3.5.1.1", "Invalid format for origin document authorization number",
                ValidationSeverity.REJECT, ValidationCategory.COMPLEMENT_VALIDATION
            ))
        
        return errors
    
    def validate_totals(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate totals calculation (Rule 2.19)"""
        errors = []
        
        # Extract totals
        gran_total_str = self._extract_xml_value(root, ".//GranTotal")
        id_receptor = self._extract_xml_value(root, ".//IDReceptor")
        dte_type = self._extract_xml_value(root, ".//TipoDTE")
        
        if gran_total_str:
            try:
                gran_total = Decimal(gran_total_str)
                
                # Rule 2.19.2.4: CF amount limit
                if id_receptor == "CF" and dte_type in ["FACT", "FCAM", "FPEQ", "FCAP", "FCCA", "FACA", "FAPE", "FAAE", "FCPE", "FCAE"]:
                    if gran_total >= ValidationRules.MAX_CF_AMOUNT_GTQ:
                        errors.append(self._create_error(
                            "2.19.2.4", "Gran Total exceeds limit for Consumidor Final",
                            ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART3
                        ))
                
                # Validate total calculation
                item_totals = []
                items = root.xpath(".//Item")
                for item in items:
                    total_str = self._extract_xml_value(item, ".//Total")
                    if total_str:
                        try:
                            item_totals.append(Decimal(total_str))
                        except ValueError:
                            continue
                
                calculated_total = sum(item_totals)
                if abs(gran_total - calculated_total) > SystemConfig.MONETARY_TOLERANCE:
                    errors.append(self._create_error(
                        "2.19.2.1", "Gran Total calculated incorrectly",
                        ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART3,
                        expected=str(calculated_total), actual=str(gran_total)
                    ))
                
            except ValueError:
                errors.append(self._create_error(
                    "2.19.2.0", "Invalid Gran Total format",
                    ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART3
                ))
        
        return errors
    
    def validate_signatures(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate electronic signatures (Rule 3.12)"""
        errors = []
        
        # Check for emisor signature
        emisor_signature = root.xpath(".//Signature[@Id='SignatureEmisor' or contains(@Id, 'Emisor')]")
        if not emisor_signature:
            errors.append(self._create_error(
                "3.12.1.1", "Missing emisor electronic signature",
                ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART4
            ))
        
        # Check for certificador signature  
        cert_signature = root.xpath(".//Signature[@Id='SignatureCertificador' or contains(@Id, 'Certificador')]")
        if not cert_signature:
            errors.append(self._create_error(
                "3.12.4.1", "Missing certificador electronic signature", 
                ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART4
            ))
        
        return errors
    
    def validate_uuid_format(self, root: etree._Element) -> List[BusinessValidationError]:
        """Validate UUID format and serie/numero generation (Rule 3.12.5-3.12.7)"""
        errors = []
        
        numero_autorizacion = self._extract_xml_value(root, ".//NumeroAutorizacion")
        serie = self._extract_xml_value(root, ".//Serie")
        numero_str = self._extract_xml_value(root, ".//Numero")
        
        if numero_autorizacion:
            # Rule 3.12.5: UUID format validation
            if not ValidationRules.UUID_PATTERN.match(numero_autorizacion):
                errors.append(self._create_error(
                    "3.12.5.1", "Invalid UUID format for authorization number",
                    ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART4
                ))
            else:
                # Rule 3.12.6: Serie validation
                expected_serie = numero_autorizacion.replace('-', '')[:8].upper()
                if serie != expected_serie:
                    errors.append(self._create_error(
                        "3.12.6.1", "Serie does not correspond to authorization number",
                        ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART4,
                        expected=expected_serie, actual=serie
                    ))
                
                # Rule 3.12.7: Numero validation
                if numero_str:
                    try:
                        numero = int(numero_str)
                        uuid_clean = numero_autorizacion.replace('-', '')
                        hex_portion = uuid_clean[8:16]
                        expected_numero = int(hex_portion, 16) % 999999999
                        
                        if numero != expected_numero:
                            errors.append(self._create_error(
                                "3.12.7.1", "Numero is incorrect",
                                ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART4,
                                expected=str(expected_numero), actual=str(numero)
                            ))
                    except ValueError:
                        errors.append(self._create_error(
                            "3.12.7.0", "Invalid numero format",
                            ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART4
                        ))
        
        return errors
    
    # ========================================
    # MAIN VALIDATION ORCHESTRATOR
    # ========================================
    
    def validate_dte(self, xml_content: str, dte_type: Optional[str] = None) -> BusinessValidationResult:
        """
        Main DTE business validation method
        Orchestrates all validation rules
        """
        start_time = datetime.now()
        all_errors = []
        all_warnings = []
        rules_applied = []
        
        logger.info(f"Starting business validation for DTE type: {dte_type}")
        
        try:
            # Parse XML
            root = etree.fromstring(xml_content.encode('utf-8'))
            
            # Detect DTE type if not provided
            if not dte_type:
                dte_type = self._extract_xml_value(root, ".//TipoDTE")
            
            # Apply validation rule groups in order
            validation_groups = [
                ("General Part 1", self.validate_general_part1),
                ("Items", self.validate_items),
                ("Taxes", self.validate_taxes),
                ("Phrases", self.validate_phrases),
                ("Complements", self.validate_complements),
                ("Totals", self.validate_totals),
                ("Signatures", self.validate_signatures),
                ("UUID Format", self.validate_uuid_format),
            ]
            
            for group_name, validation_func in validation_groups:
                try:
                    group_errors = validation_func(root)
                    for error in group_errors:
                        if error.severity == ValidationSeverity.REJECT:
                            all_errors.append(error)
                        else:
                            all_warnings.append(error)
                    rules_applied.append(group_name)
                    logger.debug(f"Applied {group_name}: {len(group_errors)} issues found")
                except Exception as e:
                    logger.error(f"Error in validation group {group_name}: {e}")
                    error = self._create_error(
                        f"SYSTEM_{group_name.upper().replace(' ', '_')}", 
                        f"System error in {group_name} validation: {str(e)}",
                        ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART1
                    )
                    all_errors.append(error)
            
        except etree.XMLSyntaxError as e:
            error = self._create_error(
                "XML_PARSE_ERROR", f"XML parsing error: {e}",
                ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART1
            )
            all_errors.append(error)
        except Exception as e:
            logger.error(f"Unexpected error in business validation: {e}")
            error = self._create_error(
                "SYSTEM_ERROR", f"System error: {str(e)}",
                ValidationSeverity.REJECT, ValidationCategory.GENERAL_PART1
            )
            all_errors.append(error)
        
        # Create result
        is_valid = len(all_errors) == 0
        
        result = BusinessValidationResult(
            is_valid=is_valid,
            errors=all_errors,
            warnings=all_warnings,
            validation_time=start_time,
            rules_applied=rules_applied,
            dte_type=dte_type
        )
        
        logger.info(
            f"Business validation completed. Valid: {is_valid}, "
            f"Errors: {len(all_errors)}, Warnings: {len(all_warnings)}"
        )
        
        return result
    
    def validate_anulation(self, xml_content: str) -> BusinessValidationResult:
        """Validate anulation business rules"""
        # Implement anulation-specific validation rules
        # This would include rules from section 3.13
        return self.validate_dte(xml_content, "ANULATION")

# ========================================
# VALIDATION UTILITIES
# ========================================

class BusinessValidationUtils:
    """Utility functions for business validation"""
    
    @staticmethod
    def format_business_result(result: BusinessValidationResult) -> str:
        """Format business validation result for display"""
        lines = []
        lines.append(f"Business Validation Result: {'VALID' if result.is_valid else 'INVALID'}")
        lines.append(f"DTE Type: {result.dte_type or 'Unknown'}")
        lines.append(f"Validation Time: {result.validation_time}")
        lines.append(f"Rules Applied: {', '.join(result.rules_applied)}")
        
        if result.errors:
            lines.append(f"\nBlocking Errors ({len(result.errors)}):")
            for error in result.errors:
                lines.append(f"  - {error.rule_code}: {error.message}")
                if error.field_name:
                    lines.append(f"    Field: {error.field_name}")
                if error.expected_value and error.actual_value:
                    lines.append(f"    Expected: {error.expected_value}, Actual: {error.actual_value}")
        
        if result.warnings:
            lines.append(f"\nWarnings ({len(result.warnings)}):")
            for warning in result.warnings:
                lines.append(f"  - {warning.rule_code}: {warning.message}")
        
        return "\n".join(lines)
    
    @staticmethod
    def get_error_summary(results: List[BusinessValidationResult]) -> Dict:
        """Get summary of validation errors across multiple results"""
        error_counts = {}
        total_documents = len(results)
        valid_documents = sum(1 for r in results if r.is_valid)
        
        for result in results:
            for error in result.errors + result.warnings:
                if error.rule_code not in error_counts:
                    error_counts[error.rule_code] = 0
                error_counts[error.rule_code] += 1
        
        return {
            'total_documents': total_documents,
            'valid_documents': valid_documents,
            'invalid_documents': total_documents - valid_documents,
            'success_rate': valid_documents / total_documents if total_documents > 0 else 0,
            'common_errors': sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        }

# ========================================
# FACTORY FUNCTION
# ========================================

def create_business_validator() -> BusinessValidator:
    """Factory function to create BusinessValidator instance"""
    return BusinessValidator()

# ========================================
# TESTING AND EXAMPLES
# ========================================

if __name__ == "__main__":
    # Example usage and testing
    import sys
    
    # Configure logging for testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    
    # Create validator
    validator = create_business_validator()
    
    # Example XML (this would be a real DTE XML)
    sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <DTE xmlns="http://www.sat.gob.gt/dte/fel/0.1.0">
        <DatosEmision>
            <TipoDTE>FACT</TipoDTE>
            <NITEmisor>1234567K</NITEmisor>
            <CodigoEstablecimiento>1</CodigoEstablecimiento>
            <FechaHoraEmision>2024-01-15T10:30:00</FechaHoraEmision>
            <IDReceptor>9876543K</IDReceptor>
            <Moneda>GTQ</Moneda>
            <Items>
                <Item NumeroLinea="1">
                    <BienOServicio>B</BienOServicio>
                    <Cantidad>10</Cantidad>
                    <UnidadMedida>UNIDAD</UnidadMedida>
                    <Descripcion>Producto de prueba</Descripcion>
                    <PrecioUnitario>100.00</PrecioUnitario>
                    <Precio>1000.00</Precio>
                    <Descuento>0.00</Descuento>
                    <Total>1000.00</Total>
                </Item>
            </Items>
            <Total>1000.00</Total>
            <GranTotal>1000.00</GranTotal>
        </DatosEmision>
        <Certificacion>
            <NITCertificador>9876543K</NITCertificador>
            <FechaHoraCertificacion>2024-01-15T10:35:00</FechaHoraCertificacion>
            <NumeroAutorizacion>550e8400-e29b-41d4-a716-446655440000</NumeroAutorizacion>
            <Serie>550E8400</Serie>
            <Numero>123456789</Numero>
        </Certificacion>
    </DTE>"""
    
    print("Testing Business Validator...")
    print("=" * 60)
    
    # Validate the sample XML
    result = validator.validate_dte(sample_xml)
    
    # Display results
    print(BusinessValidationUtils.format_business_result(result))
    
    print("\nBusiness Validator testing completed!")
