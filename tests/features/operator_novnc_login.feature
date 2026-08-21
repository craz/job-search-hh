# language: ru
Функция: Операторский login через noVNC
  Чтобы сессия HH сохранялась после ручного входа,
  система записывает marker только после явного confirm оператора.

  Сценарий: подтверждение login делает auth present
    Дано подготовлены каталоги profile и state для login
    И Chromium отмечен как установленный
    Когда оператор открывает login без реального браузера
    Тогда auth session pending_operator
    И captcha bypass выключен
    Когда оператор подтверждает login
    Тогда auth session present
    И login_ready включён
