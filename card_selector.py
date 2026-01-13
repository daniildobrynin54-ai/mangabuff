"""Селектор карт для обмена."""

import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from config import (
    OUTPUT_DIR,
    MAX_CARD_SELECTION_ATTEMPTS,
    CACHE_VALIDITY_HOURS,
    MAX_WANTERS_FOR_TRADE  # 🔧 НОВОЕ
)
from inventory import InventoryManager
from parsers import count_wants
from utils import extract_card_data, is_cache_valid


# 🔧 НОВОЕ: Используем константу из config.py
MAX_WANTERS_ALLOWED = MAX_WANTERS_FOR_TRADE


class CardSelector:
    """Селектор для подбора оптимальных карт для обмена."""
    
    def __init__(
        self,
        session,
        output_dir: str = OUTPUT_DIR,
        locked_cards: Optional[Set[int]] = None  # 🔧 НОВОЕ
    ):
        """
        Инициализация селектора.
        
        Args:
            session: Сессия requests для парсинга
            output_dir: Директория для файлов
            locked_cards: Множество заблокированных instance_id
        """
        self.session = session
        self.inventory_manager = InventoryManager(output_dir)
        self.locked_cards = locked_cards or set()  # 🔧 НОВОЕ
    
    def is_card_available(self, instance_id: int) -> bool:
        """
        🔧 НОВОЕ: Проверяет, доступна ли карта для обмена.
        
        Args:
            instance_id: ID экземпляра карты
        
        Returns:
            True если карта не заблокирована
        """
        return instance_id not in self.locked_cards
    
    def parse_and_cache_card(
        self,
        card: Dict[str, Any],
        parsed_inventory: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Парсит карту и сохраняет в кэш.
        
        Args:
            card: Карта для парсинга
            parsed_inventory: Словарь с кэшированными картами
        
        Returns:
            Пропарсенная карта или None
        """
        card_data = extract_card_data(card)
        
        if not card_data:
            return None
        
        # 🔧 НОВОЕ: Проверяем блокировку карты
        instance_id = card_data["instance_id"]
        if not self.is_card_available(instance_id):
            return None
        
        card_id_str = str(card_data["card_id"])
        
        # Проверяем кэш
        if card_id_str in parsed_inventory:
            cached = parsed_inventory[card_id_str]
            if is_cache_valid(cached.get("cached_at", ""), CACHE_VALIDITY_HOURS):
                # 🔧 НОВОЕ: Обновляем instance_id в кэше
                cached["instance_id"] = instance_id
                return cached
        
        # Парсим количество желающих
        wanters_count = count_wants(
            self.session,
            card_id_str,
            force_accurate=False
        )
        
        if wanters_count < 0:
            return None
        
        # 🔧 НОВОЕ: Проверяем ограничение на желающих
        if wanters_count > MAX_WANTERS_ALLOWED:
            return None
        
        # Создаем запись
        parsed_card = {
            "card_id": card_data["card_id"],
            "name": card_data["name"],
            "rank": card_data["rank"],
            "wanters_count": wanters_count,
            "timestamp": time.time(),
            "cached_at": datetime.now().isoformat(),
            "instance_id": instance_id
        }
        
        # Сохраняем в кэш
        parsed_inventory[card_id_str] = parsed_card
        self.inventory_manager.save_parsed_inventory(parsed_inventory)
        
        return parsed_card
    
    def filter_cards_by_rank(
        self,
        inventory: List[Dict[str, Any]],
        target_rank: str
    ) -> List[Dict[str, Any]]:
        """
        Фильтрует карты по рангу.
        
        Args:
            inventory: Список карт инвентаря
            target_rank: Целевой ранг
        
        Returns:
            Отфильтрованный список карт
        """
        filtered = []
        
        for card in inventory:
            card_data = extract_card_data(card)
            if card_data and card_data["rank"] == target_rank:
                # 🔧 НОВОЕ: Проверяем доступность карты
                if self.is_card_available(card_data["instance_id"]):
                    filtered.append(card)
        
        return filtered
    
    def select_from_unparsed(
        self,
        available_cards: List[Dict[str, Any]],
        target_wanters: int,
        parsed_inventory: Dict[str, Dict[str, Any]],
        max_attempts: int = MAX_CARD_SELECTION_ATTEMPTS
    ) -> Optional[Dict[str, Any]]:
        """
        🔧 УЛУЧШЕНО: Выбирает карту из непропарсенного инвентаря.
        Продолжает до конца если не нашла подходящую.
        
        Args:
            available_cards: Список доступных карт
            target_wanters: Целевое количество желающих
            parsed_inventory: Словарь с кэшированными картами
            max_attempts: Максимальное количество попыток
        
        Returns:
            Подходящая карта или None
        """
        attempts = 0
        
        # Перемешиваем для случайности
        random.shuffle(available_cards)
        
        while available_cards and attempts < max_attempts:
            attempts += 1
            
            # Берем первую карту
            random_card = available_cards.pop(0)
            
            # Удаляем из основного инвентаря
            self.inventory_manager.remove_card(random_card)
            
            # Парсим карту
            parsed_card = self.parse_and_cache_card(random_card, parsed_inventory)
            
            if not parsed_card:
                continue
            
            # 🔧 УЛУЧШЕНО: Проверяем условие
            # Идеальная карта: wanters < target_wanters
            if parsed_card["wanters_count"] < target_wanters:
                return parsed_card
        
        # 🔧 НОВОЕ: Если не нашли идеальную, продолжаем парсить ВСЕ оставшиеся
        print(f"   Продолжаем парсить все непропарсенные карты...")
        
        while available_cards:
            random_card = available_cards.pop(0)
            self.inventory_manager.remove_card(random_card)
            
            parsed_card = self.parse_and_cache_card(random_card, parsed_inventory)
            
            if parsed_card and parsed_card["wanters_count"] < target_wanters:
                return parsed_card
        
        return None
    
    def select_from_parsed(
        self,
        parsed_inventory: Dict[str, Dict[str, Any]],
        target_rank: str,
        target_wanters: int
    ) -> Optional[Dict[str, Any]]:
        """
        🔧 УЛУЧШЕНО: Выбирает карту из пропарсенного инвентаря.
        
        Приоритеты:
        1. Карты с wanters < target_wanters (меньше чем цель)
        2. Карты с wanters <= target_wanters (равно или меньше)
        3. Карты с минимальной разницей (ближайшие)
        
        Args:
            parsed_inventory: Словарь с кэшированными картами
            target_rank: Целевой ранг
            target_wanters: Целевое количество желающих
        
        Returns:
            Подходящая карта или None
        """
        # Фильтруем карты по рангу и доступности
        suitable_less = []      # wanters < target
        suitable_equal = []     # wanters == target
        suitable_closest = []   # wanters > target (ближайшие)
        
        for card_data in parsed_inventory.values():
            if card_data["rank"] != target_rank:
                continue
            
            # 🔧 НОВОЕ: Проверяем доступность
            instance_id = card_data.get("instance_id", 0)
            if not self.is_card_available(instance_id):
                continue
            
            # 🔧 НОВОЕ: Проверяем ограничение
            wanters = card_data["wanters_count"]
            if wanters > MAX_WANTERS_ALLOWED:
                continue
            
            if wanters < target_wanters:
                suitable_less.append(card_data)
            elif wanters == target_wanters:
                suitable_equal.append(card_data)
            else:
                suitable_closest.append(card_data)
        
        # Приоритет 1: Меньше целевого
        if suitable_less:
            return random.choice(suitable_less)
        
        # Приоритет 2: Равно целевому
        if suitable_equal:
            return random.choice(suitable_equal)
        
        # Приоритет 3: Ближайшая больше целевого
        if suitable_closest:
            # Сортируем по возрастанию и берем первую (минимальная разница)
            suitable_closest.sort(key=lambda x: x["wanters_count"])
            return suitable_closest[0]
        
        return None
    
    def select_best_card(
        self,
        target_rank: str,
        target_wanters: int
    ) -> Optional[Dict[str, Any]]:
        """
        🔧 УЛУЧШЕНО: Выбирает лучшую карту для обмена.
        
        Алгоритм:
        1. Ищет в непропарсенном инвентаре (парсит ВСЕ если не нашла)
        2. Ищет в пропарсенном с приоритетами:
           - wanters < target_wanters
           - wanters <= target_wanters  
           - Максимально близкие по количеству желающих
        
        Args:
            target_rank: Целевой ранг карты
            target_wanters: Целевое количество желающих
        
        Returns:
            Подходящая карта или None
        """
        # Загружаем данные
        inventory = self.inventory_manager.load_inventory()
        parsed_inventory = self.inventory_manager.load_parsed_inventory()
        
        if not inventory and not parsed_inventory:
            print("   ⚠️  Инвентарь пуст!")
            return None
        
        # Фильтруем по рангу
        available_cards = self.filter_cards_by_rank(inventory, target_rank)
        
        print(f"   Доступно непропарсенных карт ранга {target_rank}: {len(available_cards)}")
        
        # 🔧 УЛУЧШЕНО: Пытаемся найти в непропарсенном (парсим все)
        if available_cards:
            selected_card = self.select_from_unparsed(
                available_cards,
                target_wanters,
                parsed_inventory
            )
            
            if selected_card:
                print(f"   ✅ Выбрана непропарсенная карта: {selected_card['name']} ({selected_card['wanters_count']} желающих)")
                return selected_card
            else:
                print(f"   ⚠️  Не найдено подходящих непропарсенных карт")
        
        # 🔧 УЛУЧШЕНО: Ищем в пропарсенном с приоритетами
        print(f"   Ищем в пропарсенном инвентаре...")
        selected_card = self.select_from_parsed(
            parsed_inventory,
            target_rank,
            target_wanters
        )
        
        if selected_card:
            wanters = selected_card['wanters_count']
            if wanters < target_wanters:
                print(f"   ✅ Выбрана пропарсенная карта (меньше): {selected_card['name']} ({wanters} < {target_wanters})")
            elif wanters == target_wanters:
                print(f"   ✅ Выбрана пропарсенная карта (равно): {selected_card['name']} ({wanters} = {target_wanters})")
            else:
                print(f"   ✅ Выбрана пропарсенная карта (ближайшая): {selected_card['name']} ({wanters} vs {target_wanters})")
            return selected_card
        
        print(f"   ❌ Не найдено подходящих карт ранга {target_rank}")
        return None


def select_trade_card(
    session,
    boost_card: Dict[str, Any],
    output_dir: str = OUTPUT_DIR,
    trade_manager=None  # 🔧 НОВОЕ: Передаем trade_manager
) -> Optional[Dict[str, Any]]:
    """
    🔧 УЛУЧШЕНО: Главная функция для выбора карты для обмена.
    
    Args:
        session: Сессия для парсинга
        boost_card: Карта из клуба
        output_dir: Директория для файлов
        trade_manager: TradeManager для проверки locked_cards
    
    Returns:
        Выбранная карта или None
    """
    target_rank = boost_card.get("rank", "")
    target_wanters = boost_card.get("wanters_count", 0)
    
    if not target_rank:
        return None
    
    # 🔧 НОВОЕ: Получаем locked_cards из trade_manager
    locked_cards = set()
    if trade_manager:
        locked_cards = trade_manager.locked_cards
    
    selector = CardSelector(session, output_dir, locked_cards)
    return selector.select_best_card(target_rank, target_wanters)