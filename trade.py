"""Модуль для работы с обменами карт."""

import json
import time
from typing import Any, Dict, Optional
import requests
from bs4 import BeautifulSoup
from config import BASE_URL, REQUEST_TIMEOUT, CARD_API_DELAY


class TradeManager:
    """Менеджер обменов карточками."""
    
    def __init__(self, session: requests.Session, debug: bool = False):
        """
        Инициализация менеджера обменов.
        
        Args:
            session: Сессия requests
            debug: Режим отладки
        """
        self.session = session
        self.debug = debug
    
    def _log(self, message: str) -> None:
        """Выводит отладочное сообщение."""
        if self.debug:
            print(f"[TRADE] {message}")
    
    def _get_csrf_token(self) -> str:
        """Получает CSRF токен из заголовков сессии."""
        return self.session.headers.get('X-CSRF-TOKEN', '')
    
    def _prepare_headers(self, receiver_id: int) -> Dict[str, str]:
        """
        Подготавливает заголовки для запроса.
        
        Args:
            receiver_id: ID получателя
        
        Returns:
            Словарь заголовков
        """
        headers = {
            "Referer": f"{BASE_URL}/trades/offers/{receiver_id}",
            "Origin": BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        
        csrf_token = self._get_csrf_token()
        if csrf_token:
            headers["X-CSRF-TOKEN"] = csrf_token
        
        return headers
    
    def _is_success_response(self, response: requests.Response) -> bool:
        """
        Проверяет, является ли ответ успешным.
        
        Args:
            response: Ответ от сервера
        
        Returns:
            True если успешно
        """
        # Проверка по редиректу
        if response.status_code in (301, 302):
            location = response.headers.get("Location", "")
            if "/trades/" in location:
                return True
        
        # Проверка по JSON ответу
        try:
            data = response.json()
            if isinstance(data, dict):
                # Явные индикаторы успеха
                if data.get("success") or data.get("ok"):
                    return True
                
                # Проверка наличия trade с ID
                if isinstance(data.get("trade"), dict) and data["trade"].get("id"):
                    return True
                
                # Проверка по тексту сообщения
                body_text = json.dumps(data).lower()
                if any(word in body_text for word in ["успеш", "отправ", "создан"]):
                    return True
        except ValueError:
            pass
        
        # Проверка по тексту ответа
        body = (response.text or "").lower()
        if any(word in body for word in ["успеш", "отправ", "создан"]):
            return True
        
        return False
    
    def create_trade(
        self,
        receiver_id: int,
        my_instance_id: int,
        his_instance_id: int
    ) -> bool:
        """
        Отправляет обмен карточками через API.
        
        Args:
            receiver_id: ID получателя обмена
            my_instance_id: Instance ID моей карточки
            his_instance_id: Instance ID карточки получателя
        
        Returns:
            True если обмен успешно отправлен
        """
        url = f"{BASE_URL}/trades/create"
        headers = self._prepare_headers(receiver_id)
        
        # Формируем данные
        data = [
            ("receiver_id", int(receiver_id)),
            ("creator_card_ids[]", int(my_instance_id)),
            ("receiver_card_ids[]", int(his_instance_id)),
        ]
        
        self._log(f"Отправка обмена:")
        self._log(f"  receiver_id: {receiver_id}")
        self._log(f"  creator_card_ids[]: {my_instance_id}")
        self._log(f"  receiver_card_ids[]: {his_instance_id}")
        
        try:
            # Первая попытка с form data
            response = self.session.post(
                url,
                data=data,
                headers=headers,
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT
            )
            
            self._log(f"Response status: {response.status_code}")
            
            if self._is_success_response(response):
                return True
            
            # Вторая попытка с JSON payload
            json_payload = {
                "receiver_id": receiver_id,
                "creator_card_ids": [my_instance_id],
                "receiver_card_ids": [his_instance_id],
            }
            
            response2 = self.session.post(
                url,
                json=json_payload,
                headers={**headers, "Content-Type": "application/json"},
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT
            )
            
            if self._is_success_response(response2):
                return True
            
            self._log(f"Trade failed. Status: {response.status_code}")
            self._log(f"Response: {response.text[:200]}")
            
            return False
            
        except requests.RequestException as e:
            self._log(f"Network error: {e}")
            return False
    
    def cancel_all_sent_trades(self) -> bool:
        """
        Отменяет все отправленные обмены.
        
        Returns:
            True если запрос успешен
        """
        url = f"{BASE_URL}/trades/rejectAll?type_trade=sender"
        
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"{BASE_URL}/trades/offers",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        
        self._log("Отмена всех отправленных обменов...")
        
        try:
            response = self.session.get(
                url,
                headers=headers,
                allow_redirects=True,
                timeout=REQUEST_TIMEOUT
            )
            
            self._log(f"Response status: {response.status_code}")
            return response.status_code == 200
            
        except requests.RequestException as e:
            self._log(f"Network error: {e}")
            return False
    
    def find_partner_card_instance(
        self,
        partner_id: int,
        card_id: int
    ) -> Optional[int]:
        """
        Находит instance_id карточки у партнера.
        
        Args:
            partner_id: ID партнера
            card_id: ID карточки
        
        Returns:
            Instance ID карточки или None
        """
        # Попытка 1: через страницу обменов
        instance_id = self._find_on_page(partner_id, card_id)
        if instance_id:
            return instance_id
        
        # Попытка 2: через API
        return self._find_via_api(partner_id, card_id)
    
    def _find_on_page(self, partner_id: int, card_id: int) -> Optional[int]:
        """Ищет карту на странице обменов."""
        try:
            url = f"{BASE_URL}/trades/offers/{partner_id}"
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                return None
            
            soup = BeautifulSoup(response.text, "html.parser")
            cards = soup.select('[data-id], [data-card-id]')
            
            for card_el in cards:
                el_card_id = (
                    card_el.get("data-card-id") or
                    card_el.get("data-cardid")
                )
                el_instance_id = (
                    card_el.get("data-id") or
                    card_el.get("data-instance-id")
                )
                
                if el_card_id and int(el_card_id) == card_id and el_instance_id:
                    return int(el_instance_id)
            
            return None
            
        except Exception as e:
            self._log(f"Error finding on page: {e}")
            return None
    
    def _find_via_api(
        self,
        partner_id: int,
        card_id: int,
        max_attempts: int = 50
    ) -> Optional[int]:
        """Ищет карту через API."""
        try:
            url = f"{BASE_URL}/trades/{partner_id}/availableCardsLoad"
            
            headers = {
                "Referer": f"{BASE_URL}/trades/offers/{partner_id}",
                "Origin": BASE_URL,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            }
            
            csrf_token = self._get_csrf_token()
            if csrf_token:
                headers["X-CSRF-TOKEN"] = csrf_token
            
            offset = 0
            attempts = 0
            
            while attempts < max_attempts:
                response = self.session.post(
                    url,
                    data={"offset": offset},
                    headers=headers,
                    timeout=REQUEST_TIMEOUT
                )
                
                if response.status_code != 200:
                    break
                
                data = response.json()
                cards = data.get("cards", [])
                
                if not cards:
                    break
                
                for card in cards:
                    c_card_id = card.get("card_id")
                    
                    # Проверяем вложенный объект
                    if isinstance(card.get("card"), dict):
                        c_card_id = card["card"].get("id") or c_card_id
                    
                    if c_card_id and int(c_card_id) == card_id:
                        instance_id = card.get("id")
                        if instance_id:
                            return int(instance_id)
                
                offset += len(cards)
                
                if len(cards) < 60:
                    break
                
                time.sleep(CARD_API_DELAY)
                attempts += 1
            
            return None
            
        except Exception as e:
            self._log(f"Error finding via API: {e}")
            return None


def send_trade_to_owner(
    session: requests.Session,
    owner_id: int,
    owner_name: str,
    my_card: Dict[str, Any],
    his_card_id: int,
    dry_run: bool = True,
    debug: bool = False
) -> bool:
    """
    Отправляет обмен конкретному владельцу.
    
    Args:
        session: Сессия requests
        owner_id: ID владельца
        owner_name: Имя владельца
        my_card: Информация о моей карте
        his_card_id: ID карточки в клубе
        dry_run: Тестовый режим
        debug: Режим отладки
    
    Returns:
        True если обмен отправлен успешно
    """
    my_instance_id = my_card.get("instance_id")
    my_card_name = my_card.get("name", "")
    my_card_id = my_card.get("card_id", 0)
    my_wanters = my_card.get("wanters_count", 0)
    
    if not my_instance_id:
        if debug:
            print(f"[TRADE] Missing instance_id for my card")
        return False
    
    # Dry-run режим
    if dry_run:
        print(f"[DRY-RUN] 📤 Обмен → {owner_name} (ID: {owner_id})")
        print(f"           Моя карта: {my_card_name} (ID: {my_card_id}, желающих: {my_wanters})")
        print(f"           Instance ID: {my_instance_id} ↔ card_id: {his_card_id}")
        return True
    
    # Создаем менеджер обменов
    trade_manager = TradeManager(session, debug)
    
    # Находим instance_id карточки у владельца
    if debug:
        print(f"[TRADE] Поиск instance_id карты {his_card_id} у владельца {owner_id}...")
    
    his_instance_id = trade_manager.find_partner_card_instance(owner_id, his_card_id)
    
    if not his_instance_id:
        if debug:
            print(f"[TRADE] Не найден instance_id карты {his_card_id}")
        print(f"❌ Карта не найдена у {owner_name}")
        return False
    
    if debug:
        print(f"[TRADE] Найден instance_id: {his_instance_id}")
    
    # Отправляем обмен
    success = trade_manager.create_trade(owner_id, my_instance_id, his_instance_id)
    
    if success:
        print(f"✅ Обмен отправлен → {owner_name} | Моя карта: {my_card_name} ({my_wanters} желающих)")
    else:
        print(f"❌ Ошибка отправки → {owner_name}")
    
    return success


def cancel_all_sent_trades(
    session: requests.Session,
    debug: bool = False
) -> bool:
    """
    Удобная функция для отмены всех обменов.
    
    Args:
        session: Сессия requests
        debug: Режим отладки
    
    Returns:
        True если успешно
    """
    trade_manager = TradeManager(session, debug)
    return trade_manager.cancel_all_sent_trades()