import json
import random
import time
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from parsers import count_wants


def load_inventory(output_dir: str = "created_files") -> List[Dict[str, Any]]:
    """Загружает инвентарь из файла"""
    filepath = os.path.join(output_dir, "inventory.json")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def load_parsed_inventory(output_dir: str = "created_files") -> Dict[str, Dict[str, Any]]:
    """Загружает пропарсенный инвентарь из файла"""
    filepath = os.path.join(output_dir, "parsed_inventory.json")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_inventory(data: List[Dict[str, Any]], output_dir: str = "created_files"):
    """Сохраняет инвентарь в файл"""
    filepath = os.path.join(output_dir, "inventory.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_parsed_inventory(data: Dict[str, Dict[str, Any]], output_dir: str = "created_files"):
    """Сохраняет пропарсенный инвентарь в файл"""
    filepath = os.path.join(output_dir, "parsed_inventory.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_cache_valid(cached_at_str: str, hours: int = 24) -> bool:
    """Проверяет актуальность кэша (по умолчанию 24 часа)"""
    try:
        cached_time = datetime.fromisoformat(cached_at_str)
        return datetime.now() - cached_time < timedelta(hours=hours)
    except:
        return False


def extract_card_data(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Извлекает данные карты из различных форматов"""
    card_id = None
    name = ""
    rank = ""
    instance_id = None
    
    # Пробуем разные варианты структуры данных
    if "card_id" in card:
        card_id = card["card_id"]
    
    if "id" in card:
        instance_id = card["id"]
    
    # Имя карты
    if "name" in card:
        name = card["name"]
    elif "title" in card:
        name = card["title"]
    
    # Ранг карты
    if "rank" in card:
        rank = card["rank"]
    elif "grade" in card:
        rank = card["grade"]
    
    # Если есть вложенный объект card
    if "card" in card and isinstance(card["card"], dict):
        if not card_id and "id" in card["card"]:
            card_id = card["card"]["id"]
        if not name and "name" in card["card"]:
            name = card["card"]["name"]
        if not name and "title" in card["card"]:
            name = card["card"]["title"]
        if not rank and "rank" in card["card"]:
            rank = card["card"]["rank"]
        if not rank and "grade" in card["card"]:
            rank = card["card"]["grade"]
    
    if not card_id or not rank:
        return None
    
    return {
        "card_id": int(card_id),
        "name": name,
        "rank": rank.upper(),
        "instance_id": int(instance_id) if instance_id else 0
    }


def parse_and_cache_card(session, card: Dict[str, Any], parsed_inventory: Dict[str, Dict[str, Any]], 
                         output_dir: str, silent: bool = True) -> Optional[Dict[str, Any]]:
    """Парсит карту на количество желающих и сохраняет в кэш"""
    card_data = extract_card_data(card)
    if not card_data:
        return None
    
    card_id_str = str(card_data["card_id"])
    
    # Проверяем кэш
    if card_id_str in parsed_inventory:
        cached = parsed_inventory[card_id_str]
        if is_cache_valid(cached.get("cached_at", "")):
            return cached
    
    # Парсим количество желающих
    wanters_count = count_wants(session, card_id_str, force_accurate=False)
    
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
    save_parsed_inventory(parsed_inventory, output_dir)
    
    return parsed_card


def select_best_card(session, target_rank: str, target_wanters: int, 
                     inventory: List[Dict[str, Any]], 
                     parsed_inventory: Dict[str, Dict[str, Any]],
                     output_dir: str,
                     max_attempts: int = 50,
                     silent: bool = True) -> Optional[Dict[str, Any]]:
    """
    Выбирает лучшую карту для обмена
    
    Алгоритм:
    1. Выбирает случайную карту того же ранга из inventory.json
    2. Парсит количество желающих
    3. Если желающих меньше чем у целевой карты - подходит
    4. Если больше - выбирает другую случайную карту
    5. Если карты в inventory.json закончились - берет из parsed_inventory.json
    6. Если подходящих нет - берет самую близкую по количеству желающих
    """
    
    # Фильтруем карты нужного ранга из непропарсенного инвентаря
    available_cards = []
    for card in inventory:
        card_data = extract_card_data(card)
        if card_data and card_data["rank"] == target_rank:
            available_cards.append(card)
    
    # Пытаемся найти подходящую карту из непропарсенного инвентаря
    attempts = 0
    while available_cards and attempts < max_attempts:
        attempts += 1
        
        # Выбираем случайную карту
        random_card = random.choice(available_cards)
        available_cards.remove(random_card)
        
        # Удаляем из основного инвентаря
        inventory.remove(random_card)
        save_inventory(inventory, output_dir)
        
        # Парсим карту
        parsed_card = parse_and_cache_card(session, random_card, parsed_inventory, output_dir, silent=True)
        
        if not parsed_card:
            continue
        
        # Проверяем условие
        if parsed_card["wanters_count"] < target_wanters:
            return parsed_card
    
    # Фильтруем пропарсенные карты нужного ранга
    suitable_cards = []
    closest_cards = []
    
    for card_id, card_data in parsed_inventory.items():
        if card_data["rank"] != target_rank:
            continue
        
        if card_data["wanters_count"] < target_wanters:
            suitable_cards.append(card_data)
        else:
            closest_cards.append(card_data)
    
    # Если есть подходящие карты
    if suitable_cards:
        selected = random.choice(suitable_cards)
        return selected
    
    # Если подходящих нет - выбираем самую близкую
    if closest_cards:
        closest = min(closest_cards, key=lambda x: abs(x["wanters_count"] - target_wanters))
        return closest
    
    return None


def select_trade_card(session, boost_card: Dict[str, Any], output_dir: str = "created_files") -> Optional[Dict[str, Any]]:
    """
    Главная функция для выбора карты для обмена
    
    Args:
        session: Сессия для парсинга
        boost_card: Карта из клуба (с полями rank и wanters_count)
        output_dir: Директория для файлов
    
    Returns:
        Выбранная карта для обмена или None
    """
    target_rank = boost_card.get("rank", "")
    target_wanters = boost_card.get("wanters_count", 0)
    
    if not target_rank:
        return None
    
    # Загружаем данные
    inventory = load_inventory(output_dir)
    parsed_inventory = load_parsed_inventory(output_dir)
    
    if not inventory and not parsed_inventory:
        return None
    
    # Выбираем лучшую карту
    selected_card = select_best_card(
        session=session,
        target_rank=target_rank,
        target_wanters=target_wanters,
        inventory=inventory,
        parsed_inventory=parsed_inventory,
        output_dir=output_dir,
        silent=True
    )
    
    return selected_card