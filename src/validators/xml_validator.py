"""
FEL XML Schema Validator
Validates DTE XML documents against official SAT XSD schemas

This validator ensures all incoming DTEs comply with the official
SAT schema definitions before business rule validation.

File: src/validators/xml_validator.py
"""

import os
import logging
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
import requests
from lxml import etree
from lxml.etree import XMLSyntaxError, DocumentInvalid
import xmlschema
from xmlschema import XMLSchema, XMLSchemaException
from datetime import datetime, timedelta
import hashlib
import json

# Import our configuration
from config.fel_config import SystemConfig, DTEType, ComplementType, ErrorCodes, ERROR_MESSAGES

# Configure logging
logger = logging.getLogger(__name__)

# ========================================
# VALIDATION RESULT CLASSES
# ========================================

class ValidationLevel(Enum):
    """Validation severity levels"""
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"

@dataclass
class ValidationError:
    """Individual validation error"""
    code: str
    message: str
    level: ValidationLevel
    xpath: Optional[str] = None
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None
    line_number: Optional[int] = None
    column_number: Optional[int] = None

@dataclass
class ValidationResult:
    """Complete validation result"""
    is_valid: bool
    errors: List[ValidationError]
    warnings: List[ValidationError]
    schema_used: str
    validation_time: datetime
    document_type: Optional[str] = None
    
    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0
    
    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0
    
    @property
    def error_count(self) -> int:
        return len(self.errors)
    
    @property
    def warning_count(self) -> int:
        return len(self.warnings)

# ========================================
# SCHEMA MANAGER
# ========================================

class SchemaManager:
    """
    Manages XSD schema files and caching
    Downloads and caches official SAT schemas
    """
    
    def __init__(self, cache_dir: str = "./schemas", cache_duration_hours: int = 24):
        self.cache_dir = cache_dir
        self.cache_duration = timedelta(hours=cache_duration_hours)
        self.schemas: Dict[str, XMLSchema] = {}
        self.schema_files: Dict[str, str] = {}
        
        # Ensure cache directory exists
        os.makedirs(self.cache_dir, exist_ok=True)
        
        logger.info(f"SchemaManager initialized with cache directory: {self.cache_dir}")
    
    def _get_cache_path(self, schema_name: str) -> str:
        """Get the local cache path for a schema file"""
        return os.path.join(self.cache_dir, f"{schema_name}")
    
    def _get_cache_info_path(self, schema_name: str) -> str:
        """Get the cache info file path"""
        return os.path.join(self.cache_dir, f"{schema_name}.info")
    
    def _is_cache_valid(self, schema_name: str) -> bool:
        """Check if cached schema is still valid"""
        cache_info_path = self._get_cache_info_path(schema_name)
        
        if not os.path.exists(cache_info_path):
            return False
        
        try:
            with open(cache_info_path, 'r') as f:
                cache_info = json.load(f)
            
            cached_time = datetime.fromisoformat(cache_info['cached_at'])
            return datetime.now() - cached_time < self.cache_duration
        except (json.JSONDecodeError, KeyError, ValueError):
            return False
    
    def _download_schema(self, schema_name: str, url: str) -> bool:
        """Download schema file from SAT servers"""
        try:
            logger.info(f"Downloading schema: {schema_name} from {url}")
            
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            # Save schema file
            cache_path = self._get_cache_path(schema_name)
            with open(cache_path, 'wb') as f:
                f.write(response.content)
            
            # Save cache info
            cache_info = {
                'cached_at': datetime.now().isoformat(),
                'url': url,
                'size': len(response.content),
                'hash': hashlib.md5(response.content).hexdigest()
            }
            
            cache_info_path = self._get_cache_info_path(schema_name)
            with open(cache_info_path, 'w') as f:
                json.dump(cache_info, f)
            
            logger.info(f"Schema cached successfully: {schema_name}")
            return True
            
        except requests.RequestException as e:
            logger.error(f"Failed to download schema {schema_name}: {e}")
            return False
        except IOError as e:
            logger.error(f"Failed to save schema {schema_name}: {e}")
            return False
    
    def load_schema(self, schema_name: str, force_download: bool = False) -> Optional[XMLSchema]:
        """Load and parse XSD schema"""
        if schema_name in self.schemas and not force_download:
            return self.schemas[schema_name]
        
        cache_path = self._get_cache_path(schema_name)
        
        # Check if we need to download
        if force_download or not os.path.exists(cache_path) or not self._is_cache_valid(schema_name):
            schema_url = f"{SystemConfig.XSD_BASE_URL}{SystemConfig.XSD_SCHEMAS.get(schema_name, schema_name)}"
            if not self._download_schema(schema_name, schema_url):
                logger.error(f"Could not download schema: {schema_name}")
                return None
        
        # Load and parse schema
        try:
            logger.info(f"Loading schema: {schema_name}")
            schema = XMLSchema(cache_path)
            self.schemas[schema_name] = schema
            self.schema_files[schema_name] = cache_path
            
            logger.info(f"Schema loaded successfully: {schema_name}")
            return schema
            
        except XMLSchemaException as e:
            logger.error(f"Failed to parse schema {schema_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error loading schema {schema_name}: {e}")
            return None
    
    def get_schema_for_dte_type(self, dte_type: str) -> Optional[str]:
        """Get the appropriate schema name for a DTE type"""
        # Main document schema applies to all DTE types
        return 'GT_DOCUMENTO'
    
    def load_all_schemas(self) -> Dict[str, XMLSchema]:
        """Load all available schemas"""
        loaded_schemas = {}
        
        for schema_name in SystemConfig.XSD_SCHEMAS.keys():
            schema = self.load_schema(schema_name)
            if schema:
                loaded_schemas[schema_name] = schema
        
        logger.info(f"Loaded {len(loaded_schemas)} schemas")
        return loaded_schemas

