import json
import time
from typing import Optional, Dict, Any
import requests
from config import BASE_URL


def create_trade(session: requests.Session, receiver_id: int, my_instance_id: int, his_instance_id: int, debug: bool = False) -> bool:
    """
    Отправляет обмен карточками через API
    
    Args:
        session: Сессия requests
        receiver_id: ID получателя обмена
        my_instance_id: Instance ID моей карточки
        his_instance_id: Instance ID карточки получателя
        debug: Режим отладки
    
    Returns:
        True если обмен успешно отправлен, False в случае ошибки
    """
    url = f"{BASE_URL}/trades/create"
    
    headers = {
        "Referer": f"{BASE_URL}/trades/offers/{receiver_id}",
        "Origin": BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    
    # Добавляем CSRF токен из сессии
    if "X-CSRF-TOKEN" in session.headers:
        headers["X-CSRF-TOKEN"] = session.headers["X-CSRF-TOKEN"]
    
    # Формируем данные запроса
    data = [
        ("receiver_id", int(receiver_id)),
        ("creator_card_ids[]", int(my_instance_id)),
        ("receiver_card_ids[]", int(his_instance_id)),
    ]
    
    if debug:
        print(f"[TRADE] Отправка обмена:")
        print(f"        receiver_id: {receiver_id}")
        print(f"        creator_card_ids[]: {my_instance_id}")
        print(f"        receiver_card_ids[]: {his_instance_id}")
    
    try:
        resp = session.post(
            url,
            data=data,
            headers=headers,
            allow_redirects=False,
            timeout=(4, 8)
        )
        
        if debug:
            print(f"[TRADE] Response status: {resp.status_code}")
            print(f"[TRADE] Response headers: {dict(resp.headers)}")
            print(f"[TRADE] Response body: {resp.text[:500]}")
        
        # Проверка успешности по редиректу
        if resp.status_code in (301, 302):
            location = resp.headers.get("Location", "")
            if "/trades/" in location:
                return True
        
        # Проверка успешности по JSON ответу
        try:
            j = resp.json()
            if isinstance(j, dict):
                # Проверяем явные индикаторы успеха
                if j.get("success") or j.get("ok"):
                    return True
                
                # Проверяем наличие объекта trade с ID
                if isinstance(j.get("trade"), dict) and j["trade"].get("id"):
                    return True
                
                # Проверяем текст сообщения
                body = json.dumps(j).lower()
                if "успеш" in body or "отправ" in body or "создан" in body:
                    return True
        except ValueError:
            pass
        
        # Проверка успешности по тексту ответа
        body = (resp.text or "").lower()
        if "успеш" in body or "отправ" in body or "создан" in body:
            return True
        
        # Дополнительная попытка с JSON payload
        json_payload = {
            "receiver_id": receiver_id,
            "creator_card_ids": [my_instance_id],
            "receiver_card_ids": [his_instance_id],
        }
        
        resp2 = session.post(
            url,
            json=json_payload,
            headers={**headers, "Content-Type": "application/json"},
            allow_redirects=False,
            timeout=(4, 8)
        )
        
        if resp2.status_code in (301, 302) and "/trades/" in resp2.headers.get("Location", ""):
            return True
        
        try:
            j2 = resp2.json()
            if isinstance(j2, dict):
                if j2.get("success") or j2.get("ok"):
                    return True
                if isinstance(j2.get("trade"), dict) and j2["trade"].get("id"):
                    return True
        except ValueError:
            pass
        
        if debug:
            print(f"[TRADE] Trade failed. Status: {resp.status_code}")
            print(f"[TRADE] Response: {resp.text[:200]}")
        
        return False
        
    except requests.RequestException as e:
        if debug:
            print(f"[TRADE] Network error: {e}")
        return False


def cancel_all_sent_trades(session: requests.Session, debug: bool = False) -> bool:
    """
    Отменяет все отправленные обмены
    
    Args:
        session: Сессия requests
        debug: Режим отладки
    
    Returns:
        True если запрос успешен, False в случае ошибки
    """
    url = f"{BASE_URL}/trades/rejectAll?type_trade=sender"
    
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": f"{BASE_URL}/trades/offers",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    
    if debug:
        print(f"[CANCEL] Отмена всех отправленных обменов...")
    
    try:
        resp = session.get(
            url,
            headers=headers,
            allow_redirects=True,
            timeout=(4, 8)
        )
        
        if debug:
            print(f"[CANCEL] Response status: {resp.status_code}")
            print(f"[CANCEL] Response URL: {resp.url}")
        
        # Проверяем успешность
        if resp.status_code == 200:
            return True
        
        return False
        
    except requests.RequestException as e:
        if debug:
            print(f"[CANCEL] Network error: {e}")
        return False


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
    Отправляет обмен конкретному владельцу
    
    Args:
        session: Сессия requests
        owner_id: ID владельца
        owner_name: Имя владельца
        my_card: Словарь с информацией о моей карте (должен содержать instance_id)
        his_card_id: ID карточки в клубе (для которой ищем владельцев)
        dry_run: Если True, не отправляет реальные обмены
        debug: Режим отладки
    
    Returns:
        True если обмен отправлен успешно (или в dry_run режиме)
    """
    my_instance_id = my_card.get("instance_id")
    my_card_name = my_card.get("name", "")
    my_card_id = my_card.get("card_id", 0)
    my_wanters = my_card.get("wanters_count", 0)
    
    if not my_instance_id:
        if debug:
            print(f"[TRADE] Missing instance_id for my card")
        return False
    
    # В dry-run режиме просто выводим информацию
    if dry_run:
        print(f"[DRY-RUN] 📤 Обмен → {owner_name} (ID: {owner_id})")
        print(f"           Моя карта: {my_card_name} (ID: {my_card_id}, желающих: {my_wanters})")
        print(f"           Instance ID: {my_instance_id} ↔ card_id: {his_card_id}")
        return True
    
    # Находим instance_id карточки у владельца
    if debug:
        print(f"[TRADE] Поиск instance_id карты {his_card_id} у владельца {owner_id}...")
    
    his_instance_id = find_partner_card_instance(
        session=session,
        partner_id=owner_id,
        card_id=his_card_id,
        debug=debug
    )
    
    if not his_instance_id:
        if debug:
            print(f"[TRADE] Не найден instance_id карты {his_card_id} у владельца {owner_id}")
        print(f"❌ Карта не найдена у {owner_name}")
        return False
    
    if debug:
        print(f"[TRADE] Найден instance_id: {his_instance_id}")
    
    # Отправляем обмен
    success = create_trade(
        session=session,
        receiver_id=owner_id,
        my_instance_id=my_instance_id,
        his_instance_id=his_instance_id,
        debug=debug
    )
    
    if success:
        print(f"✅ Обмен отправлен → {owner_name} | Моя карта: {my_card_name} ({my_wanters} желающих)")
    else:
        print(f"❌ Ошибка отправки → {owner_name}")
    
    return success


def find_partner_card_instance(
    session: requests.Session,
    partner_id: int,
    card_id: int,
    debug: bool = False
) -> Optional[int]:
    """
    Находит instance_id карточки у партнера
    
    Args:
        session: Сессия requests
        partner_id: ID партнера
        card_id: ID карточки
        debug: Режим отладки
    
    Returns:
        Instance ID карточки или None если не найдена
    """
    try:
        # Пробуем получить карты через страницу обменов
        url = f"{BASE_URL}/trades/offers/{partner_id}"
        resp = session.get(url, timeout=(4, 8))
        
        if resp.status_code != 200:
            return None
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Ищем карточки на странице
        cards = soup.select('[data-id], [data-card-id]')
        
        for card_el in cards:
            el_card_id = card_el.get("data-card-id") or card_el.get("data-cardid")
            el_instance_id = card_el.get("data-id") or card_el.get("data-instance-id")
            
            if el_card_id and int(el_card_id) == card_id and el_instance_id:
                return int(el_instance_id)
        
        # Если не нашли на странице, пробуем через API
        api_url = f"{BASE_URL}/trades/{partner_id}/availableCardsLoad"
        
        headers = {
            "Referer": f"{BASE_URL}/trades/offers/{partner_id}",
            "Origin": BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        
        if "X-CSRF-TOKEN" in session.headers:
            headers["X-CSRF-TOKEN"] = session.headers["X-CSRF-TOKEN"]
        
        offset = 0
        max_attempts = 50
        attempts = 0
        
        while attempts < max_attempts:
            try:
                resp = session.post(
                    api_url,
                    data={"offset": offset},
                    headers=headers,
                    timeout=(4, 8)
                )
                
                if resp.status_code != 200:
                    break
                
                data = resp.json()
                cards = data.get("cards", [])
                
                if not cards:
                    break
                
                for card in cards:
                    c_card_id = card.get("card_id")
                    if isinstance(card.get("card"), dict):
                        c_card_id = card["card"].get("id") or c_card_id
                    
                    if c_card_id and int(c_card_id) == card_id:
                        instance_id = card.get("id")
                        if instance_id:
                            return int(instance_id)
                
                offset += len(cards)
                
                if len(cards) < 60:
                    break
                
                time.sleep(0.15)
                attempts += 1
                
            except Exception as e:
                if debug:
                    print(f"[TRADE] Error fetching cards: {e}")
                break
        
        return None
        
    except Exception as e:
        if debug:
            print(f"[TRADE] Error finding instance: {e}")
        return None