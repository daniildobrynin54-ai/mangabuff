"""Модуль для отслеживания дневной статистики с парсингом со страницы клуба."""

import re
from typing import Dict, Any, Optional
import requests
from bs4 import BeautifulSoup
from config import (
    BASE_URL,
    REQUEST_TIMEOUT,
    MAX_DAILY_DONATIONS,
    MAX_DAILY_REPLACEMENTS
)


class DailyStatsManager:
    """Менеджер дневной статистики с парсингом с сайта."""
    
    def __init__(self, session: requests.Session, boost_url: str):
        """
        Инициализация менеджера статистики.
        
        Args:
            session: Сессия requests
            boost_url: URL страницы буста клуба
        """
        self.session = session
        self.boost_url = boost_url
        self._cached_stats = None
    
    def _parse_replacements_from_page(self, soup: BeautifulSoup) -> Optional[tuple[int, int]]:
        """
        Парсит количество использованных замен со страницы.
        
        Args:
            soup: Объект BeautifulSoup
        
        Returns:
            Кортеж (использовано, максимум) или None
        """
        try:
            # Ищем блок с заменами: <div><span>2</span> / 10</div>
            change_block = soup.select_one('.club-boost__change > div')
            
            if not change_block:
                return None
            
            text = change_block.get_text(strip=True)
            # Формат: "2 / 10"
            match = re.search(r'(\d+)\s*/\s*(\d+)', text)
            
            if match:
                used = int(match.group(1))
                maximum = int(match.group(2))
                return used, maximum
            
            return None
            
        except Exception as e:
            print(f"⚠️  Ошибка парсинга замен: {e}")
            return None
    
    def _parse_donations_limit(self, soup: BeautifulSoup) -> Optional[tuple[int, int]]:
        """
        Парсит лимит пожертвований из правил.
        
        Args:
            soup: Объект BeautifulSoup
        
        Returns:
            Кортеж (использовано, максимум) или None
        """
        try:
            # Ищем текст вида "В день можно пожертвовать до 5/50 карт"
            rules = soup.select('.club-boost__rules li')
            
            for rule in rules:
                text = rule.get_text()
                
                # Паттерн: "до X/Y карт"
                match = re.search(r'до\s+(\d+)/(\d+)\s+карт', text)
                if match:
                    used = int(match.group(1))
                    maximum = int(match.group(2))
                    return used, maximum
            
            return None
            
        except Exception as e:
            print(f"⚠️  Ошибка парсинга пожертвований: {e}")
            return None
    
    def fetch_stats_from_page(self) -> Optional[Dict[str, Any]]:
        """
        Загружает статистику со страницы клуба.
        
        Returns:
            Словарь со статистикой или None
        """
        try:
            response = self.session.get(self.boost_url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                print(f"⚠️  Ошибка загрузки страницы буста: {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Парсим замены
            replacements_data = self._parse_replacements_from_page(soup)
            
            if replacements_data:
                replacements_used, replacements_max = replacements_data
            else:
                # Используем значения по умолчанию
                replacements_used = 0
                replacements_max = MAX_DAILY_REPLACEMENTS
            
            # Парсим пожертвования
            donations_data = self._parse_donations_limit(soup)
            
            if donations_data:
                donations_used, donations_max = donations_data
            else:
                # Используем значения по умолчанию
                donations_used = 0
                donations_max = MAX_DAILY_DONATIONS
            
            stats = {
                "donations_used": donations_used,
                "donations_max": donations_max,
                "replacements_used": replacements_used,
                "replacements_max": replacements_max,
                "donations_left": donations_max - donations_used,
                "replacements_left": replacements_max - replacements_used
            }
            
            # Кэшируем
            self._cached_stats = stats
            
            return stats
            
        except requests.RequestException as e:
            print(f"⚠️  Ошибка сети при загрузке статистики: {e}")
            return None
        except Exception as e:
            print(f"⚠️  Неожиданная ошибка при парсинге статистики: {e}")
            return None
    
    def get_stats(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Получает статистику (из кэша или загружает заново).
        
        Args:
            force_refresh: Принудительно обновить данные
        
        Returns:
            Словарь со статистикой
        """
        if force_refresh or self._cached_stats is None:
            stats = self.fetch_stats_from_page()
            
            if stats is None:
                # Возвращаем значения по умолчанию при ошибке
                return {
                    "donations_used": 0,
                    "donations_max": MAX_DAILY_DONATIONS,
                    "replacements_used": 0,
                    "replacements_max": MAX_DAILY_REPLACEMENTS,
                    "donations_left": MAX_DAILY_DONATIONS,
                    "replacements_left": MAX_DAILY_REPLACEMENTS
                }
            
            return stats
        
        return self._cached_stats
    
    def can_donate(self, force_refresh: bool = True) -> bool:
        """
        Проверяет, можно ли пожертвовать карту.
        
        Args:
            force_refresh: Обновить данные с сервера
        
        Returns:
            True если лимит не достигнут
        """
        stats = self.get_stats(force_refresh=force_refresh)
        return stats["donations_left"] > 0
    
    def can_replace(self, force_refresh: bool = True) -> bool:
        """
        Проверяет, можно ли заменить карту.
        
        Args:
            force_refresh: Обновить данные с сервера
        
        Returns:
            True если лимит не достигнут
        """
        stats = self.get_stats(force_refresh=force_refresh)
        return stats["replacements_left"] > 0
    
    def get_donations_left(self, force_refresh: bool = False) -> int:
        """Возвращает оставшееся количество пожертвований."""
        stats = self.get_stats(force_refresh=force_refresh)
        return stats["donations_left"]
    
    def get_replacements_left(self, force_refresh: bool = False) -> int:
        """Возвращает оставшееся количество замен."""
        stats = self.get_stats(force_refresh=force_refresh)
        return stats["replacements_left"]
    
    def print_stats(self, force_refresh: bool = False) -> None:
        """Выводит текущую статистику."""
        stats = self.get_stats(force_refresh=force_refresh)
        
        print("\n📊 Дневная статистика (с сервера):")
        print(f"   Пожертвовано: {stats['donations_used']}/{stats['donations_max']}")
        print(f"   Замен карты: {stats['replacements_used']}/{stats['replacements_max']}")
        print(f"   Осталось пожертвований: {stats['donations_left']}")
        print(f"   Осталось замен: {stats['replacements_left']}\n")
    
    def refresh_stats(self) -> None:
        """Принудительно обновляет статистику с сервера."""
        self.fetch_stats_from_page()


def create_stats_manager(
    session: requests.Session,
    boost_url: str
) -> DailyStatsManager:
    """
    Фабричная функция для создания менеджера статистики.
    
    Args:
        session: Сессия requests
        boost_url: URL страницы буста
    
    Returns:
        Экземпляр DailyStatsManager
    """
    return DailyStatsManager(session, boost_url)