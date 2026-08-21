# language: ru
Функция: Live authenticated HH read без записи
  Чтобы синхронизировать переговоры после confirmed session,
  система делает только GET и пишет в Core.

  Сценарий: authenticated applications sync без HH write
    Дано confirmed session и access token
    И fake authenticated HH отдаёт переговоры
    Когда оператор запускает live applications sync
    Тогда Core получает Application со source hh
    И отчёт помечает transport authenticated_api
    И HH write не выполнялся
