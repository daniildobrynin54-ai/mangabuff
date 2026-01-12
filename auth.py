from typing import Optional
import requests
from bs4 import BeautifulSoup
from config import BASE_URL, USER_AGENT


def get_csrf_token(session: requests.Session) -> Optional[str]:
    """Получает CSRF токен со страницы логина"""
    try:
        response = session.get(f"{BASE_URL}/login", timeout=(4, 8))
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        token_meta = soup.select_one('meta[name="csrf-token"]')
        if token_meta and token_meta.get("content"):
            return token_meta["content"].strip()
        
        token_input = soup.find("input", {"name": "_token"})
        if token_input and token_input.get("value"):
            return token_input["value"].strip()
        
        return None
    except Exception:
        return None


def login(email: str, password: str) -> Optional[requests.Session]:
    """Выполняет вход в аккаунт"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru,en;q=0.8",
    })
    
    csrf_token = get_csrf_token(session)
    if not csrf_token:
        return None
    
    headers = {
        "Referer": f"{BASE_URL}/login",
        "Origin": BASE_URL,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRF-TOKEN": csrf_token,
    }
    
    data = {
        "email": email,
        "password": password,
        "_token": csrf_token
    }
    
    try:
        resp = session.post(
            f"{BASE_URL}/login",
            data=data,
            headers=headers,
            allow_redirects=True,
            timeout=(4, 8)
        )
        
        if "mangabuff_session" in session.cookies.keys():
            session.headers["X-CSRF-TOKEN"] = csrf_token
            session.headers["X-Requested-With"] = "XMLHttpRequest"
            return session
        else:
            return None
            
    except Exception:
        return None