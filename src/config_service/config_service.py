"""
Configuration Service
Handles loading and managing configuration from YAML files and environment variables.
"""

import os
import yaml
from typing import Any, Dict, Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
DEFAULT_ENV_FILE = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=DEFAULT_ENV_FILE)


class ConfigService:
    """
    Centralized configuration service that loads from YAML files
    and merges with environment variables.
    """
    
    def __init__(self, config_dir: str = None):
        """
        Initialize configuration service.
        
        Args:
            config_dir: Directory containing config files. Defaults to project root/config
        """
        if config_dir is None:
            # Default to project_root/config
            self.config_dir = Path(__file__).parent.parent.parent / "config"
        else:
            self.config_dir = Path(config_dir)
        
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Configuration layers (loaded in order, later layers override earlier)
        self.default_config: Dict[str, Any] = {}
        self.main_config: Dict[str, Any] = {}
        self.strategy_config: Dict[str, Any] = {}
        self.backtest_override: Dict[str, Any] = {}
        self.live_override: Dict[str, Any] = {}
        
        # Final merged configuration
        self.config: Dict[str, Any] = {}
        
        # Load all configuration files
        self._load_all_configs()
    
    def _load_yaml_file(self, filename: str) -> Dict[str, Any]:
        """Load a YAML configuration file."""
        filepath = self.config_dir / filename
        
        if not filepath.exists():
            return {}
        
        try:
            with open(filepath, 'r') as f:
                content = yaml.safe_load(f)
                return content if content else {}
        except Exception as e:
            print(f"Warning: Could not load {filename}: {e}")
            return {}
    
    def _load_all_configs(self):
        """Load all configuration files in the correct order."""
        # Load default config (template - should not be edited by users)
        self.default_config = self._load_yaml_file("config.default.yaml")
        
        # Load main config (user-edited primary config)
        self.main_config = self._load_yaml_file("config.yaml")
        
        # Load strategy-specific overrides
        self.strategy_config = self._load_yaml_file("strategy.user.yaml")
        
        # Load service-specific overrides
        self.backtest_override = self._load_yaml_file("backtest.user.yaml")
        self.live_override = self._load_yaml_file("live.user.yaml")
        
        # Merge all configurations
        self._merge_configs()
    
    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """
        Deep merge two dictionaries. Override values take precedence.
        """
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def _merge_configs(self):
        """Merge all configuration layers into final config."""
        # Start with defaults
        self.config = self.default_config.copy()
        
        # Overlay main config
        self.config = self._deep_merge(self.config, self.main_config)
        
        # Overlay strategy config
        self.config = self._deep_merge(self.config, self.strategy_config)
        
        # Note: backtest and live overrides are applied dynamically based on mode
    
    def get_backtest_config(self) -> Dict[str, Any]:
        """Get configuration for backtesting (with backtest overrides applied)."""
        config = self._deep_merge(self.config, self.backtest_override)
        return config
    
    def get_live_config(self) -> Dict[str, Any]:
        """Get configuration for live trading (with live overrides applied)."""
        config = self._deep_merge(self.config, self.live_override)
        return config
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value using dot notation.
        
        Example: config.get("broker_service.default_broker")
        
        Args:
            key: Dot-separated key path
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def get_strategy_config(self, strategy_name: str) -> Dict[str, Any]:
        """
        Load strategy-specific configuration from strategy folder.
        
        Args:
            strategy_name: Name of the strategy (e.g., "madam_strategy")
            
        Returns:
            Strategy configuration dictionary
        """
        strategy_dir = Path(__file__).parent.parent / "strategy_service" / "strategies" / strategy_name
        config_file = strategy_dir / "config.yaml"
        
        if not config_file.exists():
            print(f"Warning: Strategy config not found at {config_file}")
            return {}
        
        try:
            with open(config_file, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Error loading strategy config: {e}")
            return {}
    
    def get_env(self, key: str, default: str = "") -> str:
        """
        Get an environment variable value.
        
        Args:
            key: Environment variable name
            default: Default value if not found
            
        Returns:
            Environment variable value
        """
        return os.getenv(key, default)
    
    def reload(self):
        """Reload all configuration files."""
        self._load_all_configs()
    
    def save_config(self, filename: str, config_data: Dict[str, Any]):
        """
        Save configuration to a YAML file.
        
        Args:
            filename: Name of the file to save
            config_data: Configuration dictionary to save
        """
        filepath = self.config_dir / filename
        
        try:
            with open(filepath, 'w') as f:
                yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
            print(f"Configuration saved to {filepath}")
        except Exception as e:
            print(f"Error saving configuration: {e}")


# Global configuration instance
_config_instance: Optional[ConfigService] = None


def get_config() -> ConfigService:
    """Get the global configuration instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigService()
    return _config_instance


def reload_config():
    """Reload the global configuration."""
    global _config_instance
    if _config_instance is not None:
        _config_instance.reload()


if __name__ == "__main__":
    # Test configuration service
    print("Testing Configuration Service")
    print("=" * 50)
    
    config = ConfigService()
    
    # Test getting values
    broker = config.get("broker_service.default_broker", "fyers")
    print(f"Default broker: {broker}")
    
    initial_capital = config.get("backtest_service.initial_capital", 100000)
    print(f"Backtest initial capital: {initial_capital}")
    
    # Test environment variable
    client_id = config.get_env("FYERS_CLIENT_ID", "not_set")
    print(f"Fyers Client ID: {client_id}")
    
    # Test strategy config
    strategy_cfg = config.get_strategy_config("madam_strategy")
    if strategy_cfg:
        print(f"\nMadam Strategy config loaded:")
        print(f"  Strategy name: {strategy_cfg.get('strategy_name')}")
        print(f"  Volume threshold: {strategy_cfg.get('params', {}).get('volume_threshold')}")
    
    print("\n✅ Configuration service test completed")