# ========================================
# XML VALIDATOR
# ========================================

class XMLValidator:
    """
    Main XML validator for DTE documents
    Validates against XSD schemas and performs basic XML validation
    """
    
    def __init__(self, schema_manager: Optional[SchemaManager] = None):
        self.schema_manager = schema_manager or SchemaManager()
        self.validation_cache: Dict[str, ValidationResult] = {}
        
        logger.info("XMLValidator initialized")
    
    def _create_validation_error(
        self, 
        code: str, 
        message: str, 
        level: ValidationLevel = ValidationLevel.ERROR,
        xpath: Optional[str] = None,
        expected: Optional[str] = None,
        actual: Optional[str] = None,
        line: Optional[int] = None,
        column: Optional[int] = None
    ) -> ValidationError:
        """Create a validation error object"""
        return ValidationError(
            code=code,
            message=message,
            level=level,
            xpath=xpath,
            expected_value=expected,
            actual_value=actual,
            line_number=line,
            column_number=column
        )
    
    def _parse_xml(self, xml_content: str) -> Tuple[Optional[etree._Element], List[ValidationError]]:
        """Parse XML content and return element tree"""
        errors = []
        
        try:
            # Parse XML with validation
            parser = etree.XMLParser(strip_whitespace=False, recover=False)
            root = etree.fromstring(xml_content.encode('utf-8'), parser)
            return root, errors
            
        except XMLSyntaxError as e:
            error = self._create_validation_error(
                code=ErrorCodes.INVALID_XML_FORMAT,
                message=f"XML Syntax Error: {e.msg}",
                level=ValidationLevel.ERROR,
                line=e.lineno,
                column=e.offset
            )
            errors.append(error)
            return None, errors
            
        except Exception as e:
            error = self._create_validation_error(
                code=ErrorCodes.INVALID_XML_FORMAT,
                message=f"XML Parsing Error: {str(e)}",
                level=ValidationLevel.ERROR
            )
            errors.append(error)
            return None, errors
    
    def _detect_document_type(self, root: etree._Element) -> Optional[str]:
        """Detect the DTE type from XML content"""
        try:
            # Look for the DTE type in the XML structure
            # This depends on the actual XSD structure from SAT
            
            # Try to find DTE type in common locations
            dte_type_element = root.find('.//TipoDTE')
            if dte_type_element is not None and dte_type_element.text:
                return dte_type_element.text.strip()
            
            # Alternative: Check root element or other common patterns
            # This would need to be adjusted based on actual SAT XSD structure
            if 'DTE' in root.tag:
                # Extract from attributes or child elements
                pass
            
            logger.warning("Could not detect DTE type from XML structure")
            return None
            
        except Exception as e:
            logger.error(f"Error detecting document type: {e}")
            return None
    
    def _validate_against_schema(
        self, 
        root: etree._Element, 
        schema: XMLSchema
    ) -> List[ValidationError]:
        """Validate XML element against XSD schema"""
        errors = []
        
        try:
            # Validate using xmlschema library
            schema.validate(root)
            logger.debug("Schema validation passed")
            
        except xmlschema.XMLSchemaException as e:
            # Convert xmlschema errors to our format
            error = self._create_validation_error(
                code=ErrorCodes.SCHEMA_VALIDATION_ERROR,
                message=f"Schema validation failed: {str(e)}",
                level=ValidationLevel.ERROR,
                xpath=getattr(e, 'path', None)
            )
            errors.append(error)
            
        except Exception as e:
            error = self._create_validation_error(
                code=ErrorCodes.SCHEMA_VALIDATION_ERROR,
                message=f"Unexpected schema validation error: {str(e)}",
                level=ValidationLevel.ERROR
            )
            errors.append(error)
        
        return errors
    
    def _validate_basic_structure(self, root: etree._Element) -> List[ValidationError]:
        """Perform basic structural validation"""
        errors = []
        
        # Check for required namespaces
        nsmap = root.nsmap
        if None not in nsmap and not any('fel' in uri.lower() for uri in nsmap.values()):
            error = self._create_validation_error(
                code="MISSING_NAMESPACE",
                message="Missing required FEL namespace",
                level=ValidationLevel.WARNING
            )
            errors.append(error)
        
        # Check for minimum required elements
        required_elements = ['DatosEmision', 'Certificacion']  # Adjust based on actual XSD
        for element_name in required_elements:
            if root.find(f'.//{element_name}') is None:
                error = self._create_validation_error(
                    code="MISSING_REQUIRED_ELEMENT",
                    message=f"Missing required element: {element_name}",
                    level=ValidationLevel.ERROR,
                    xpath=f"//{element_name}"
                )
                errors.append(error)
        
        return errors
    
    def _validate_encoding(self, xml_content: str) -> List[ValidationError]:
        """Validate XML encoding and character set"""
        errors = []
        
        # Check encoding declaration
        if '<?xml' in xml_content[:100]:
            if 'encoding=' not in xml_content[:200]:
                error = self._create_validation_error(
                    code="MISSING_ENCODING",
                    message="XML encoding declaration recommended",
                    level=ValidationLevel.WARNING
                )
                errors.append(error)
        
        # Check for invalid characters
        try:
            xml_content.encode('utf-8')
        except UnicodeEncodeError as e:
            error = self._create_validation_error(
                code="INVALID_ENCODING",
                message=f"Invalid character encoding: {str(e)}",
                level=ValidationLevel.ERROR
            )
            errors.append(error)
        
        return errors
    
    def validate_xml(
        self, 
        xml_content: str, 
        schema_name: Optional[str] = None,
        dte_type: Optional[str] = None
    ) -> ValidationResult:
        """
        Main validation method
        Validates XML content against appropriate XSD schema
        """
        start_time = datetime.now()
        all_errors = []
        all_warnings = []
        schema_used = "unknown"
        detected_dte_type = dte_type
        
        logger.info(f"Starting XML validation for DTE type: {dte_type}")
        
        # Step 1: Validate encoding
        encoding_errors = self._validate_encoding(xml_content)
        for error in encoding_errors:
            if error.level == ValidationLevel.ERROR:
                all_errors.append(error)
            else:
                all_warnings.append(error)
        
        # Step 2: Parse XML
        root, parse_errors = self._parse_xml(xml_content)
        all_errors.extend(parse_errors)
        
        if root is None:
            # Cannot continue validation without parsed XML
            return ValidationResult(
                is_valid=False,
                errors=all_errors,
                warnings=all_warnings,
                schema_used=schema_used,
                validation_time=start_time,
                document_type=detected_dte_type
            )
        
        # Step 3: Detect document type if not provided
        if not detected_dte_type:
            detected_dte_type = self._detect_document_type(root)
        
        # Step 4: Basic structure validation
        structure_errors = self._validate_basic_structure(root)
        for error in structure_errors:
            if error.level == ValidationLevel.ERROR:
                all_errors.append(error)
            else:
                all_warnings.append(error)
        
        # Step 5: Schema validation
        if not schema_name:
            schema_name = self.schema_manager.get_schema_for_dte_type(detected_dte_type or "")
        
        if schema_name:
            schema = self.schema_manager.load_schema(schema_name)
            if schema:
                schema_used = schema_name
                schema_errors = self._validate_against_schema(root, schema)
                all_errors.extend(schema_errors)
            else:
                error = self._create_validation_error(
                    code="SCHEMA_LOAD_ERROR",
                    message=f"Could not load schema: {schema_name}",
                    level=ValidationLevel.ERROR
                )
                all_errors.append(error)
        else:
            error = self._create_validation_error(
                code="NO_SCHEMA_FOUND",
                message="No appropriate schema found for validation",
                level=ValidationLevel.WARNING
            )
            all_warnings.append(error)
        
        # Create final result
        is_valid = len(all_errors) == 0
        
        result = ValidationResult(
            is_valid=is_valid,
            errors=all_errors,
            warnings=all_warnings,
            schema_used=schema_used,
            validation_time=start_time,
            document_type=detected_dte_type
        )
        
        logger.info(
            f"XML validation completed. Valid: {is_valid}, "
            f"Errors: {len(all_errors)}, Warnings: {len(all_warnings)}"
        )
        
        return result
    
    def validate_anulation_xml(self, xml_content: str) -> ValidationResult:
        """Validate anulation XML against anulation schema"""
        return self.validate_xml(xml_content, schema_name='GT_ANULACION_DOCUMENTO')
    
    def batch_validate(
        self, 
        xml_documents: List[str], 
        dte_types: Optional[List[str]] = None
    ) -> List[ValidationResult]:
        """Validate multiple XML documents"""
        results = []
        
        for i, xml_content in enumerate(xml_documents):
            dte_type = dte_types[i] if dte_types and i < len(dte_types) else None
            result = self.validate_xml(xml_content, dte_type=dte_type)
            results.append(result)
        
        return results
    
    def get_validation_summary(self, results: List[ValidationResult]) -> Dict:
        """Get summary statistics for multiple validation results"""
        total_documents = len(results)
        valid_documents = sum(1 for r in results if r.is_valid)
        total_errors = sum(len(r.errors) for r in results)
        total_warnings = sum(len(r.warnings) for r in results)
        
        return {
            'total_documents': total_documents,
            'valid_documents': valid_documents,
            'invalid_documents': total_documents - valid_documents,
            'success_rate': valid_documents / total_documents if total_documents > 0 else 0,
            'total_errors': total_errors,
            'total_warnings': total_warnings,
            'average_errors_per_document': total_errors / total_documents if total_documents > 0 else 0
        }

