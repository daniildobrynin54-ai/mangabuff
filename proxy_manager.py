"""Менеджер прокси для requests."""

import os
from typing import Optional, Dict
from urllib.parse import urlparse

from config import PROXY_ENABLED, PROXY_URL


class ProxyManager:
    """Менеджер для настройки прокси."""
    
    def __init__(self, proxy_url: Optional[str] = None):
        """
        Инициализация менеджера прокси.
        
        Args:
            proxy_url: URL прокси (формат: http://host:port или socks5://host:port)
                      Поддерживает авторизацию: http://user:pass@host:port
        """
        self.proxy_url = proxy_url or PROXY_URL or os.getenv('PROXY_URL')
        self.enabled = PROXY_ENABLED and bool(self.proxy_url)
    
    def get_proxies(self) -> Optional[Dict[str, str]]:
        """
        Возвращает словарь прокси для requests.
        
        Returns:
            Словарь с прокси или None если прокси не используется
        """
        if not self.enabled or not self.proxy_url:
            return None
        
        # Парсим URL прокси
        parsed = urlparse(self.proxy_url)
        
        # Поддержка разных схем
        if parsed.scheme in ('http', 'https'):
            return {
                'http': self.proxy_url,
                'https': self.proxy_url
            }
        elif parsed.scheme in ('socks5', 'socks5h'):
            # Для SOCKS5 нужна библиотека requests[socks]
            return {
                'http': self.proxy_url,
                'https': self.proxy_url
            }
        else:
            print(f"⚠️  Unknown proxy scheme: {parsed.scheme}")
            return None
    
    def is_enabled(self) -> bool:
        """Проверяет, включен ли прокси."""
        return self.enabled
    
    def get_info(self) -> str:
        """Возвращает информацию о прокси."""
        if not self.enabled:
            return "Proxy: Disabled"
        
        # Скрываем пароль в выводе
        parsed = urlparse(self.proxy_url)
        
        if parsed.password:
            safe_url = f"{parsed.scheme}://{parsed.username}:***@{parsed.hostname}:{parsed.port}"
        else:
            safe_url = self.proxy_url
        
        return f"Proxy: {safe_url}"
    
    @staticmethod
    def parse_proxy_from_file(filepath: str) -> Optional[str]:
        """
        Загружает прокси из файла.
        
        Формат файла (первая строка):
        http://host:port
        или
        http://user:pass@host:port
        
        Args:
            filepath: Путь к файлу с прокси
        
        Returns:
            URL прокси или None
        """
        try:
            with open(filepath, 'r') as f:
                line = f.readline().strip()
                if line:
                    return line
        except FileNotFoundError:
            print(f"⚠️  Proxy file not found: {filepath}")
        except Exception as e:
            print(f"⚠️  Error reading proxy file: {e}")
        
        return None


def create_proxy_manager(
    proxy_url: Optional[str] = None,
    proxy_file: Optional[str] = None
) -> ProxyManager:
    """
    Фабричная функция для создания ProxyManager.
    
    Args:
        proxy_url: URL прокси
        proxy_file: Путь к файлу с прокси
    
    Returns:
        ProxyManager
    """
    # Приоритет: аргумент > файл > переменная окружения > config
    url = proxy_url
    
    if not url and proxy_file:
        url = ProxyManager.parse_proxy_from_file(proxy_file)
    
    manager = ProxyManager(url)
    
    if manager.is_enabled():
        print(f"🌐 {manager.get_info()}")
    else:
        print("🌐 Proxy: Disabled")
    
    return manager