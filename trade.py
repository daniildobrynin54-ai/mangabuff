"""Модуль для работы с обменами карт."""

import json
import time
from typing import Any, Dict, Optional, Set
import requests
from bs4 import BeautifulSoup
from config import BASE_URL, REQUEST_TIMEOUT, CARD_API_DELAY


class TradeManager:
    """Менеджер обменов карточками с отслеживанием состояния."""
    
    def __init__(self, session: requests.Session, debug: bool = False):
        """
        Инициализация менеджера обменов.
        
        Args:
            session: Сессия requests
            debug: Режим отладки
        """
        self.session = session
        self.debug = debug
        # Отслеживание отправленных обменов (owner_id, card_id)
        self.sent_trades: Set[tuple[int, int]] = set()
    
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
        # Проверка по статус-коду
        if response.status_code == 200:
            return True
            
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
    
    def has_trade_sent(self, receiver_id: int, card_id: int) -> bool:
        """
        Проверяет, был ли уже отправлен обмен этому владельцу на эту карту.
        
        Args:
            receiver_id: ID получателя
            card_id: ID карточки
        
        Returns:
            True если обмен уже отправлен
        """
        return (receiver_id, card_id) in self.sent_trades
    
    def mark_trade_sent(self, receiver_id: int, card_id: int) -> None:
        """
        Отмечает обмен как отправленный.
        
        Args:
            receiver_id: ID получателя
            card_id: ID карточки
        """
        self.sent_trades.add((receiver_id, card_id))
        self._log(f"Обмен помечен как отправленный: owner={receiver_id}, card_id={card_id}")
    
    def clear_sent_trades(self) -> None:
        """Очищает список отправленных обменов."""
        count = len(self.sent_trades)
        self.sent_trades.clear()
        self._log(f"Список отправленных обменов очищен ({count} записей)")
    
    def create_trade(
        self,
        receiver_id: int,
        my_instance_id: int,
        his_instance_id: int,
        max_retries: int = 2
    ) -> bool:
        """
        Отправляет обмен карточками через API с повторными попытками.
        
        Args:
            receiver_id: ID получателя обмена
            my_instance_id: Instance ID моей карточки
            his_instance_id: Instance ID карточки получателя
            max_retries: Максимальное количество попыток
        
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
        
        self._log(f"Создание обмена:")
        self._log(f"  URL: {url}")
        self._log(f"  receiver_id: {receiver_id}")
        self._log(f"  my_instance_id (creator_card_ids[]): {my_instance_id}")
        self._log(f"  his_instance_id (receiver_card_ids[]): {his_instance_id}")
        
        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    self._log(f"Повторная попытка {attempt}/{max_retries}...")
                    time.sleep(1)
                
                # Первая попытка с form data
                self._log(f"Отправка запроса (form data)...")
                response = self.session.post(
                    url,
                    data=data,
                    headers=headers,
                    allow_redirects=False,
                    timeout=REQUEST_TIMEOUT
                )
                
                self._log(f"Response status: {response.status_code}")
                self._log(f"Response headers: {dict(response.headers)}")
                self._log(f"Response body (first 500 chars): {response.text[:500]}")
                
                if self._is_success_response(response):
                    self._log("✅ Обмен успешно создан (form data)")
                    return True
                
                # Если статус 422 - карта уже в обмене
                if response.status_code == 422:
                    try:
                        error_data = response.json()
                        self._log(f"Ошибка 422: {error_data}")
                    except:
                        pass
                    self._log("❌ Карта уже участвует в обмене")
                    return False
                
                # Если статус 429 - rate limit
                if response.status_code == 429:
                    self._log("⚠️  Rate limit (429) - слишком много запросов")
                    return False
                
                # Вторая попытка с JSON payload
                self._log(f"Попытка с JSON payload...")
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
                
                self._log(f"JSON Response status: {response2.status_code}")
                
                if self._is_success_response(response2):
                    self._log("✅ Обмен успешно создан (JSON)")
                    return True
                
                if response2.status_code == 422:
                    self._log("❌ Карта уже участвует в обмене (JSON)")
                    return False
                
                self._log(f"❌ Обмен не удался. Status: {response.status_code}")
                
            except requests.RequestException as e:
                self._log(f"❌ Ошибка сети на попытке {attempt}: {e}")
                if attempt == max_retries:
                    return False
        
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
            
            if response.status_code == 200:
                # Очищаем список отправленных обменов после успешной отмены
                self.clear_sent_trades()
                return True
            
            return False
            
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
        self._log(f"Поиск instance_id карты {card_id} у владельца {partner_id}...")
        
        # Попытка 1: через страницу обменов
        instance_id = self._find_on_page(partner_id, card_id)
        if instance_id:
            self._log(f"✅ Найден на странице: instance_id={instance_id}")
            return instance_id
        
        self._log("Карта не найдена на странице, пробуем через API...")
        
        # Попытка 2: через API
        instance_id = self._find_via_api(partner_id, card_id)
        if instance_id:
            self._log(f"✅ Найден через API: instance_id={instance_id}")
            return instance_id
        
        self._log(f"❌ Instance_id карты {card_id} не найден у владельца {partner_id}")
        return None
    
    def _find_on_page(self, partner_id: int, card_id: int) -> Optional[int]:
        """Ищет карту на странице обменов."""
        try:
            url = f"{BASE_URL}/trades/offers/{partner_id}"
            self._log(f"Загрузка страницы: {url}")
            
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                self._log(f"Ошибка загрузки страницы: {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.text, "html.parser")
            cards = soup.select('[data-id], [data-card-id]')
            
            self._log(f"Найдено элементов карт на странице: {len(cards)}")
            
            for idx, card_el in enumerate(cards):
                el_card_id = (
                    card_el.get("data-card-id") or
                    card_el.get("data-cardid")
                )
                el_instance_id = (
                    card_el.get("data-id") or
                    card_el.get("data-instance-id")
                )
                
                if self.debug and idx < 5:  # Показываем первые 5 для отладки
                    self._log(f"  Карта #{idx}: card_id={el_card_id}, instance_id={el_instance_id}")
                
                if el_card_id and int(el_card_id) == card_id and el_instance_id:
                    self._log(f"✅ Совпадение найдено! instance_id={el_instance_id}")
                    return int(el_instance_id)
            
            return None
            
        except Exception as e:
            self._log(f"Ошибка при поиске на странице: {e}")
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
            
            self._log(f"Начинаем поиск через API (max {max_attempts} попыток)...")
            
            while attempts < max_attempts:
                self._log(f"API запрос #{attempts + 1}: offset={offset}")
                
                response = self.session.post(
                    url,
                    data={"offset": offset},
                    headers=headers,
                    timeout=REQUEST_TIMEOUT
                )
                
                if response.status_code != 200:
                    self._log(f"Ошибка API: {response.status_code}")
                    break
                
                data = response.json()
                cards = data.get("cards", [])
                
                self._log(f"Получено карт: {len(cards)}")
                
                if not cards:
                    self._log("Карты закончились")
                    break
                
                for idx, card in enumerate(cards):
                    c_card_id = card.get("card_id")
                    
                    # Проверяем вложенный объект
                    if isinstance(card.get("card"), dict):
                        c_card_id = card["card"].get("id") or c_card_id
                    
                    if self.debug and idx < 3:  # Показываем первые 3 для отладки
                        self._log(f"  API карта #{idx}: card_id={c_card_id}, instance_id={card.get('id')}")
                    
                    if c_card_id and int(c_card_id) == card_id:
                        instance_id = card.get("id")
                        if instance_id:
                            self._log(f"✅ Совпадение найдено через API! instance_id={instance_id}")
                            return int(instance_id)
                
                offset += len(cards)
                
                if len(cards) < 60:
                    self._log("Получено меньше 60 карт - это последняя страница")
                    break
                
                time.sleep(CARD_API_DELAY)
                attempts += 1
            
            return None
            
        except Exception as e:
            self._log(f"Ошибка при поиске через API: {e}")
            return None


def send_trade_to_owner(
    session: requests.Session,
    owner_id: int,
    owner_name: str,
    my_instance_id: int,
    his_card_id: int,
    my_card_name: str = "",
    my_wanters: int = 0,
    trade_manager: Optional[TradeManager] = None,
    dry_run: bool = True,
    debug: bool = False
) -> bool:
    """
    Отправляет обмен конкретному владельцу.
    
    Args:
        session: Сессия requests
        owner_id: ID владельца
        owner_name: Имя владельца
        my_instance_id: Instance ID моей карты
        his_card_id: ID карточки (для поиска instance_id у владельца)
        my_card_name: Название моей карты (для вывода)
        my_wanters: Количество желающих (для вывода)
        trade_manager: Менеджер обменов
        dry_run: Тестовый режим
        debug: Режим отладки
    
    Returns:
        True если обмен отправлен успешно
    """
    if not my_instance_id:
        if debug:
            print(f"[TRADE] Отсутствует my_instance_id")
        return False
    
    # Создаем менеджер если не передан
    if not trade_manager:
        trade_manager = TradeManager(session, debug)
    
    # Проверяем, не был ли уже отправлен обмен
    if not dry_run and trade_manager.has_trade_sent(owner_id, his_card_id):
        if debug:
            print(f"[TRADE] Обмен уже был отправлен {owner_name} (ID: {owner_id})")
        print(f"⏭️  Обмен уже отправлен → {owner_name}")
        return False
    
    # Dry-run режим
    if dry_run:
        print(f"[DRY-RUN] 📤 Обмен → {owner_name} (ID: {owner_id})")
        print(f"           Моя карта: {my_card_name} (желающих: {my_wanters})")
        print(f"           My instance_id: {my_instance_id}, ищем instance_id карты {his_card_id} у владельца")
        return True
    
    # Находим instance_id карточки у владельца
    his_instance_id = trade_manager.find_partner_card_instance(owner_id, his_card_id)
    
    if not his_instance_id:
        if debug:
            print(f"[TRADE] Не найден instance_id карты {his_card_id} у владельца {owner_id}")
        print(f"❌ Карта не найдена → {owner_name}")
        return False
    
    # Отправляем обмен
    success = trade_manager.create_trade(
        owner_id, 
        my_instance_id, 
        his_instance_id,
        max_retries=2
    )
    
    if success:
        # Отмечаем обмен как отправленный
        trade_manager.mark_trade_sent(owner_id, his_card_id)
        print(f"✅ Обмен отправлен → {owner_name} | Моя карта: {my_card_name} ({my_wanters} желающих)")
    else:
        print(f"❌ Ошибка отправки → {owner_name}")
    
    return success


def cancel_all_sent_trades(
    session: requests.Session,
    trade_manager: Optional[TradeManager] = None,
    debug: bool = False
) -> bool:
    """
    Удобная функция для отмены всех обменов.
    
    Args:
        session: Сессия requests
        trade_manager: Менеджер обменов
        debug: Режим отладки
    
    Returns:
        True если успешно
    """
    if not trade_manager:
        trade_manager = TradeManager(session, debug)
    
    return trade_manager.cancel_all_sent_trades()