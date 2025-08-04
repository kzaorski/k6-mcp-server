import csv
import json
import os
import random
import string
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)


class DataGenerator:
    """Utility class for generating dynamic test data."""
    
    @staticmethod
    def generate_random_string(length: int = 10) -> str:
        """Generate a random string of specified length."""
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))
    
    @staticmethod
    def generate_random_number(min_val: int = 1, max_val: int = 1000) -> int:
        """Generate a random number within specified range."""
        return random.randint(min_val, max_val)
    
    @staticmethod
    def generate_timestamp(format_str: str = "%Y-%m-%dT%H:%M:%SZ") -> str:
        """Generate current timestamp in specified format."""
        return datetime.now().strftime(format_str)
    
    @staticmethod
    def generate_uuid() -> str:
        """Generate a UUID4 string."""
        return str(uuid.uuid4())
    
    @staticmethod
    def generate_email(domain: str = "example.com") -> str:
        """Generate a random email address."""
        username = DataGenerator.generate_random_string(8).lower()
        return f"{username}@{domain}"
    
    @staticmethod
    def load_from_csv(file_path: str) -> List[Dict[str, Any]]:
        """Load data from CSV file."""
        data = []
        try:
            with open(file_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                data = list(reader)
            logger.info(f"Loaded {len(data)} records from CSV: {file_path}")
        except Exception as e:
            logger.error(f"Error loading CSV file {file_path}: {str(e)}")
        return data
    
    @staticmethod
    def load_from_json(file_path: str) -> List[Dict[str, Any]]:
        """Load data from JSON file."""
        data = []
        try:
            with open(file_path, 'r', encoding='utf-8') as jsonfile:
                loaded_data = json.load(jsonfile)
                # Handle both array and single object
                if isinstance(loaded_data, list):
                    data = loaded_data
                else:
                    data = [loaded_data]
            logger.info(f"Loaded {len(data)} records from JSON: {file_path}")
        except Exception as e:
            logger.error(f"Error loading JSON file {file_path}: {str(e)}")
        return data
    
    @staticmethod
    def interpolate_variables(template: str, variables: Dict[str, Any]) -> str:
        """Replace placeholders in template with actual values."""
        result = template
        for key, value in variables.items():
            placeholder = f"{{{{{key}}}}}"
            result = result.replace(placeholder, str(value))
        return result
    
    @staticmethod
    def generate_data_from_config(generators_config: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Generate data based on configuration."""
        generated_data = {}
        
        for var_name, config in generators_config.items():
            generator_type = config.get('type', 'string')
            
            if generator_type == 'string':
                length = config.get('length', 10)
                generated_data[var_name] = DataGenerator.generate_random_string(length)
            
            elif generator_type == 'number':
                min_val = config.get('min', 1)
                max_val = config.get('max', 1000)
                generated_data[var_name] = DataGenerator.generate_random_number(min_val, max_val)
            
            elif generator_type == 'timestamp':
                format_str = config.get('format', "%Y-%m-%dT%H:%M:%SZ")
                generated_data[var_name] = DataGenerator.generate_timestamp(format_str)
            
            elif generator_type == 'uuid':
                generated_data[var_name] = DataGenerator.generate_uuid()
            
            elif generator_type == 'email':
                domain = config.get('domain', 'example.com')
                generated_data[var_name] = DataGenerator.generate_email(domain)
            
            elif generator_type == 'choice':
                choices = config.get('choices', ['option1', 'option2'])
                generated_data[var_name] = random.choice(choices)
            
            else:
                logger.warning(f"Unknown generator type: {generator_type}")
                generated_data[var_name] = f"unknown_{generator_type}"
        
        return generated_data
    
    @staticmethod
    def prepare_env_variables(env_config: Optional[Dict[str, str]]) -> Dict[str, str]:
        """Prepare environment variables for K6 script."""
        env_vars = {}
        
        if env_config:
            for key, value in env_config.items():
                # Support both direct values and references to system env vars
                if value.startswith('$'):
                    # Reference to system env var: "$HOME" -> os.getenv("HOME")
                    system_var = value[1:]
                    env_vars[key] = os.getenv(system_var, value)
                else:
                    env_vars[key] = value
        
        return env_vars
    
    @staticmethod
    def process_data_file(file_path: str) -> List[Dict[str, Any]]:
        """Process data file based on extension."""
        if not file_path or not os.path.exists(file_path):
            logger.warning(f"Data file not found: {file_path}")
            return []
        
        file_ext = Path(file_path).suffix.lower()
        
        if file_ext == '.csv':
            return DataGenerator.load_from_csv(file_path)
        elif file_ext == '.json':
            return DataGenerator.load_from_json(file_path)
        else:
            logger.error(f"Unsupported file format: {file_ext}")
            return []