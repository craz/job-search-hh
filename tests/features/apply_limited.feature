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

  Сценарий: С двойным разрешением fake live transport отправляет один POST
    Дано есть план limited apply на вакансию hh
    И внешние записи HH включены
    И оператор передал явный флаг авторизации записи
    Когда оператор запускает apply limited через recording transport
    Тогда ответ mode limited и execution completed
    И limited apply отметил hh_write_attempted
    И captcha_stop политика включена
