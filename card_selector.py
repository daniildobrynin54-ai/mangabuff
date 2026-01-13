"""Селектор карт для обмена с учетом заблокированных карт."""

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
    
    def __init__(self, session, output_dir: str = OUTPUT_DIR, trade_manager=None):
        """
        Инициализация селектора.
        
        Args:
            session: Сессия requests для парсинга
            output_dir: Директория для файлов
            trade_manager: TradeManager для проверки заблокированных карт
        """
        self.session = session
        self.inventory_manager = InventoryManager(output_dir)
        self.trade_manager = trade_manager
    
    def parse_and_cache_card(
        self,
        card: Dict[str, Any],
        parsed_inventory: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Парсит карту и сохраняет в кэш."""
        card_data = extract_card_data(card)
        
        if not card_data:
            return None
        
        card_id_str = str(card_data["card_id"])
        instance_id = card_data["instance_id"]
        
        # Проверяем что карта не заблокирована
        if self.trade_manager and self.trade_manager.is_my_card_locked(instance_id):
            return None
        
        # Проверяем кэш
        if card_id_str in parsed_inventory:
            cached = parsed_inventory[card_id_str]
            if is_cache_valid(cached.get("cached_at", ""), CACHE_VALIDITY_HOURS):
                cached_instance = cached.get("instance_id", 0)
                if self.trade_manager and self.trade_manager.is_my_card_locked(cached_instance):
                    return None
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
        """Фильтрует карты по рангу и исключает заблокированные."""
        filtered = []
        
        for card in inventory:
            card_data = extract_card_data(card)
            if not card_data:
                continue
            
            if card_data["rank"] != target_rank:
                continue
            
            instance_id = card_data.get("instance_id", 0)
            if self.trade_manager and self.trade_manager.is_my_card_locked(instance_id):
                continue
            
            filtered.append(card)
        
        return filtered
    
    def select_from_unparsed(
        self,
        available_cards: List[Dict[str, Any]],
        target_wanters: int,
        parsed_inventory: Dict[str, Dict[str, Any]],
        max_attempts: int = MAX_CARD_SELECTION_ATTEMPTS
    ) -> Optional[Dict[str, Any]]:
        """Выбирает карту из непропарсенного инвентаря."""
        attempts = 0
        
        while available_cards and attempts < max_attempts:
            attempts += 1
            
            random_card = random.choice(available_cards)
            available_cards.remove(random_card)
            
            parsed_card = self.parse_and_cache_card(random_card, parsed_inventory)
            
            if not parsed_card:
                continue
            
            self.inventory_manager.remove_card(random_card)
            
            if parsed_card["wanters_count"] < target_wanters:
                return parsed_card
        
        return None
    
    def select_from_parsed(
        self,
        parsed_inventory: Dict[str, Dict[str, Any]],
        target_rank: str,
        target_wanters: int
    ) -> Optional[Dict[str, Any]]:
        """Выбирает карту из пропарсенного инвентаря."""
        suitable_cards = []
        closest_cards = []
        
        for card_data in parsed_inventory.values():
            if card_data["rank"] != target_rank:
                continue
            
            instance_id = card_data.get("instance_id", 0)
            if self.trade_manager and self.trade_manager.is_my_card_locked(instance_id):
                continue
            
            if card_data["wanters_count"] < target_wanters:
                suitable_cards.append(card_data)
            else:
                closest_cards.append(card_data)
        
        if suitable_cards:
            return random.choice(suitable_cards)
        
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
        """Выбирает лучшую карту для обмена."""
        inventory = self.inventory_manager.load_inventory()
        parsed_inventory = self.inventory_manager.load_parsed_inventory()
        
        if not inventory and not parsed_inventory:
            return None
        
        available_cards = self.filter_cards_by_rank(inventory, target_rank)
        
        selected_card = self.select_from_unparsed(
            available_cards,
            target_wanters,
            parsed_inventory
        )
        
        if selected_card:
            return selected_card
        
        return self.select_from_parsed(
            parsed_inventory,
            target_rank,
            target_wanters
        )


def select_trade_card(
    session,
    boost_card: Dict[str, Any],
    output_dir: str = OUTPUT_DIR,
    trade_manager=None
) -> Optional[Dict[str, Any]]:
    """Главная функция для выбора карты для обмена."""
    target_rank = boost_card.get("rank", "")
    target_wanters = boost_card.get("wanters_count", 0)
    
    if not target_rank:
        return None
    
    selector = CardSelector(session, output_dir, trade_manager)
    return selector.select_best_card(target_rank, target_wanters)