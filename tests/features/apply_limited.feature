# language: ru
Функция: Limited apply без случайной отправки на HH
  Как оператор системы поиска работы
  Я хочу gated limited-apply команду
  Чтобы без явного разрешения отклик не ушёл на HH

  Сценарий: Без разрешения limited apply отказывается
    Дано есть план limited apply на вакансию hh
    И внешние записи HH выключены
    Когда оператор запускает apply limited без авторизации записи
    Тогда команда отказывает с external_writes_disabled
    И limited apply не пытался писать в HH

  Сценарий: С двойным разрешением live write всё ещё не реализован
    Дано есть план limited apply на вакансию hh
    И внешние записи HH включены
    И оператор передал явный флаг авторизации записи
    Когда оператор запускает apply limited с лимитом один
    Тогда ответ mode limited и execution not_implemented
    И limited apply не пытался писать в HH
