import time
import requests
from bs4 import BeautifulSoup
from config import (
    BASE_URL,
    OWNERS_PER_PAGE,
    WANTS_PER_PAGE,
    OWNERS_APPROXIMATE_THRESHOLD,
    WANTS_APPROXIMATE_THRESHOLD,
    OWNERS_LAST_PAGE_ESTIMATE,
    WANTS_LAST_PAGE_ESTIMATE
)


def parse_page_numbers(soup: BeautifulSoup) -> int:
    """Извлекает максимальный номер страницы из пагинации"""
    page_elements = soup.select('.pagination__button, .pagination > li > a, .pagination > li, .paginator a')
    pages = []
    
    for el in page_elements:
        text = el.get_text(strip=True)
        try:
            num = int(text)
            if num > 0:
                pages.append(num)
        except ValueError:
            continue
    
    return max(pages) if pages else 1


def count_owners(session: requests.Session, card_id: str, force_accurate: bool = False) -> int:
    """Подсчитывает владельцев карты с оптимизацией из content.js"""
    try:
        url = f"{BASE_URL}/cards/{card_id}/users"
        
        resp = session.get(url, timeout=(4, 8))
        if resp.status_code != 200:
            return -1
        
        soup = BeautifulSoup(resp.text, "html.parser")
        max_page = parse_page_numbers(soup)
        
        if max_page == 1:
            count = len(soup.select('.card-show__owner'))
            return count
        
        if max_page >= OWNERS_APPROXIMATE_THRESHOLD and not force_accurate:
            approximate_count = (max_page - 1) * OWNERS_PER_PAGE + OWNERS_LAST_PAGE_ESTIMATE
            return approximate_count
        
        time.sleep(0.8)
        
        last_page_url = f"{url}?page={max_page}"
        last_resp = session.get(last_page_url, timeout=(4, 8))
        
        if last_resp.status_code != 200:
            return (max_page - 1) * OWNERS_PER_PAGE + OWNERS_LAST_PAGE_ESTIMATE
        
        last_soup = BeautifulSoup(last_resp.text, "html.parser")
        last_page_count = len(last_soup.select('.card-show__owner'))
        exact_count = (max_page - 1) * OWNERS_PER_PAGE + last_page_count
        
        return exact_count
        
    except Exception:
        return -1


def count_wants(session: requests.Session, card_id: str, force_accurate: bool = False) -> int:
    """Подсчитывает желающих карту с оптимизацией из content.js"""
    try:
        url = f"{BASE_URL}/cards/{card_id}/offers/want"
        
        resp = session.get(url, timeout=(4, 8))
        if resp.status_code != 200:
            return -1
        
        soup = BeautifulSoup(resp.text, "html.parser")
        max_page = parse_page_numbers(soup)
        
        selectors = '.profile__friends-item, .users-list__item, .user-card'
        
        if max_page == 1:
            count = len(soup.select(selectors))
            return count
        
        if max_page >= WANTS_APPROXIMATE_THRESHOLD and not force_accurate:
            approximate_count = (max_page - 1) * WANTS_PER_PAGE + WANTS_LAST_PAGE_ESTIMATE
            return approximate_count
        
        time.sleep(0.8)
        
        last_page_url = f"{url}?page={max_page}"
        last_resp = session.get(last_page_url, timeout=(4, 8))
        
        if last_resp.status_code != 200:
            return (max_page - 1) * WANTS_PER_PAGE + WANTS_LAST_PAGE_ESTIMATE
        
        last_soup = BeautifulSoup(last_resp.text, "html.parser")
        last_page_count = len(last_soup.select(selectors))
        exact_count = (max_page - 1) * WANTS_PER_PAGE + last_page_count
        
        return exact_count
        
    except Exception:
        return -1