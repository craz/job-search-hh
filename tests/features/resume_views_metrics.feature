# language: ru
Функция: Richer metrics из resumes/mine
  Чтобы дневные метрики включали просмотры резюме,
  live sync читает GET /resumes/mine вместе с negotiations.

  Сценарий: metrics sync получает views_total из resumes
    Дано fake authenticated HH отдаёт negotiations и resumes
    Когда оператор запускает live metrics sync
    Тогда Core получает Daily Metric с views_total
    И notes указывают resumes_mine
    И HH write не выполнялся
