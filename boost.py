"""Работа с буст-картами клуба."""

import re
import time
from typing import Any, Dict, List, Optional
import requests
from bs4 import BeautifulSoup
from config import BASE_URL, REQUEST_TIMEOUT, MAX_CLUB_CARD_OWNERS
from parsers import count_owners, count_wants
from inventory import get_user_inventory
from utils import extract_card_data


class ClubMemberParser:
    """Парсер участников клуба с буст-картой."""
    
    def __init__(self, session: requests.Session):
        """
        Инициализация парсера.
        
        Args:
            session: Сессия requests
        """
        self.session = session
    
    def extract_user_id_from_avatar(self, avatar_element) -> Optional[str]:
        """
        Извлекает ID пользователя из элемента аватара.
        
        Args:
            avatar_element: Элемент BeautifulSoup с аватаром
        
        Returns:
            ID пользователя или None
        """
        # Ищем ссылку внутри аватара
        link = avatar_element.find('a', href=True)
        
        if not link:
            # Проверяем, может сам элемент является ссылкой
            if avatar_element.name == 'a' and avatar_element.has_attr('href'):
                link = avatar_element
            else:
                return None
        
        href = link.get('href', '')
        # Формат: /users/101264
        match = re.search(r'/users/(\d+)', href)
        
        return match.group(1) if match else None
    
    def get_user_nickname(self, user_id: str) -> Optional[str]:
        """
        Получает никнейм пользователя со страницы профиля.
        
        Args:
            user_id: ID пользователя
        
        Returns:
            Никнейм или None
        """
        url = f"{BASE_URL}/users/{user_id}"
        
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                return None
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Ищем никнейм в различных местах
            selectors = [
                '.profile__name',
                '.profile-name',
                '[data-name]',
                'div.profile h1',
                'div.profile h2'
            ]
            
            for selector in selectors:
                element = soup.select_one(selector)
                if element:
                    # Пробуем получить из атрибута data-name
                    if element.has_attr('data-name'):
                        nickname = element.get('data-name', '').strip()
                        if nickname:
                            return nickname
                    
                    # Пробуем получить из текста
                    nickname = element.get_text(strip=True)
                    if nickname:
                        return nickname
            
            return None
            
        except requests.RequestException:
            return None
    
    def parse_club_members_with_card(self, boost_url: str) -> List[Dict[str, str]]:
        """
        Парсит участников клуба, у которых есть буст-карта.
        
        Args:
            boost_url: URL страницы буста
        
        Returns:
            Список словарей {user_id, nickname}
        """
        # Нормализуем URL
        if not boost_url.startswith("http"):
            boost_url = f"{BASE_URL}{boost_url}"
        
        try:
            response = self.session.get(boost_url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Ищем аватары участников клуба
            # Возможные селекторы для аватаров
            avatar_selectors = [
                '.club-boost__avatar',
                '.club-boost-avatar',
                'a.club-boost__avatar',
                'div.club-boost__user'
            ]
            
            avatars = []
            for selector in avatar_selectors:
                found = soup.select(selector)
                if found:
                    avatars.extend(found)
            
            if not avatars:
                return []
            
            members = []
            seen_ids = set()
            
            for avatar in avatars:
                user_id = self.extract_user_id_from_avatar(avatar)
                
                if not user_id or user_id in seen_ids:
                    continue
                
                seen_ids.add(user_id)
                
                # Получаем никнейм
                nickname = self.get_user_nickname(user_id)
                
                if nickname:
                    members.append({
                        'user_id': user_id,
                        'nickname': nickname
                    })
                    
                # Небольшая задержка между запросами профилей
                time.sleep(0.3)
            
            return members
            
        except requests.RequestException:
            return []


class BoostCardExtractor:
    """Извлечение информации о буст-карте."""
    
    def __init__(self, session: requests.Session):
        """
        Инициализация экстрактора.
        
        Args:
            session: Сессия requests
        """
        self.session = session
        self.member_parser = ClubMemberParser(session)
    
    def extract_card_id_from_button(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Извлекает ID карты из кнопки на странице буста.
        
        Args:
            soup: Объект BeautifulSoup со страницей
        
        Returns:
            ID карты или None
        """
        card_link = soup.select_one('a.button.button--block[href*="/cards/"]')
        
        if not card_link:
            return None
        
        href = card_link.get("href", "")
        match = re.search(r"/cards/(\d+)", href)
        
        return match.group(1) if match else None
    
    def extract_card_image_from_boost_page(self, soup: BeautifulSoup) -> Optional[str]:
        """
        🆕 НОВОЕ: Извлекает URL изображения карты со страницы буста.
        
        Args:
            soup: Объект BeautifulSoup со страницей буста
        
        Returns:
            URL изображения или None
        """
        img_elem = soup.select_one('.club-boost__image img')
        
        if img_elem:
            img_src = img_elem.get('src', '')
            if img_src:
                # Если относительный путь - делаем абсолютным
                if img_src.startswith('/'):
                    return f"{BASE_URL}{img_src}"
                return img_src
        
        return None
    
    def fetch_card_page_info(
        self,
        card_id: str
    ) -> tuple[str, str]:
        """
        Получает информацию о карте со страницы карты.
        
        Args:
            card_id: ID карты
        
        Returns:
            Кортеж (название карты, ранг карты)
        """
        url = f"{BASE_URL}/cards/{card_id}"
        
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                return "", ""
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Извлекаем название
            title_selectors = [
                'h1.card-show__title',
                'h1[class*="title"]',
                '.card-show__name'
            ]
            
            card_name = ""
            for selector in title_selectors:
                title_el = soup.select_one(selector)
                if title_el:
                    card_name = title_el.get_text(strip=True)
                    break
            
            # Извлекаем ранг
            rank_selectors = [
                '.card-show__grade',
                '.card-grade',
                '[class*="grade"]',
                '[data-rank]'
            ]
            
            card_rank = ""
            for selector in rank_selectors:
                rank_el = soup.select_one(selector)
                if rank_el:
                    if rank_el.has_attr("data-rank"):
                        card_rank = rank_el.get("data-rank", "")
                    else:
                        card_rank = rank_el.get_text(strip=True)
                    
                    # Очищаем от лишних символов
                    card_rank = re.sub(r'[^A-Z]', '', card_rank.upper())
                    if card_rank:
                        break
            
            return card_name, card_rank
            
        except requests.RequestException:
            return "", ""
    
    def fetch_from_owner_inventory(
        self,
        card_id: str
    ) -> tuple[str, str, int]:
        """
        Получает информацию из инвентаря последнего владельца.
        
        Args:
            card_id: ID карты
        
        Returns:
            Кортеж (название, ранг, instance_id)
        """
        try:
            # Получаем страницу владельцев
            users_url = f"{BASE_URL}/cards/{card_id}/users"
            response = self.session.get(users_url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                return "", "", 0
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Находим всех владельцев
            user_links = [
                a for a in soup.find_all("a", href=True)
                if a["href"].startswith("/users/")
            ]
            
            if not user_links:
                return "", "", 0
            
            # Берем последнего владельца
            last_user_link = user_links[-1]
            owner_id = last_user_link["href"].rstrip("/").split("/")[-1]
            
            # Получаем инвентарь владельца
            owner_cards = get_user_inventory(self.session, owner_id)
            
            # Ищем нужную карту
            for card in owner_cards:
                card_data = extract_card_data(card)
                
                if not card_data:
                    continue
                
                if card_data["card_id"] == int(card_id):
                    return (
                        card_data["name"],
                        card_data["rank"],
                        card_data["instance_id"]
                    )
            
            return "", "", 0
            
        except Exception:
            return "", "", 0
    
    def get_card_info(self, boost_url: str) -> Optional[Dict[str, Any]]:
        """
        Получает полную информацию о карте для буста.
        
        Args:
            boost_url: URL страницы буста
        
        Returns:
            Словарь с информацией о карте или None
        """
        # Нормализуем URL
        if not boost_url.startswith("http"):
            boost_url = f"{BASE_URL}{boost_url}"
        
        try:
            # Загружаем страницу буста
            response = self.session.get(boost_url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                return None
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Извлекаем ID карты
            card_id = self.extract_card_id_from_button(soup)
            
            if not card_id:
                return None
            
            # 🆕 НОВОЕ: Извлекаем URL изображения карты
            image_url = self.extract_card_image_from_boost_page(soup)
            
            # Получаем информацию со страницы карты
            card_name, card_rank = self.fetch_card_page_info(card_id)
            instance_id = 0
            
            # Если не удалось получить информацию - пробуем через инвентарь
            if not card_name or not card_rank:
                name, rank, inst_id = self.fetch_from_owner_inventory(card_id)
                
                if not card_name:
                    card_name = name
                if not card_rank:
                    card_rank = rank
                if not instance_id:
                    instance_id = inst_id
            
            # Получаем статистику
            owners_count = count_owners(self.session, card_id, force_accurate=False)
            wants_count = count_wants(self.session, card_id, force_accurate=False)
            
            # Определяем, нужна ли автозамена
            needs_replacement = owners_count > 0 and owners_count <= MAX_CLUB_CARD_OWNERS
            
            # Парсим участников клуба с этой картой
            club_members = self.member_parser.parse_club_members_with_card(boost_url)
            
            return {
                "name": card_name,
                "id": instance_id,
                "card_id": int(card_id),
                "rank": card_rank,
                "wanters_count": wants_count,
                "owners_count": owners_count,
                "card_url": f"{BASE_URL}/cards/{card_id}/users",
                "timestamp": time.time(),
                "needs_replacement": needs_replacement,
                "club_members": club_members,
                "image_url": image_url  # 🆕 НОВОЕ: URL изображения карты
            }
            
        except requests.RequestException:
            return None


def get_boost_card_info(
    session: requests.Session,
    boost_url: str
) -> Optional[Dict[str, Any]]:
    """
    Удобная функция для получения информации о буст-карте.
    
    Args:
        session: Сессия requests
        boost_url: URL страницы буста
    
    Returns:
        Информация о карте или None
    """
    extractor = BoostCardExtractor(session)
    return extractor.get_card_info(boost_url)


def replace_club_card(session: requests.Session) -> bool:
    """
    Заменяет карту в клубе через API.
    
    Args:
        session: Сессия requests
    
    Returns:
        True если успешно
    """
    url = f"{BASE_URL}/clubs/replace"
    csrf_token = session.headers.get('X-CSRF-TOKEN', '')
    
    headers = {
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "X-CSRF-Token": csrf_token,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": session.url if hasattr(session, 'url') else BASE_URL,
        "Origin": BASE_URL,
    }
    
    try:
        response = session.post(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
        
        return response.status_code == 200
        
    except requests.RequestException:
        return False


def format_club_members_info(members: List[Dict[str, str]]) -> str:
    """
    Форматирует информацию об участниках клуба.
    
    Args:
        members: Список словарей с информацией об участниках
    
    Returns:
        Отформатированная строка
    """
    if not members:
        return "В клубе ни у кого нет"
    
    if len(members) == 1:
        return f"В клубе имеется у: {members[0]['nickname']}"
    
    nicknames = [m['nickname'] for m in members]
    return f"В клубе имеется у: {', '.join(nicknames)}"