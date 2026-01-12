import time
import re
from typing import List, Tuple, Optional, Callable
import requests
from bs4 import BeautifulSoup
from config import BASE_URL


def find_available_owners_on_page(session: requests.Session, card_id: str, page: int = 1) -> Tuple[List[dict], bool]:
    """
    Находит владельцев карты на конкретной странице
    
    Args:
        session: Сессия requests
        card_id: ID карты
        page: Номер страницы
    
    Returns:
        Кортеж (список владельцев, есть ли следующая страница)
        Владелец = {"id": str, "name": str}
    """
    available_owners = []
    
    url = f"{BASE_URL}/cards/{card_id}/users"
    if page > 1:
        url += f"?page={page}"
    
    try:
        resp = session.get(url, timeout=(4, 8))
        if resp.status_code != 200:
            return ([], False)
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Находим всех владельцев на странице
        owners = soup.select('.card-show__owner')
        
        if not owners:
            return ([], False)
        
        # На первой странице пропускаем первых 6 владельцев
        start_index = 6 if page == 1 else 0
        
        for idx, owner in enumerate(owners):
            # Пропускаем первых 6 на первой странице
            if page == 1 and idx < 6:
                continue
            
            # Проверяем, что владелец онлайн
            owner_classes = owner.get('class', [])
            if 'card-show__owner--online' not in owner_classes:
                continue
            
            # Проверяем отсутствие замка
            lock_icons = owner.select('.card-show__owner-icon .icon-lock')
            if lock_icons:
                continue
            
            # Извлекаем ID пользователя из href
            href = owner.get('href', '')
            match = re.search(r'/users/(\d+)', href)
            if match:
                user_id = match.group(1)
                
                # Получаем имя пользователя
                name_elem = owner.select_one('.card-show__owner-name')
                user_name = name_elem.get_text(strip=True) if name_elem else "Неизвестно"
                
                available_owners.append({
                    "id": user_id,
                    "name": user_name
                })
        
        # Проверяем наличие следующей страницы
        pagination = soup.select('.pagination__button a')
        has_next = False
        
        for link in pagination:
            text = link.get_text(strip=True)
            if text == "Вперёд":
                has_next = True
                break
        
        return (available_owners, has_next)
        
    except Exception as e:
        return ([], False)


