import time
from typing import List, Dict, Any
import requests
from config import BASE_URL


def get_user_inventory(session: requests.Session, user_id: str) -> List[Dict[str, Any]]:
    """Получает все карточки пользователя"""
    all_cards = []
    offset = 0
    
    while True:
        url = f"{BASE_URL}/trades/{user_id}/availableCardsLoad"
        
        try:
            resp = session.post(
                url,
                headers={
                    "Referer": f"{BASE_URL}/trades/{user_id}",
                    "Origin": BASE_URL,
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
                data={"offset": offset},
                timeout=(4, 8)
            )
            
            if resp.status_code != 200:
                break
            
            data = resp.json()
            cards = data.get("cards", [])
            
            if not cards:
                break
            
            all_cards.extend(cards)
            offset += len(cards)
            
            if len(cards) < 60:
                break
            
            time.sleep(0.25)
            
        except Exception:
            break
    
    return all_cards