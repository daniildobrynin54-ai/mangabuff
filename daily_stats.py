"""Модуль для отслеживания дневной статистики."""

import os
from datetime import datetime, timedelta
from typing import Dict, Any
from config import (
    OUTPUT_DIR,
    DAILY_STATS_FILE,
    MAX_DAILY_DONATIONS,
    MAX_DAILY_REPLACEMENTS,
    DAILY_RESET_HOUR,
    TIMEZONE_OFFSET
)
from utils import load_json, save_json


class DailyStatsManager:
    """Менеджер дневной статистики."""
    
    def __init__(self, output_dir: str = OUTPUT_DIR):
        """
        Инициализация менеджера статистики.
        
        Args:
            output_dir: Директория для файлов
        """
        self.output_dir = output_dir
        self.stats_path = os.path.join(output_dir, DAILY_STATS_FILE)
    
    def _get_current_date_msk(self) -> str:
        """Получает текущую дату в МСК."""
        # UTC время + смещение МСК
        msk_time = datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)
        return msk_time.strftime("%Y-%m-%d")
    
    def _should_reset_stats(self, stats: Dict[str, Any]) -> bool:
        """
        Проверяет, нужно ли сбросить статистику.
        
        Args:
            stats: Текущая статистика
        
        Returns:
            True если нужен сброс
        """
        current_date = self._get_current_date_msk()
        last_date = stats.get("date", "")
        
        return current_date != last_date
    
    def _create_empty_stats(self) -> Dict[str, Any]:
        """Создает пустую статистику."""
        return {
            "date": self._get_current_date_msk(),
            "donations_count": 0,
            "replacements_count": 0,
            "last_reset": datetime.utcnow().isoformat()
        }
    
    def load_stats(self) -> Dict[str, Any]:
        """
        Загружает статистику.
        
        Returns:
            Словарь со статистикой
        """
        stats = load_json(self.stats_path, default=self._create_empty_stats())
        
        # Проверяем, нужен ли сброс
        if self._should_reset_stats(stats):
            stats = self._create_empty_stats()
            self.save_stats(stats)
        
        return stats
    
    def save_stats(self, stats: Dict[str, Any]) -> bool:
        """
        Сохраняет статистику.
        
        Args:
            stats: Статистика для сохранения
        
        Returns:
            True если успешно
        """
        return save_json(self.stats_path, stats)
    
    def increment_donations(self) -> bool:
        """
        Увеличивает счетчик пожертвований.
        
        Returns:
            True если успешно
        """
        stats = self.load_stats()
        stats["donations_count"] += 1
        return self.save_stats(stats)
    
    def increment_replacements(self) -> bool:
        """
        Увеличивает счетчик замен.
        
        Returns:
            True если успешно
        """
        stats = self.load_stats()
        stats["replacements_count"] += 1
        return self.save_stats(stats)
    
    def can_donate(self) -> bool:
        """
        Проверяет, можно ли пожертвовать карту.
        
        Returns:
            True если лимит не достигнут
        """
        stats = self.load_stats()
        return stats["donations_count"] < MAX_DAILY_DONATIONS
    
    def can_replace(self) -> bool:
        """
        Проверяет, можно ли заменить карту.
        
        Returns:
            True если лимит не достигнут
        """
        stats = self.load_stats()
        return stats["replacements_count"] < MAX_DAILY_REPLACEMENTS
    
    def get_donations_left(self) -> int:
        """Возвращает оставшееся количество пожертвований."""
        stats = self.load_stats()
        return max(0, MAX_DAILY_DONATIONS - stats["donations_count"])
    
    def get_replacements_left(self) -> int:
        """Возвращает оставшееся количество замен."""
        stats = self.load_stats()
        return max(0, MAX_DAILY_REPLACEMENTS - stats["replacements_count"])
    
    def print_stats(self) -> None:
        """Выводит текущую статистику."""
        stats = self.load_stats()
        
        print("\n📊 Дневная статистика:")
        print(f"   Дата: {stats['date']}")
        print(f"   Пожертвовано: {stats['donations_count']}/{MAX_DAILY_DONATIONS}")
        print(f"   Замен карты: {stats['replacements_count']}/{MAX_DAILY_REPLACEMENTS}")
        print(f"   Осталось пожертвований: {self.get_donations_left()}")
        print(f"   Осталось замен: {self.get_replacements_left()}\n")


def check_daily_limits(output_dir: str = OUTPUT_DIR) -> Dict[str, bool]:
    """
    Проверяет дневные лимиты.
    
    Args:
        output_dir: Директория для файлов
    
    Returns:
        Словарь с результатами проверок
    """
    manager = DailyStatsManager(output_dir)
    
    return {
        "can_donate": manager.can_donate(),
        "can_replace": manager.can_replace(),
        "donations_left": manager.get_donations_left(),
        "replacements_left": manager.get_replacements_left()
    }