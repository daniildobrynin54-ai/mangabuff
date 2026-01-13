"""Парсер владельцев карт."""

import random
import re
import time
from typing import Callable, Dict, List, Optional, Tuple
import requests
from bs4 import BeautifulSoup
from config import (
    BASE_URL,
    REQUEST_TIMEOUT,
    PAGE_DELAY,
    MIN_TRADE_DELAY,
    TRADE_RANDOM_DELAY_MIN,
    TRADE_RANDOM_DELAY_MAX,
    FIRST_PAGE_SKIP_OWNERS
)
from trade import TradeManager


class Owner:
    """Класс владельца карты."""
    
    def __init__(self, owner_id: str, name: str):
        """Инициализация владельца."""
        self.id = owner_id
        self.name = name
    
    def to_dict(self) -> Dict[str, str]:
        """Преобразует в словарь."""
        return {"id": self.id, "name": self.name}


class OwnersParser:
    """Парсер для поиска владельцев карт."""
    
    def __init__(self, session: requests.Session):
        """Инициализация парсера."""
        self.session = session
    
    def _extract_user_id(self, owner_element) -> Optional[str]:
        """Извлекает ID пользователя из элемента."""
        href = owner_element.get('href', '')
        match = re.search(r'/users/(\d+)', href)
        return match.group(1) if match else None
    
    def _extract_user_name(self, owner_element) -> str:
        """Извлекает имя пользователя из элемента."""
        name_elem = owner_element.select_one('.card-show__owner-name')
        return name_elem.get_text(strip=True) if name_elem else "Неизвестно"
    
    def _is_owner_available(self, owner_element) -> bool:
        """Проверяет, доступен ли владелец для обмена."""
        owner_classes = owner_element.get('class', [])
        
        if 'card-show__owner--online' not in owner_classes:
            return False
        
        lock_icons = owner_element.select('.card-show__owner-icon .icon-lock')
        if lock_icons:
            return False
        
        return True
    
    def find_owners_on_page(
        self,
        card_id: str,
        page: int = 1
    ) -> Tuple[List[Owner], bool]:
        """Находит владельцев карты на конкретной странице."""
        url = f"{BASE_URL}/cards/{card_id}/users"
        if page > 1:
            url += f"?page={page}"
        
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                return [], False
            
            soup = BeautifulSoup(response.text, "html.parser")
            owner_elements = soup.select('.card-show__owner')
            
            if not owner_elements:
                return [], False
            
            start_index = FIRST_PAGE_SKIP_OWNERS if page == 1 else 0
            available_owners = []
            
            for idx, owner_elem in enumerate(owner_elements):
                if page == 1 and idx < start_index:
                    continue
                
                if not self._is_owner_available(owner_elem):
                    continue
                
                user_id = self._extract_user_id(owner_elem)
                if not user_id:
                    continue
                
                user_name = self._extract_user_name(owner_elem)
                available_owners.append(Owner(user_id, user_name))
            
            has_next = self._has_next_page(soup)
            
            return available_owners, has_next
            
        except requests.RequestException:
            return [], False
    
    def _has_next_page(self, soup: BeautifulSoup) -> bool:
        """Проверяет наличие следующей страницы."""
        pagination_links = soup.select('.pagination__button a')
        
        for link in pagination_links:
            text = link.get_text(strip=True)
            if text == "Вперёд":
                return True
        
        return False
    
    def find_all_owners(self, card_id: str) -> List[Owner]:
        """Находит всех доступных владельцев карты."""
        all_owners = []
        page = 1
        
        print(f"🔍 Поиск доступных владельцев карты {card_id}...")
        
        while True:
            owners, has_next = self.find_owners_on_page(card_id, page)
            
            if owners:
                print(f"📊 Страница {page}: найдено владельцев - {len(owners)}:")
                for owner in owners:
                    print(f"   {owner.name} (ID: {owner.id})")
                print()
                
                all_owners.extend(owners)
            else:
                print(f"📊 Страница {page}: подходящих владельцев - 0")
                print()
            
            if not has_next:
                print(f"✅ Всего найдено владельцев: {len(all_owners)}")
                break
            
            time.sleep(PAGE_DELAY)
            page += 1
        
        return all_owners