# ========================================
# VALIDATION UTILITIES
# ========================================

class ValidationUtils:
    """Utility functions for XML validation"""
    
    @staticmethod
    def format_validation_result(result: ValidationResult) -> str:
        """Format validation result for display"""
        lines = []
        lines.append(f"Validation Result: {'VALID' if result.is_valid else 'INVALID'}")
        lines.append(f"Document Type: {result.document_type or 'Unknown'}")
        lines.append(f"Schema Used: {result.schema_used}")
        lines.append(f"Validation Time: {result.validation_time}")
        
        if result.errors:
            lines.append(f"\nErrors ({len(result.errors)}):")
            for error in result.errors:
                lines.append(f"  - {error.code}: {error.message}")
                if error.xpath:
                    lines.append(f"    XPath: {error.xpath}")
        
        if result.warnings:
            lines.append(f"\nWarnings ({len(result.warnings)}):")
            for warning in result.warnings:
                lines.append(f"  - {warning.code}: {warning.message}")
                if warning.xpath:
                    lines.append(f"    XPath: {warning.xpath}")
        
        return "\n".join(lines)
    
    @staticmethod
    def export_validation_result_json(result: ValidationResult) -> str:
        """Export validation result as JSON"""
        data = {
            'is_valid': result.is_valid,
            'document_type': result.document_type,
            'schema_used': result.schema_used,
            'validation_time': result.validation_time.isoformat(),
            'errors': [
                {
                    'code': error.code,
                    'message': error.message,
                    'level': error.level.value,
                    'xpath': error.xpath,
                    'expected_value': error.expected_value,
                    'actual_value': error.actual_value,
                    'line_number': error.line_number,
                    'column_number': error.column_number
                }
                for error in result.errors
            ],
            'warnings': [
                {
                    'code': warning.code,
                    'message': warning.message,
                    'level': warning.level.value,
                    'xpath': warning.xpath,
                    'expected_value': warning.expected_value,
                    'actual_value': warning.actual_value,
                    'line_number': warning.line_number,
                    'column_number': warning.column_number
                }
                for warning in result.warnings
            ]
        }
        
        return json.dumps(data, indent=2, ensure_ascii=False)

