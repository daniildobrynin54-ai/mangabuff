"""Модуль автоматической замены карт в клубе с блокировкой при достижении лимита."""

import time
from typing import Optional
import requests
from boost import get_boost_card_info, replace_club_card
from trade import cancel_all_sent_trades
from daily_stats import DailyStatsManager
from utils import print_section, print_success, print_warning, print_info
from config import OUTPUT_DIR, MAX_CLUB_CARD_OWNERS


class CardReplacementManager:
    """Менеджер автоматической замены карт с контролем лимита."""
    
    def __init__(
        self,
        session: requests.Session,
        boost_url: str,
        stats_manager: DailyStatsManager
    ):
        """
        Инициализация менеджера.
        
        Args:
            session: Сессия requests
            boost_url: URL страницы буста
            stats_manager: Менеджер статистики
        """
        self.session = session
        self.boost_url = boost_url
        self.stats_manager = stats_manager
    
    def should_replace_card(self, boost_card: dict) -> bool:
        """Проверяет, нужно ли заменить карту."""
        owners_count = boost_card.get('owners_count', 0)
        
        if owners_count <= 0:
            print_info("Нет данных о владельцах карты")
            return False
        
        if owners_count > MAX_CLUB_CARD_OWNERS:
            print_info(f"Владельцев {owners_count} > {MAX_CLUB_CARD_OWNERS} - замена не требуется")
            return False
        
        print_warning(f"⚠️  Владельцев {owners_count} <= {MAX_CLUB_CARD_OWNERS} - требуется замена!")
        return True
    
    def can_replace(self) -> bool:
        """
        🔧 ИСПРАВЛЕНО: Проверяет лимит замен с обновлением с сервера.
        
        Returns:
            True если лимит не достигнут
        """
        if not self.stats_manager.can_replace(force_refresh=True):
            print_warning(f"⛔ Достигнут дневной лимит замен карт!")
            self.stats_manager.print_stats()
            return False
        
        return True
    
    def perform_replacement(self, boost_card: dict) -> Optional[dict]:
        """
        🔧 ИСПРАВЛЕНО: Выполняет замену карты с блокировкой при достижении лимита.
        
        Args:
            boost_card: Текущая карта
        
        Returns:
            Информация о новой карте или None
        """
        if not self.should_replace_card(boost_card):
            return None
        
        # 🔧 КРИТИЧНО: Проверяем лимит ПЕРЕД любыми действиями
        if not self.can_replace():
            return None
        
        print_section("🔄 АВТОМАТИЧЕСКАЯ ЗАМЕНА КАРТЫ", char="=")
        
        old_card_id = boost_card.get('card_id')
        old_card_name = boost_card.get('name', 'Неизвестно')
        owners = boost_card.get('owners_count', '?')
        
        print(f"   Текущая карта: {old_card_name} (ID: {old_card_id})")
        print(f"   Владельцев: {owners} (порог: {MAX_CLUB_CARD_OWNERS})")
        
        # Показываем актуальную статистику
        replacements_left = self.stats_manager.get_replacements_left(force_refresh=True)
        print(f"   Замен осталось сегодня: {replacements_left}\n")
        
        # Отменяем обмены перед заменой
        print("1️⃣ Отменяем все отправленные обмены...")
        cancel_all_sent_trades(self.session, debug=False)
        time.sleep(1)
        
        # 🔧 ЕЩЕ РАЗ проверяем лимит перед отправкой запроса
        if not self.stats_manager.can_replace(force_refresh=True):
            print_warning("⛔ Лимит замен достигнут перед отправкой!")
            print("=" * 60 + "\n")
            return None
        
        # Выполняем замену
        print("2️⃣ Отправляем запрос на замену карты...")
        success = replace_club_card(self.session)
        
        if not success:
            print_warning("❌ Не удалось заменить карту")
            print("=" * 60 + "\n")
            return None
        
        print_success("✅ Запрос на замену отправлен!")
        
        # Ждем обновления данных
        print("3️⃣ Ожидание обновления данных (3 сек)...")
        time.sleep(3)
        
        # Обновляем статистику с сервера
        print("4️⃣ Обновляем статистику с сервера...")
        self.stats_manager.refresh_stats()
        
        # Загружаем информацию о новой карте
        print("5️⃣ Загружаем информацию о новой карте...")
        new_boost_card = get_boost_card_info(self.session, self.boost_url)
        
        if not new_boost_card:
            print_warning("❌ Не удалось получить информацию о новой карте")
            print("=" * 60 + "\n")
            return None
        
        new_card_id = new_boost_card.get('card_id')
        new_card_name = new_boost_card.get('name', 'Неизвестно')
        new_owners = new_boost_card.get('owners_count', '?')
        
        # Проверяем что карта изменилась
        if new_card_id != old_card_id:
            print_success(f"✅ Карта успешно заменена!")
            print(f"\n   Старая: {old_card_name} (ID: {old_card_id}, владельцев: {owners})")
            print(f"   Новая: {new_card_name} (ID: {new_card_id}, владельцев: {new_owners})\n")
            
            # Выводим обновленную статистику с сервера
            self.stats_manager.print_stats(force_refresh=True)
            print("=" * 60 + "\n")
            
            return new_boost_card
        else:
            print_warning(f"⚠️  Карта не изменилась (ID: {old_card_id})")
            print("   Возможно, замена не сработала или вернулась та же карта\n")
            
            # Все равно обновляем статистику
            self.stats_manager.print_stats(force_refresh=True)
            print("=" * 60 + "\n")
            return None


def check_and_replace_if_needed(
    session: requests.Session,
    boost_url: str,
    boost_card: dict,
    stats_manager: DailyStatsManager
) -> Optional[dict]:
    """
    🔧 ИСПРАВЛЕНО: Проверяет карту и заменяет её если нужно и возможно.
    
    Args:
        session: Сессия requests
        boost_url: URL страницы буста
        boost_card: Информация о текущей карте
        stats_manager: Менеджер статистики
    
    Returns:
        Новая карта если была замена, иначе None
    """
    manager = CardReplacementManager(session, boost_url, stats_manager)
    return manager.perform_replacement(boost_card)