def process_owners_page_by_page(
    session: requests.Session,
    card_id: str,
    boost_card: dict,
    output_dir: str,
    select_card_func: Callable,
    send_trade_func: Optional[Callable] = None,
    monitor_obj = None,
    dry_run: bool = True,
    debug: bool = False
) -> int:
    """
    Обрабатывает владельцев карты постранично
    
    Алгоритм:
    1. Парсит страницу владельцев
    2. Для каждого владельца подбирает карту
    3. Отправляет обмены (если функция передана)
    4. Переходит к следующей странице
    5. Если карта изменилась (обнаружено через monitor) - начинает заново
    
    Args:
        session: Сессия requests
        card_id: ID карты
        boost_card: Информация о карте для буста
        output_dir: Директория для файлов
        select_card_func: Функция подбора карты (из card_selector)
        send_trade_func: Функция отправки обмена (опционально)
        monitor_obj: Объект монитора для проверки изменения карты
        dry_run: Если True, не отправляет реальные обмены
        debug: Режим отладки
    
    Returns:
        Общее количество обработанных владельцев
    """
    import random
    
    total_processed = 0
    total_trades_sent = 0
    page = 1
    
    # Минимальная задержка между обменами - 11 секунд
    MIN_TRADE_DELAY = 11.0
    last_trade_time = 0.0
    
    print(f"🔍 Поиск доступных владельцев карты {card_id}...")
    print(f"📊 Режим: {'DRY-RUN (тестовый)' if dry_run else 'БОЕВОЙ (реальные обмены)'}\n")
    
    while True:
        # Проверяем, не изменилась ли карта через монитор
        if monitor_obj and monitor_obj.card_changed:
            print("\n🔄 Обнаружена новая карта! Перезапуск обработки с первой страницы...")
            monitor_obj.card_changed = False
            return total_processed  # Возвращаем управление для перезапуска
        
        # Парсим страницу
        page_owners, has_next = find_available_owners_on_page(session, card_id, page)
        
        if page_owners:
            print(f"📊 Страница {page}: найдено владельцев - {len(page_owners)}")
            
            # Обрабатываем каждого владельца
            for idx, owner in enumerate(page_owners, 1):
                # Проверяем снова перед каждым владельцем
                if monitor_obj and monitor_obj.card_changed:
                    print("\n🔄 Обнаружена новая карта! Перезапуск обработки с первой страницы...")
                    monitor_obj.card_changed = False
                    return total_processed
                
                # Подбираем карту для обмена
                selected_card = select_card_func(session, boost_card, output_dir)
                
                if selected_card:
                    card_name = selected_card.get('name', '')
                    card_id_val = selected_card.get('card_id', 0)
                    wanters = selected_card.get('wanters_count', 0)
                    
                    print(f"   [{idx}/{len(page_owners)}] {owner['name']} → {card_name} ({wanters} желающих)")
                    
                    # Отправляем обмен, если функция передана
                    if send_trade_func:
                        # Ждем минимум 11 секунд с предыдущего обмена
                        if not dry_run:
                            current_time = time.time()
                            time_since_last = current_time - last_trade_time
                            if time_since_last < MIN_TRADE_DELAY:
                                sleep_time = MIN_TRADE_DELAY - time_since_last
                                time.sleep(sleep_time)
                        
                        # Вызываем функцию отправки обмена
                        success = send_trade_func(
                            session=session,
                            owner_id=int(owner['id']),
                            owner_name=owner['name'],
                            my_card=selected_card,
                            his_card_id=int(card_id),
                            dry_run=dry_run,
                            debug=debug
                        )
                        
                        if success:
                            total_trades_sent += 1
                            if not dry_run:
                                last_trade_time = time.time()
                                # Добавляем небольшую случайную задержку
                                additional_delay = random.uniform(0.5, 2.0)
                                time.sleep(additional_delay)
                        else:
                            if not dry_run:
                                print(f"      ⚠️  Ошибка отправки")
                    else:
                        print(f"      ⚠️  Функция отправки не передана")
                else:
                    print(f"   [{idx}/{len(page_owners)}] {owner['name']} → ❌ Не удалось подобрать карту")
            
            total_processed += len(page_owners)
            print()  # Пустая строка для разделения
        else:
            print(f"📊 Страница {page}: подходящих владельцев - 0")
            print()
        
        # Если нет следующей страницы - выходим
        if not has_next:
            print(f"✅ Обработка завершена:")
            print(f"   Проверено владельцев: {total_processed}")
            print(f"   Отправлено обменов: {total_trades_sent}")
            break
        
        # Задержка перед следующей страницей
        time.sleep(0.5)
        page += 1
    
    return total_processed


def find_all_available_owners(session: requests.Session, card_id: str) -> List[dict]:
    """
    Находит всех доступных владельцев карты (без обработки)
    Используется когда нужен просто список всех владельцев
    
    Args:
        session: Сессия requests
        card_id: ID карты
    
    Returns:
        Список владельцев [{"id": str, "name": str}, ...]
    """
    all_owners = []
    page = 1
    
    print(f"🔍 Поиск доступных владельцев карты {card_id}...")
    
    while True:
        page_owners, has_next = find_available_owners_on_page(session, card_id, page)
        
        if page_owners:
            print(f"📊 Страница {page}: подходящих владельцев - {len(page_owners)}:")
            for owner in page_owners:
                print(f"{owner['name']} (ID: {owner['id']})")
            print()
            
            all_owners.extend(page_owners)
        else:
            print(f"📊 Страница {page}: подходящих владельцев - 0")
            print()
        
        # Если нет следующей страницы - выходим
        if not has_next:
            print(f"✅ Всего найдено владельцев: {len(all_owners)}")
            break
        
        time.sleep(0.5)
        page += 1
    
    return all_owners