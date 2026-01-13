"""Управление инвентарем пользователя."""

import os
import time
from typing import Any, Dict, List
import requests
from config import (
    BASE_URL,
    REQUEST_TIMEOUT,
    DEFAULT_DELAY,
    OUTPUT_DIR,
    INVENTORY_FILE,
    PARSED_INVENTORY_FILE
)
from utils import load_json, save_json


class InventoryManager:
    """Менеджер для работы с инвентарем."""
    
    def __init__(self, output_dir: str = OUTPUT_DIR):
        """
        Инициализация менеджера инвентаря.
        
        Args:
            output_dir: Директория для хранения файлов
        """
        self.output_dir = output_dir
        self.inventory_path = os.path.join(output_dir, INVENTORY_FILE)
        self.parsed_inventory_path = os.path.join(output_dir, PARSED_INVENTORY_FILE)
    
    def load_inventory(self) -> List[Dict[str, Any]]:
        """
        Загружает инвентарь из файла.
        
        Returns:
            Список карт инвентаря
        """
        return load_json(self.inventory_path, default=[])
    
    def save_inventory(self, inventory: List[Dict[str, Any]]) -> bool:
        """
        Сохраняет инвентарь в файл.
        
        Args:
            inventory: Список карт для сохранения
        
        Returns:
            True если успешно
        """
        return save_json(self.inventory_path, inventory)
    
    def load_parsed_inventory(self) -> Dict[str, Dict[str, Any]]:
        """
        Загружает пропарсенный инвентарь из файла.
        
        Returns:
            Словарь с пропарсенными картами {card_id: card_data}
        """
        return load_json(self.parsed_inventory_path, default={})
    
    def save_parsed_inventory(
        self,
        parsed_inventory: Dict[str, Dict[str, Any]]
    ) -> bool:
        """
        Сохраняет пропарсенный инвентарь в файл.
        
        Args:
            parsed_inventory: Словарь с пропарсенными картами
        
        Returns:
            True если успешно
        """
        return save_json(self.parsed_inventory_path, parsed_inventory)
    
    def remove_card(self, card: Dict[str, Any]) -> bool:
        """
        Удаляет карту из инвентаря.
        
        Args:
            card: Карта для удаления
        
        Returns:
            True если успешно
        """
        inventory = self.load_inventory()
        
        try:
            inventory.remove(card)
            return self.save_inventory(inventory)
        except ValueError:
            return False


def fetch_user_cards(
    session: requests.Session,
    user_id: str,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Загружает карточки пользователя с заданным смещением.
    
    Args:
        session: Сессия requests
        user_id: ID пользователя
        offset: Смещение для пагинации
    
    Returns:
        Список карт или пустой список при ошибке
    """
    url = f"{BASE_URL}/trades/{user_id}/availableCardsLoad"
    
    headers = {
        "Referer": f"{BASE_URL}/trades/{user_id}",
        "Origin": BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    
    try:
        response = session.post(
            url,
            headers=headers,
            data={"offset": offset},
            timeout=REQUEST_TIMEOUT
        )
        
        if response.status_code != 200:
            return []
        
        data = response.json()
        return data.get("cards", [])
        
    except (requests.RequestException, ValueError):
        return []


def get_user_inventory(
    session: requests.Session,
    user_id: str,
    page_size: int = 60
) -> List[Dict[str, Any]]:
    """
    Получает все карточки пользователя.
    
    Args:
        session: Сессия requests
        user_id: ID пользователя
        page_size: Размер страницы (по умолчанию API возвращает 60)
    
    Returns:
        Список всех карт пользователя
    """
    all_cards = []
    offset = 0
    
    while True:
        cards = fetch_user_cards(session, user_id, offset)
        
        if not cards:
            break
        
        all_cards.extend(cards)
        offset += len(cards)
        
        # Если получили меньше, чем размер страницы - это последняя страница
        if len(cards) < page_size:
            break
        
        time.sleep(DEFAULT_DELAY)
    
    return all_cards