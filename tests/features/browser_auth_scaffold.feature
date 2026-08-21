# language: ru
Функция: Browser/auth scaffold без установки браузера
  Как оператор системы поиска работы
  Я хочу видеть scaffold-состояние сессии HH
  Чтобы не принять незавершённый browser runtime за готовый вход

  Сценарий: Session status описывает scaffold без Chromium
    Дано подготовлены каталоги profile и state
    Когда оператор запрашивает session status
    Тогда chromium не установлен
    И profile lock доступен
    И auth session отсутствует
    И session status держит внешние записи выключенными
