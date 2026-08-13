"""桌面应用配置模块

集中管理桌面应用的所有配置项，支持用户自定义配置。
"""

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Optional


# 默认配置
DEFAULT_CONFIG = {
    # 应用基础
    "app_name": "Research Agent",
    "app_title": "科研智能体系统",
    "version": "1.1.0",
    
    # 窗口设置
    "window": {
        "width": 1280,
        "height": 800,
        "min_width": 1024,
        "min_height": 640,
        "maximize": False,
        "fullscreen": False,
        "always_on_top": False,
        "resizable": True,
        "frameless": False,
        "background_color": "#f5f5f5",
    },
    
    # 服务器设置
    "server": {
        "host": "127.0.0.1",
        "port": 0,  # 0 = 自动分配
        "auto_port": True,
        "health_check_interval": 0.5,
        "health_check_timeout": 30,
        "debug": False,
        "reload": False,
    },
    
    # 日志设置
    "logging": {
        "level": "INFO",
        "max_size_mb": 10,
        "retention_days": 7,
        "console": True,
        "file": True,
    },
    
    # 数据存储
    "storage": {
        "data_dir": None,  # None = 自动选择
        "db_filename": "research_agent.db",
        "config_filename": "config.json",
        "logs_dir": "logs",
        "cache_dir": "cache",
        "downloads_dir": "downloads",
    },
    
    # 主题设置
    "theme": {
        "primary_color": "#1890ff",
        "background_color": "#ffffff",
        "text_color": "#333333",
        "font_family": "Segoe UI, Arial, sans-serif",
        "font_size": 14,
        "dark_mode": False,
    },
    
    # 系统设置
    "system": {
        "tray_enabled": True,
        "auto_start": False,
        "minimize_to_tray": True,
        "close_to_tray": False,
        "single_instance": True,
    },
    
    # 快捷键
    "shortcuts": {
        "toggle_window": "Ctrl+Shift+A",
        "open_settings": "Ctrl+,",
        "new_chat": "Ctrl+N",
        "save": "Ctrl+S",
        "quit": "Ctrl+Q",
    },
}


class DesktopConfig:
    """桌面应用配置管理"""
    
    def __init__(self, config_dir: Optional[Path] = None):
        self._config = deepcopy(DEFAULT_CONFIG)
        self._config_dir = config_dir or self._get_default_config_dir()
        self._config_file = self._config_dir / DEFAULT_CONFIG["storage"]["config_filename"]
        self._load()
    
    def _get_default_config_dir(self) -> Path:
        """获取默认配置目录"""
        import sys
        
        if sys.platform == "win32":
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
            config_dir = Path(base) / "ResearchAgent"
        elif sys.platform == "darwin":
            config_dir = Path.home() / "Library" / "Application Support" / "ResearchAgent"
        else:
            config_dir = Path.home() / ".research_agent"
        
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir
    
    def _load(self):
        """加载配置文件"""
        if self._config_file.exists():
            try:
                with open(self._config_file, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                self._merge_config(user_config)
            except (json.JSONDecodeError, IOError) as e:
                print(f"警告: 配置文件加载失败，使用默认配置: {e}")
    
    def _merge_config(self, user_config: dict):
        """合并用户配置（递归）"""
        for key, value in user_config.items():
            if key in self._config and isinstance(value, dict) and isinstance(self._config[key], dict):
                self._config[key] = self._deep_merge(self._config[key], value)
            else:
                self._config[key] = value
    
    def _deep_merge(self, base: dict, override: dict) -> dict:
        """深度合并字典"""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(value, dict) and isinstance(result[key], dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    
    def save(self):
        """保存配置到文件"""
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._config_file.with_suffix(".json.tmp")
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, self._config_file)
    
    def get(self, key: str, default=None):
        """获取配置值（支持点号路径）"""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def set(self, key: str, value):
        """设置配置值（支持点号路径）"""
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
    
    def reset(self):
        """重置为默认配置"""
        self._config = deepcopy(DEFAULT_CONFIG)
        self.save()
    
    @property
    def window(self) -> dict:
        """获取窗口配置"""
        return self._config["window"]
    
    @property
    def server(self) -> dict:
        """获取服务器配置"""
        return self._config["server"]
    
    @property
    def logging(self) -> dict:
        """获取日志配置"""
        return self._config["logging"]
    
    @property
    def storage(self) -> dict:
        """获取存储配置"""
        return self._config["storage"]
    
    @property
    def theme(self) -> dict:
        """获取主题配置"""
        return self._config["theme"]
    
    @property
    def system(self) -> dict:
        """获取系统配置"""
        return self._config["system"]
    
    @property
    def shortcuts(self) -> dict:
        """获取快捷键配置"""
        return self._config["shortcuts"]
    
    @property
    def app_name(self) -> str:
        return self._config["app_name"]
    
    @property
    def app_title(self) -> str:
        return self._config["app_title"]
    
    @property
    def version(self) -> str:
        return self._config["version"]
    
    def get_data_dir(self) -> Path:
        """获取数据目录"""
        data_dir = self._config["storage"]["data_dir"]
        if data_dir:
            return Path(data_dir)
        return self._config_dir
    
    def get_logs_dir(self) -> Path:
        """获取日志目录"""
        return self.get_data_dir() / self._config["storage"]["logs_dir"]
    
    def get_cache_dir(self) -> Path:
        """获取缓存目录"""
        cache_dir = self.get_data_dir() / self._config["storage"]["cache_dir"]
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir
    
    def get_downloads_dir(self) -> Path:
        """获取下载目录"""
        downloads_dir = self.get_data_dir() / self._config["storage"]["downloads_dir"]
        downloads_dir.mkdir(parents=True, exist_ok=True)
        return downloads_dir
    
    def get_db_path(self) -> Path:
        """获取数据库路径"""
        return self.get_data_dir() / self._config["storage"]["db_filename"]
    
    def to_dict(self) -> dict:
        """导出为字典"""
        return deepcopy(self._config)
    
    def __repr__(self) -> str:
        return f"<DesktopConfig: {self.app_name} v{self.version}>"


# 全局配置实例
_config_instance: Optional[DesktopConfig] = None


def get_config() -> DesktopConfig:
    """获取全局配置实例"""
    global _config_instance
    if _config_instance is None:
        _config_instance = DesktopConfig()
    return _config_instance


def reload_config():
    """重新加载配置"""
    global _config_instance
    _config_instance = DesktopConfig()
    return _config_instance
