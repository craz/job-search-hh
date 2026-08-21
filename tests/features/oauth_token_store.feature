# language: ru
Функция: Безопасное хранение OAuth access token
  Чтобы live API reads работали после operator login,
  система сохраняет токен без печати секрета в JSON.

  Сценарий: set-token сохраняет presence без дампа
    Дано пустой HH state для token
    Когда оператор сохраняет access token из файла
    Тогда token-status показывает access_token_present
    И JSON ответа не содержит сырой access_token
