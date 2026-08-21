# language: ru
Функция: Loopback OAuth callback listener
  Чтобы не копировать authorization code вручную,
  HH слушает только 127.0.0.1 и сохраняет токен без дампа секрета.

  Сценарий: callback принимает code и сохраняет token presence
    Дано OAuth credentials и loopback redirect
    Когда listener получает authorization code
    Тогда token-status показывает access_token_present
    И отчёт не содержит сырой access_token
