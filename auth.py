"""Модуль авторизации."""

from typing import Optional
import requests
from bs4 import BeautifulSoup
from config import BASE_URL, USER_AGENT, REQUEST_TIMEOUT


class AuthenticationError(Exception):
    """Ошибка аутентификации."""
    pass


def get_csrf_token(session: requests.Session) -> Optional[str]:
    """
    Получает CSRF токен со страницы логина.
    
    Args:
        session: Сессия requests
    
    Returns:
        CSRF токен или None при ошибке
    """
    try:
        response = session.get(f"{BASE_URL}/login", timeout=REQUEST_TIMEOUT)
        
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Пробуем найти токен в meta теге
        token_meta = soup.select_one('meta[name="csrf-token"]')
        if token_meta:
            token = token_meta.get("content", "").strip()
            if token:
                return token
        
        # Пробуем найти токен в input поле
        token_input = soup.find("input", {"name": "_token"})
        if token_input:
            token = token_input.get("value", "").strip()
            if token:
                return token
        
        return None
        
    except requests.RequestException:
        return None


def create_session() -> requests.Session:
    """
    Создает настроенную сессию requests.
    
    Returns:
        Настроенная сессия
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru,en;q=0.8",
    })
    return session


def login(email: str, password: str) -> Optional[requests.Session]:
    """
    Выполняет вход в аккаунт.
    
    Args:
        email: Email пользователя
        password: Пароль
    
    Returns:
        Авторизованная сессия или None при ошибке
    
    Raises:
        AuthenticationError: При ошибке аутентификации
    """
    session = create_session()
    
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
        response = session.post(
            f"{BASE_URL}/login",
            data=data,
            headers=headers,
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT
        )
        
        # Проверяем успешность входа по наличию cookie сессии
        if "mangabuff_session" not in session.cookies:
            return None
        
        # Обновляем заголовки для последующих запросов
        session.headers.update({
            "X-CSRF-TOKEN": csrf_token,
            "X-Requested-With": "XMLHttpRequest"
        })
        
        return session
        
    except requests.RequestException:
        return None


def is_authenticated(session: requests.Session) -> bool:
    """
    Проверяет, авторизована ли сессия.
    
    Args:
        session: Сессия для проверки
    
    Returns:
        True если сессия авторизована
    """
    return "mangabuff_session" in session.cookies