class OwnersProcessor:
    """Процессор для обработки владельцев."""
    
    def __init__(
        self,
        session: requests.Session,
        select_card_func: Callable,
        send_trade_func: Optional[Callable] = None,
        dry_run: bool = True,
        debug: bool = False
    ):
        """Инициализация процессора."""
        self.session = session
        self.parser = OwnersParser(session)
        self.select_card_func = select_card_func
        self.send_trade_func = send_trade_func
        self.dry_run = dry_run
        self.debug = debug
        self.last_trade_time = 0.0
        self.trade_manager = TradeManager(session, debug) if not dry_run else None
    
    def reset_state(self) -> None:
        """Сбрасывает состояние процессора при смене карты."""
        if self.trade_manager:
            self.trade_manager.clear_sent_trades()
        self.last_trade_time = 0.0
    
    def _wait_before_trade(self) -> None:
        """Ожидает перед следующим обменом."""
        if self.dry_run:
            return
        
        current_time = time.time()
        time_since_last = current_time - self.last_trade_time
        
        if time_since_last < MIN_TRADE_DELAY:
            sleep_time = MIN_TRADE_DELAY - time_since_last
            time.sleep(sleep_time)
    
    def _add_random_delay(self) -> None:
        """Добавляет случайную задержку после обмена."""
        if not self.dry_run:
            delay = random.uniform(TRADE_RANDOM_DELAY_MIN, TRADE_RANDOM_DELAY_MAX)
            time.sleep(delay)
    
    def process_owner(
        self,
        owner: Owner,
        boost_card: Dict,
        output_dir: str,
        his_card_id: int,
        index: int,
        total: int,
        monitor_obj=None
    ) -> tuple[bool, bool]:
        """Обрабатывает одного владельца."""
        if monitor_obj and monitor_obj.card_changed:
            print(f"\n⚠️  Карта изменилась! Прерываем обработку владельца {owner.name}")
            return False, True
        
        selected_card = self.select_card_func(
            self.session,
            boost_card,
            output_dir,
            trade_manager=self.trade_manager
        )
        
        if not selected_card:
            print(f"   [{index}/{total}] {owner.name} → ❌ Не удалось подобрать карту")
            if self.trade_manager:
                locked_count = self.trade_manager.get_locked_cards_count()
                if locked_count > 0:
                    print(f"      ℹ️  Заблокировано карт: {locked_count}")
            return False, False
        
        card_name = selected_card.get('name', '')
        wanters = selected_card.get('wanters_count', 0)
        my_instance_id = selected_card.get('instance_id')
        
        print(f"   [{index}/{total}] {owner.name} → {card_name} ({wanters} желающих)")
        
        if not self.send_trade_func:
            print(f"      ⚠️  Функция отправки не передана")
            return False, False
        
        if not my_instance_id:
            print(f"      ⚠️  Не найден instance_id выбранной карты")
            return False, False
        
        self._wait_before_trade()
        
        if monitor_obj and monitor_obj.card_changed:
            print(f"\n⚠️  Карта изменилась! Прерываем перед отправкой обмена")
            return False, True
        
        success = self.send_trade_func(
            session=self.session,
            owner_id=int(owner.id),
            owner_name=owner.name,
            my_instance_id=my_instance_id,
            his_card_id=his_card_id,
            my_card_name=card_name,
            my_wanters=wanters,
            trade_manager=self.trade_manager,
            dry_run=self.dry_run,
            debug=self.debug
        )
        
        if success:
            if not self.dry_run:
                self.last_trade_time = time.time()
                self._add_random_delay()
            return True, False
        else:
            if not self.dry_run:
                print(f"      ⚠️  Ошибка отправки")
            return False, False
    
    def process_page_by_page(
        self,
        card_id: str,
        boost_card: Dict,
        output_dir: str,
        monitor_obj=None
    ) -> int:
        """Обрабатывает владельцев постранично."""
        total_processed = 0
        total_trades_sent = 0
        page = 1
        
        print(f"🔍 Поиск доступных владельцев карты {card_id}...")
        print(f"📊 Режим: {'DRY-RUN (тестовый)' if self.dry_run else 'БОЕВОЙ (реальные обмены)'}\n")
        
        while True:
            if monitor_obj and monitor_obj.card_changed:
                print("\n🔄 Обнаружена новая карта! Прерываем обработку страницы...")
                return total_processed
            
            owners, has_next = self.parser.find_owners_on_page(card_id, page)
            
            if owners:
                print(f"📊 Страница {page}: найдено владельцев - {len(owners)}")
                
                for idx, owner in enumerate(owners, 1):
                    success, should_break = self.process_owner(
                        owner,
                        boost_card,
                        output_dir,
                        int(card_id),
                        idx,
                        len(owners),
                        monitor_obj
                    )
                    
                    if should_break:
                        print("\n🔄 Прерывание обработки для перезапуска с новой картой...")
                        return total_processed
                    
                    if success:
                        total_trades_sent += 1
                
                total_processed += len(owners)
                print()
            else:
                print(f"📊 Страница {page}: подходящих владельцев - 0\n")
            
            if not has_next:
                print(f"✅ Обработка завершена:")
                print(f"   Проверено владельцев: {total_processed}")
                print(f"   Отправлено обменов: {total_trades_sent}")
                break
            
            if monitor_obj and monitor_obj.card_changed:
                print("\n🔄 Обнаружена новая карта! Прерываем перед следующей страницей...")
                return total_processed
            
            time.sleep(PAGE_DELAY)
            page += 1
        
        return total_processed


def process_owners_page_by_page(
    session: requests.Session,
    card_id: str,
    boost_card: Dict,
    output_dir: str,
    select_card_func: Callable,
    send_trade_func: Optional[Callable] = None,
    monitor_obj=None,
    processor: Optional['OwnersProcessor'] = None,
    dry_run: bool = True,
    debug: bool = False
) -> int:
    """Удобная функция для постраничной обработки владельцев."""
    if not processor:
        processor = OwnersProcessor(
            session=session,
            select_card_func=select_card_func,
            send_trade_func=send_trade_func,
            dry_run=dry_run,
            debug=debug
        )
    
    return processor.process_page_by_page(
        card_id=card_id,
        boost_card=boost_card,
        output_dir=output_dir,
        monitor_obj=monitor_obj
    )


def find_all_available_owners(
    session: requests.Session,
    card_id: str
) -> List[Dict[str, str]]:
    """Удобная функция для поиска всех владельцев."""
    parser = OwnersParser(session)
    owners = parser.find_all_owners(card_id)
    return [owner.to_dict() for owner in owners]