# ========================================
# MAIN VALIDATOR FACTORY
# ========================================

def create_xml_validator(cache_dir: Optional[str] = None) -> XMLValidator:
    """Factory function to create XMLValidator instance"""
    schema_manager = SchemaManager(cache_dir=cache_dir or "./schemas")
    return XMLValidator(schema_manager=schema_manager)

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
    validator = create_xml_validator("./test_schemas")
    
    # Example XML (this would be a real DTE XML)
    sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <DTE xmlns="http://www.sat.gob.gt/dte/fel/0.1.0">
        <DatosEmision>
            <TipoDTE>FACT</TipoDTE>
            <NITEmisor>1234567K</NITEmisor>
            <FechaEmision>2024-01-15T10:30:00</FechaEmision>
        </DatosEmision>
        <Certificacion>
            <NITCertificador>9876543K</NITCertificador>
        </Certificacion>
    </DTE>"""
    
    print("Testing XML Validator...")
    print("=" * 50)
    
    # Validate the sample XML
    result = validator.validate_xml(sample_xml, dte_type="FACT")
    
    # Display results
    print(ValidationUtils.format_validation_result(result))
    
    # Test schema loading
    print("\n" + "=" * 50)
    print("Testing Schema Manager...")
    
    schema_manager = SchemaManager("./test_schemas")
    schemas = schema_manager.load_all_schemas()
    print(f"Loaded {len(schemas)} schemas")
    
    for name in schemas.keys():
        print(f"  - {name}")
    
    print("\nXML Validator testing completed!")
