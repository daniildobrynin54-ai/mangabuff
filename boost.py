import re
import time
from typing import Optional, Dict, Any
import requests
from bs4 import BeautifulSoup
from config import BASE_URL
from inventory import get_user_inventory
from parsers import count_owners, count_wants


def get_boost_card_info(session: requests.Session, boost_url: str) -> Optional[Dict[str, Any]]:
    """Получает полную информацию о карточке для вклада в клуб"""
    
    if not boost_url.startswith("http"):
        boost_url = f"{BASE_URL}{boost_url}"
    
    try:
        resp = session.get(boost_url, timeout=(4, 8))
        if resp.status_code != 200:
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        card_link = soup.select_one('a.button.button--block[href*="/cards/"]')
        if not card_link:
            return None
        
        card_href = card_link["href"]
        
        match = re.search(r"/cards/(\d+)", card_href)
        if not match:
            return None
        
        card_id = match.group(1)
        
        card_page_url = f"{BASE_URL}/cards/{card_id}"
        card_resp = session.get(card_page_url, timeout=(4, 8))
        
        card_name = ""
        card_rank = ""
        instance_id = 0
        
        if card_resp.status_code == 200:
            card_soup = BeautifulSoup(card_resp.text, "html.parser")
            
            title_el = card_soup.select_one('h1.card-show__title, h1[class*="title"], .card-show__name')
            if title_el:
                card_name = title_el.get_text(strip=True)
            
            rank_el = card_soup.select_one('.card-show__grade, .card-grade, [class*="grade"], [data-rank]')
            if rank_el:
                if rank_el.has_attr("data-rank"):
                    card_rank = rank_el.get("data-rank", "")
                else:
                    card_rank = rank_el.get_text(strip=True)
                card_rank = re.sub(r'[^A-Z]', '', card_rank.upper())
        
        if not card_name or not card_rank:
            try:
                users_resp = session.get(f"{BASE_URL}/cards/{card_id}/users", timeout=(4, 8))
                if users_resp.status_code == 200:
                    users_soup = BeautifulSoup(users_resp.text, "html.parser")
                    user_links = [a for a in users_soup.find_all("a", href=True) if a["href"].startswith("/users/")]
                    
                    if user_links:
                        last_user_link = user_links[-1]
                        owner_id = last_user_link["href"].rstrip("/").split("/")[-1]
                        owner_cards = get_user_inventory(session, owner_id)
                        
                        for card in owner_cards:
                            if int(card.get("card_id") or 0) == int(card_id):
                                instance_id = card.get("id") or 0
                                
                                if not card_name:
                                    card_name = card.get("title") or card.get("name") or ""
                                if not card_rank:
                                    card_rank = card.get("rank") or card.get("grade") or ""
                                
                                if isinstance(card.get("card"), dict):
                                    if not card_name:
                                        card_name = card["card"].get("name") or card["card"].get("title") or ""
                                    if not card_rank:
                                        card_rank = card["card"].get("rank") or card["card"].get("grade") or ""
                                
                                break
            except Exception:
                pass
        
        owners_count = count_owners(session, card_id, force_accurate=False)
        wants_count = count_wants(session, card_id, force_accurate=False)
        
        card_info = {
            "name": card_name,
            "id": instance_id,
            "card_id": int(card_id),
            "rank": card_rank,
            "wanters_count": wants_count,
            "owners_count": owners_count,
            "card_url": f"{BASE_URL}/cards/{card_id}/users",
            "timestamp": time.time()
        }
        
        return card_info
        
    except Exception:
        return None