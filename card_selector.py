"""Селектор карт для обмена."""

import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from config import (
    OUTPUT_DIR,
    MAX_CARD_SELECTION_ATTEMPTS,
    CACHE_VALIDITY_HOURS
)
from inventory import InventoryManager
from parsers import count_wants
from utils import extract_card_data, is_cache_valid


class CardSelector:
    """Селектор для подбора оптимальных карт для обмена."""
    
    def __init__(self, session, output_dir: str = OUTPUT_DIR):
        """
        Инициализация селектора.
        
        Args:
            session: Сессия requests для парсинга
            output_dir: Директория для файлов
        """
        self.session = session
        self.inventory_manager = InventoryManager(output_dir)
    
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
        
        card_id_str = str(card_data["card_id"])
        
        # Проверяем кэш
        if card_id_str in parsed_inventory:
            cached = parsed_inventory[card_id_str]
            if is_cache_valid(cached.get("cached_at", ""), CACHE_VALIDITY_HOURS):
                return cached
        
        # Парсим количество желающих
        wanters_count = count_wants(
            self.session,
            card_id_str,
            force_accurate=False
        )
        
        if wanters_count < 0:
            return None
        
        # Создаем запись
        parsed_card = {
            "card_id": card_data["card_id"],
            "name": card_data["name"],
            "rank": card_data["rank"],
            "wanters_count": wanters_count,
            "timestamp": time.time(),
            "cached_at": datetime.now().isoformat(),
            "instance_id": card_data["instance_id"]
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
        Выбирает карту из непропарсенного инвентаря.
        
        Args:
            available_cards: Список доступных карт
            target_wanters: Целевое количество желающих
            parsed_inventory: Словарь с кэшированными картами
            max_attempts: Максимальное количество попыток
        
        Returns:
            Подходящая карта или None
        """
        attempts = 0
        inventory = self.inventory_manager.load_inventory()
        
        while available_cards and attempts < max_attempts:
            attempts += 1
            
            # Выбираем случайную карту
            random_card = random.choice(available_cards)
            available_cards.remove(random_card)
            
            # Удаляем из основного инвентаря
            self.inventory_manager.remove_card(random_card)
            
            # Парсим карту
            parsed_card = self.parse_and_cache_card(random_card, parsed_inventory)
            
            if not parsed_card:
                continue
            
            # Проверяем условие
            if parsed_card["wanters_count"] < target_wanters:
                return parsed_card
        
        return None
    
    def select_from_parsed(
        self,
        parsed_inventory: Dict[str, Dict[str, Any]],
        target_rank: str,
        target_wanters: int
    ) -> Optional[Dict[str, Any]]:
        """
        Выбирает карту из пропарсенного инвентаря.
        
        Args:
            parsed_inventory: Словарь с кэшированными картами
            target_rank: Целевой ранг
            target_wanters: Целевое количество желающих
        
        Returns:
            Подходящая карта или None
        """
        suitable_cards = []
        closest_cards = []
        
        for card_data in parsed_inventory.values():
            if card_data["rank"] != target_rank:
                continue
            
            if card_data["wanters_count"] < target_wanters:
                suitable_cards.append(card_data)
            else:
                closest_cards.append(card_data)
        
        # Выбираем подходящую случайную карту
        if suitable_cards:
            return random.choice(suitable_cards)
        
        # Если подходящих нет - выбираем самую близкую
        if closest_cards:
            return min(
                closest_cards,
                key=lambda x: abs(x["wanters_count"] - target_wanters)
            )
        
        return None
    
    def select_best_card(
        self,
        target_rank: str,
        target_wanters: int
    ) -> Optional[Dict[str, Any]]:
        """
        Выбирает лучшую карту для обмена.
        
        Алгоритм:
        1. Пытается найти в непропарсенном инвентаре
        2. Если не находит - ищет в пропарсенном
        3. Выбирает карту с меньшим количеством желающих
        
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
            return None
        
        # Фильтруем по рангу
        available_cards = self.filter_cards_by_rank(inventory, target_rank)
        
        # Пытаемся найти в непропарсенном инвентаре
        selected_card = self.select_from_unparsed(
            available_cards,
            target_wanters,
            parsed_inventory
        )
        
        if selected_card:
            return selected_card
        
        # Ищем в пропарсенном инвентаре
        return self.select_from_parsed(
            parsed_inventory,
            target_rank,
            target_wanters
        )


def select_trade_card(
    session,
    boost_card: Dict[str, Any],
    output_dir: str = OUTPUT_DIR
) -> Optional[Dict[str, Any]]:
    """
    Главная функция для выбора карты для обмена.
    
    Args:
        session: Сессия для парсинга
        boost_card: Карта из клуба
        output_dir: Директория для файлов
    
    Returns:
        Выбранная карта или None
    """
    target_rank = boost_card.get("rank", "")
    target_wanters = boost_card.get("wanters_count", 0)
    
    if not target_rank:
        return None
    
    selector = CardSelector(session, output_dir)
    return selector.select_best_card(target_rank, target_wanters)