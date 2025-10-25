from django.shortcuts import render, get_object_or_404
from django.template.loader import render_to_string
from django.contrib.auth.decorators import login_required
from django.db.models import F, Prefetch, OuterRef, Exists
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.http import HttpResponseRedirect, HttpResponseForbidden, JsonResponse
from django.contrib.auth.models import Group
from .models import *
from .forms import *
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from django.utils import timezone
import hashlib
import json
import pandas as pd
import openpyxl as xl
from fnmatch import fnmatch

# Create your views here.

# date_keys = {'Выставлен счёт': 'deepskyblue',
#              'Оплачен': 'blue', 'Закупается': 'darkolivegreen',
#              'Закуплен': 'greenyellow', 'Изготавливается': 'yellow',
#              'Изготовлен': 'orange', 'Текущий день': 'lightslategray', 'Дедлайн': 'red'}
# """Цвета ячеек состояний"""


# PARSING_BLACKLIST = ["Лист", "Корпус", "Схема"]
# """Список названий частей изделия в файле спецификации, которые не являются отдельными частями"""

def get_default_object_state():
    return ObjectState.objects.filter(name="Приостановлен").first()


def get_ready_object_state():
    return ObjectState.objects.filter(name="В сборке").first()


ALPHABET = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюяabcdefghijklmnopqrstuvwxyz!@#$%^&*()-=_+"№;:?'


def check_worker_data(request=None, user=None):
    """Проверяет существование данных о работнике, возвращает созданную модель, если данных нет"""
    if user:
        if WorkerData.objects.filter(worker=user).exists():
            return WorkerData.objects.filter(worker=user).first()
        else:
            return WorkerData.objects.create(worker=user)
    elif request:
        if WorkerData.objects.filter(worker=request.user).exists():
            return WorkerData.objects.filter(worker=request.user).first()
        else:
            return WorkerData.objects.create(worker=request.user)
    else:
        raise KeyError("One argument required: request OR user")


def check_user_group(request, group_name: str):
    """
    Проверяет принадлежность пользователя указанной группе

    - request — HTTP-запрос
    - group_name — имя группы, которой должен принадлежать пользователь
    - strict — должна ли проверка быть строгой. Если проверка строгая и пользователь не принадлежит выбранной группе, 
    он будет перенаправлен на главную страницу. Если проверка не строгая, будет возвращено значение True/False в зависимости от того,
    принадлежит ли пользователь выбранной группе
    """
    target_group = Group.objects.get(name=group_name)
    if target_group in request.user.groups.all():
        return True
    else:
        return False


def update_notification(request=None):
    if request.headers.get('X-Requested-With') and 'XMLNotificationUpdate' in request.headers.get('X-Requested-With'):
        notification = None
        notifications = Notification.objects.filter(
            recipient_group=request.user.groups.first())
        if notifications:
            for notify in notifications:
                if request.user not in notify.read_by.all() and (timezone.now() - notify.created_at).seconds < 100:
                    notification = notify
                    break
        if notification:
            cache_key = f'notification_{request.user}'
            cur_hash = hashlib.md5(json.dumps(
                [notification.id, notification.title, notification.message], sort_keys=True).encode()).hexdigest()
            prev_hash = cache.get(cache_key)
            if prev_hash and prev_hash == cur_hash:
                return JsonResponse({'html': ""})
            cache.set(cache_key, cur_hash, timeout=300)
            data = {'html': render_to_string(
                "partials/notification.html", {'notification': notification}, request), 'message': notification.message, 'time': notification.created_at}
            notification.read_by.add(request.user)
            notification.save()
            return JsonResponse(data)
        else:
            return JsonResponse({'html': ""})
    return None

# def check_summary(data: pd.DataFrame):
#     """
#     Проверяет формат Сводной

#     data — данные для парсинга из Сводной в формате pandas.DataFrame
#     """
#     # Проверка заголовка сводной
#     if data.iloc[0, 2] != 'Сводная таблица закупаемого оборудования №':
#         raise ValidationError(
#             "Не удалось определить, является ли файл сводной")
#     obj_number = str(data.iloc[0, 3])
#     # Проверка заголовков для изделий
#     if data.iloc[2, 1] != 'Перечень изготавливаемых изделий:':
#         raise ValidationError("Не найден перечень изготавливаемых изделий")
#     if data.iloc[3, 1] != 'Зав. номер':
#         raise ValidationError("Не найдены заводские номера изделий")
#     if data.iloc[3, 2] != 'Наименование':
#         raise ValidationError("Не найдены наименования изделий")
#     if data.iloc[3, 3] != 'Кол-во':
#         raise ValidationError("Не найдены количества изготавливаемых изделий")
#     # Проверка формата и расположения изделий
#     nan_idx = 4
#     for value in data.iloc[4:, 1]:
#         if pd.notna(value):
#             nan_idx += 1
#             if obj_number not in value:
#                 return False
#         else:
#             break
#     # Проверка заголовков компонентов
#     if data.iloc[nan_idx+1, 1] != 'Перечень оборудования, закупаемого производством:':
#         raise ValidationError("Не найден перечень закупаемого оборудования")
#     if data.iloc[nan_idx+2, 2] != 'Наименование':
#         raise ValidationError("Не найдены наименования оборудования")
#     if data.iloc[nan_idx+2, 14] != 'Дефицит':
#         raise ValidationError(
#             "Не найдены данные о дефиците оборудования")
#     # Проверки закончены
#     return True


def rc_to_a1(row: int, col: int):
    """
    Перевод формата ячеек R1C1 в формат A1

    - row — номер строки
    - col — номер столбца
    """
    letter = ''
    while col > 0:
        col, remainder = divmod(col - 1, 26)
        letter = chr(65 + remainder) + letter
    return f"{letter}{row}"


def check_spec(data: pd.DataFrame, formatted: xl.Workbook):
    """
    Проверяет формат Спецификации

    - data — данные для парсинга из Спецификации в формате pandas.DataFrame
    - formatted — Excel-файл с форматированием
    """
    if data.iloc[0, 1] != 'Наименование':
        raise ValidationError("Не найдены наименования частей изделий")
    if data.iloc[0, 11] != 'Итого\nруб':
        raise ValidationError("Не найдены итоговые стоимости частей изделий")
    if data.iloc[0, 14] != 'З/п':
        raise ValidationError(
            "Не найдены данные о зарплатах за иготовление изделий")
    row_idx = 10
    isHeader = False
    anyHeader = False
    sheet = formatted['Спецификация']
    # Цвет: #33CCFF
    while pd.notna(data.iloc[row_idx, 1]):
        cell = sheet[rc_to_a1(row_idx+1, 2)]
        if cell.fill and cell.fill.start_color.rgb == "FF33CCFF":
            if cell.font and cell.font.bold:
                if isHeader:
                    raise ValidationError("Обнаружено пустое изделие")
                isHeader = True
                anyHeader = True
            else:
                isHeader = False
        elif anyHeader is False:
            raise ValidationError("Обнаружено оборудование без изделия")
        else:
            isHeader = False
        row_idx += 1
    return True

# Главная страница


@login_required
def index(request):

    # Если пользователь принадлежит группе Работник
    # Загружаем шаблон для работника
    if check_user_group(request, "worker"):
        # Проверка данных после авторизации.
        # В таком случае данные будут созданы в случае
        # Если они не существуют
        worker = check_worker_data(request)
        context = dict()
        notify = update_notification(request)
        if notify:
            return notify
        queued = CreationInstance.objects.filter(
            worker=worker, status='QUEUED').prefetch_related('product', 'part')
        if queued:
            context['queued_first'] = queued.first()
            context['queued'] = queued
        else:
            ready_state_subquery = ObjectStateInstance.objects.filter(
                object=OuterRef('pk'),
                state=get_ready_object_state()
            )

            objects = Object.objects.filter(
                hidden=False, ready_percentage__lt=100).annotate(is_ready=Exists(ready_state_subquery)).filter(is_ready=True).prefetch_related(Prefetch('product_set', queryset=Product.objects.prefetch_related(Prefetch('part_set', queryset=Part.objects.all()))))
            products = []
            search_query = request.GET.get('search', '')
            for object in objects:
                for product in object.product_set.all():
                    ava_amount = product.get_ava_amount()
                    has_available_parts = any(
                        part.get_ava_amount() > 0
                        for part in product.part_set.all()
                    )

                    if (ava_amount > 0 or has_available_parts) and search_query in product.get_id():
                        products.append(product)
            # Получаем список всех изделий
            # raw_products = Product.objects.all().prefetch_related('object')
            # # Фильтруем, оставляя лишь изделия, которые можно взять в работу
            # products = []
            # for product in raw_products:
            #     if product.object.hidden is True:
            #         continue
            #     parts = Part.objects.filter(
            #         product=product).prefetch_related('product')
            #     state = ObjectStateInstance.objects.filter(
            #         object=product.object, state=READY_OBJECT_STATE).prefetch_related('state', 'object')
            #     # Если доступно всё изделие или какая-либо его часть
            #     if product.get_ava_amount() > 0 or any(part.get_ava_amount() > 0 for part in parts):
            #         # Если изделие готово к сборке
            #         if state.exists():
            #             products.append(product)
            context['products'] = products
            if request.headers.get('X-Requested-With') == 'XMLHttpSearchRequest':
                data = {'html': render_to_string(
                    "partials/worker_products.html", context, request)}
                return JsonResponse(data)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            cache_key = f'worker_products_list_{request.user}'
            if queued:
                cur_hash = hashlib.md5(json.dumps(
                    list(queued.values('id')), sort_keys=True).encode()).hexdigest()
            else:
                prod_ids = []
                for product in products:
                    prod_ids.append(product.id)
                cur_hash = hashlib.md5(json.dumps(
                    prod_ids, sort_keys=True).encode()).hexdigest()
            prev_hash = cache.get(cache_key)
            if prev_hash and prev_hash == cur_hash:
                return JsonResponse({'html': ""})
            cache.set(cache_key, cur_hash, timeout=300)
            data = {'html': render_to_string(
                "partials/worker_products.html", context, request)}
            return JsonResponse(data)
        cache_key = f'worker_products_list_{request.user}'
        if queued:
            cur_hash = hashlib.md5(json.dumps(
                list(queued.values('id')), sort_keys=True).encode()).hexdigest()
        else:
            prod_ids = []
            for product in products:
                prod_ids.append(product.id)
            cur_hash = hashlib.md5(json.dumps(
                prod_ids, sort_keys=True).encode()).hexdigest()
        cache.set(cache_key, cur_hash, timeout=300)
        # Отправляем пользователю шаблон, заполняя его данными
        return render(request, "worker.html", context)
    # Если пользователь принадлежит группе Мастер
    # Загружаем шаблон для мастера
    elif check_user_group(request, "master"):
        objects = Object.objects.filter(hidden=False)
        questions = Question.objects.filter(answer='')
        context = {'objects': objects, 'questions': len(questions)}
        notify = update_notification(request)
        if notify:
            return notify
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            data = []
            for object in objects:
                data.append(
                    f'obj: {object.id} ready: {object.get_ready_percentage()}')
            for question in questions:
                data.append(f'question: {question.id}')
            cur_hash = hashlib.md5(json.dumps(
                data, sort_keys=True).encode()).hexdigest()
            cache_key = f'master_object_list_{request.user}'
            prev_hash = cache.get(cache_key)
            if prev_hash and prev_hash == cur_hash:
                return JsonResponse({'html': ""})
            cache.set(cache_key, cur_hash, timeout=300)
            question_len = 0
            if questions:
                question_len = len(questions)
            data = {'html': render_to_string(
                'partials/objects_table.html', context, request), 'questions': question_len}
            return JsonResponse(data)
        return render(request, 'master.html', context)
        # start_dt = timezone.now().date()
        # end_dt = timezone.now().date()
        # dates = {}
        # for object in objects:
        #     states = ObjectStateInstance.objects.filter(
        #         object=object).all()
        #     if not states is None:
        #         for state in states:
        #             event_date = state.created_at
        #             if start_dt is None:
        #                 start_dt = event_date
        #             else:
        #                 start_dt = min(start_dt, event_date)
        #             if end_dt is None:
        #                 end_dt = event_date
        #             else:
        #                 end_dt = max(end_dt, event_date)
        #             if dates.get(object.id) is None:
        #                 dates[object.id] = dict()
        #             dates[object.id][event_date] = date_keys.get(
        #                 state.state.name, 'none')
        #     event_date = object.deadline
        #     if dates.get(object.id) is None:
        #         dates[object.id] = dict()
        #     dates[object.id][event_date] = date_keys.get('Дедлайн')
        #     if start_dt is None:
        #         start_dt = event_date
        #     else:
        #         start_dt = min(start_dt, event_date)
        #     start_dt = min(start_dt, timezone.now().date())
        #     if end_dt is None:
        #         end_dt = event_date
        #     else:
        #         end_dt = max(end_dt, event_date)
        #     end_dt = max(end_dt, timezone.now().date())
        #     if (end_dt - start_dt).days < 7:
        #         start_dt -= timedelta(days=7)
        #         end_dt += timedelta(days=7)
        # year_month = dict()
        # days = dict()
        # idx = 0
        # st = start_dt
        # while st <= end_dt:
        #     if year_month.get(str(st.isoformat())[:-3]) is None:
        #         year_month[(str(st.isoformat())[:-3])] = 1
        #     else:
        #         year_month[(str(st.isoformat())[:-3])] += 1
        #     days[idx] = {'value': str(st.isoformat())
        #                  [-2::], 'color': 'none', 'text': 'black'}
        #     if st == timezone.now().date():
        #         days[idx]['color'] = date_keys.get('Текущий день')
        #         days[idx]['text'] = 'white'
        #     elif st.weekday() in [5, 6]:
        #         days[idx]["color"] = 'rgb(200, 0, 100)'
        #         days[idx]['text'] = 'white'
        #     idx += 1
        #     for object in objects:
        #         if dates.get(object.id) is None:
        #             dates[object.id] = dict()
        #         if dates.get(object.id).get(st) is None:
        #             if st == timezone.now().date():
        #                 dates[object.id][st] = date_keys.get(
        #                     'Текущий день')
        #             else:
        #                 dates[object.id][st] = 'none'
        #     st += timedelta(days=1)

        # for key in dates:
        #     dates[key] = dict(sorted(dates.get(key).items()))

        # context = {'year_month': year_month, 'days': days,
        #            'objects': objects, 'datemap': dates, 'legend': date_keys}
        # return render(request, 'master.html', context)
    # Иначе отправляем шаблон с текстом об ошибке
    else:
        return render(request, 'index.html')


# Детальный обзор изделия
@login_required
def product_detail_view(request, pk):
    if check_user_group(request, "worker") is False:
        return HttpResponseRedirect('/workspace')
    notify = update_notification(request)
    if notify:
        return notify
    # Получаем информацию о выбранном изделии
    product = get_object_or_404(Product, pk=pk)
    raw_parts = Part.objects.filter(product=product)
    parts = None
    for part in raw_parts:
        if part.get_ava_amount() > 0:
            if parts is None:
                parts = [part]
            else:
                parts.append(part)
    tmpl_choices = dict()
    choices = None
    def_amount = 1
    def_choice = '1'
    if product.get_ava_amount() > 0:
        def_amount = min(def_amount, product.ava_float())
        choices = [('1', 'Всё изделие')]
        tmpl_choices['1'] = str(def_amount)
    idx = 2
    if parts:
        for part in parts:
            if choices is None:
                def_amount = min(def_amount, part.get_ava_amount())
                def_choice = str(idx)
                choices = [(str(idx), part.name)]
                tmpl_choices[str(idx)] = str(min(1, part.get_ava_amount()))
                idx += 1
            else:
                choices.append((str(idx), part.name))
                tmpl_choices[str(idx)] = str(min(1, part.get_ava_amount()))
                idx += 1
    # Если была нажата кнопка Взять в работу (пришёл POST запрос)
    # Обрабатываем данные
    if request.method == "POST":
        # Получаем данные от формы
        form = TakeProductToWorkForm(
            request.POST, choices=choices, initial={'amount': def_amount, 'creation': def_choice})
        # Если не возникло ошибок
        if form.is_valid():
            # Получаем выбранное количество
            amount = form.cleaned_data['amount']
            choice = int(form.cleaned_data['creation'])
            # Если выбрано всё изделие
            if choice == 1:
                # Если количество превышает доступное
                # Выводим сообщение об ошибке (добавляя ошибку в форму, дальнейшая обработка произойдёт в шаблоне)
                if amount > product.get_ava_amount():
                    context = {
                        'form': form,
                        'product': product,
                        'parts': parts,
                        'choices': tmpl_choices,
                    }
                    form.add_error(
                        'amount', "Указанное количество изделий превышает допустимое")
                    return render(request, 'product_detail.html', context)
                # Иначе создаём запись о новом изделии в работе
                else:
                    worker_data = check_worker_data(request)
                    product.ava_amount = None
                    product.save()
                    # Если запись уже есть, обновляем её (увеличилось кол-во изделий в работе)
                    wip_product = CreationInstance.objects.filter(
                        worker=worker_data, product=product, status="IN_WORK").first()
                    if wip_product:
                        wip_product.amount += amount
                        wip_product.save()
                    # Иначе создаём новую запись
                    else:
                        CreationInstance.objects.create(
                            product=product, worker=worker_data, amount=amount, status='IN_WORK', started=timezone.now().date())
                    product.get_ava_amount()
                    # Возвращаем пользователя на главную страницу
                    return HttpResponseRedirect('/workspace')
            # Если выбрана часть изделия
            else:
                selected_part = None
                idx = 2
                for part in parts:
                    if idx == choice:
                        selected_part = part
                        break
                    idx += 1
                if amount > selected_part.get_ava_amount():
                    context = {
                        'form': form,
                        'product': product,
                        'parts': parts,
                        'choices': tmpl_choices,
                    }
                    form.add_error(
                        'amount', "Указанное количество изделий превышает допустимое")
                    return render(request, 'product_detail.html', context)
                else:
                    worker_data = check_worker_data(request)
                    # Если запись уже есть, обновляем её (увеличилось кол-во частей в работе)
                    selected_part.product.ava_amount = None
                    selected_part.product.save()
                    selected_part.ava_amount = None
                    selected_part.save()
                    wip_part = CreationInstance.objects.filter(
                        worker=worker_data, part=selected_part).first()
                    if wip_part:
                        wip_part.amount += amount
                        wip_part.save()
                    # Иначе создаём новую запись
                    else:
                        CreationInstance.objects.create(
                            part=part, worker=worker_data, amount=amount, status='IN_WORK', started=timezone.now().date())
                    selected_part.get_ava_amount()
                    selected_part.product.get_ava_amount()
                    # Возвращаем пользователя на главную страницу
                    return HttpResponseRedirect('/workspace')

    # Если пришёл другой запрос (GET), возвращаем шаблон с формой для взятия изделия в работу
    else:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            cache_key = f'product_detail_{request.user}'
            cache_data = [f'prod: {product.ava_float()}',
                          f'descr: {product.description}']
            if parts:
                for part in parts:
                    cache_data.append(f'{part.id}: {part.get_ava_amount}')
            cur_hash = hashlib.md5(json.dumps(
                cache_data, sort_keys=True).encode()).hexdigest()
            prev_hash = cache.get(cache_key)
            if prev_hash and prev_hash == cur_hash:
                return JsonResponse({'html': ""})
            cache.set(cache_key, cur_hash, timeout=300)
            form = TakeProductToWorkForm(choices=choices, initial={
                'amount': def_amount, 'creation': def_choice})
            if parts == None:
                if product.get_ava_amount() == 0:
                    data = {'return': True}
                    return JsonResponse(data)
            else:
                if product.get_ava_amount() == 0 and all(part.get_ava_amount() == 0 for part in parts):
                    data = {'return': True}
                    return JsonResponse(data)
            context = {
                'form': form,
                'product': product,
                'parts': parts,
                'choices': tmpl_choices,
            }
            data = {'html': render_to_string(
                "partials/product_details.html", context, request)}
            return JsonResponse(data)
        else:
            form = TakeProductToWorkForm(choices=choices, initial={
                'amount': def_amount, 'creation': def_choice})
    context = {
        'form': form,
        'product': product,
        'parts': parts,
        'choices': tmpl_choices,
    }
    return render(request, 'product_detail.html', context)


# Список изделий, изготавливаемых работником
@login_required
def my_products_view(request):
    if check_user_group(request, "worker") is False:
        return HttpResponseRedirect('/workspace')
    notify = update_notification(request)
    if notify:
        return notify
    worker_data = check_worker_data(request)
    # Получаем запись о всех изделиях, выполняемых данным работником
    instances = CreationInstance.objects.filter(
        worker=worker_data, status='IN_WORK')
    # Отправляем заполненный шаблон
    context = {'instances': instances}
    return render(request, 'my_products.html', context)


# Детальный обзор изделия в работе
@login_required
def my_product_view(request, pk):
    if check_user_group(request, "worker") is False:
        return HttpResponseRedirect('/workspace')
    notify = update_notification(request)
    if notify:
        return notify
    worker_data = check_worker_data(request)
    # Получаем запись о выбранном изделии
    instance = get_object_or_404(CreationInstance, pk=pk)
    # Если данные запросил пользователь, который не ведёт работу над изделием
    # Вовзращаем его на страницу с его изделиями
    if instance.worker != worker_data:
        return HttpResponseRedirect("/workspace/my_products")
    # Получаем данные о всех вопросах на странице данного изделия
    all_questions = Question.objects.filter(instance=instance)
    # Если получен POST запрос (нажата кнопка Отправить вопрос)
    if request.method == "POST":
        if 'send_question' in request.POST:
            # Получаем данные из формы
            form = EnterQuestionForm(request.POST, initial={'question': ' '})
            # Создаём новый вопрос, если не возникло ошибок
            if form.is_valid():
                question = form.cleaned_data['question']
                Question.objects.create(
                    instance=instance, quest=question)
                all_questions = Question.objects.filter(instance=instance)
        elif 'finish_product' in request.POST:
            object = instance.product.object if instance.product else instance.part.product.object
            object.ready_percentage = None
            object.save()
            part = None
            if instance.part:
                part = instance.part
                part.ava_amount = None
                part.save()
            product = instance.product if instance.product else instance.part.product
            product.ava_amount = None
            product.completed_amount = None
            product.save()
            completed = CreationInstance.objects.filter(
                worker=worker_data, product=instance.product, part=instance.part, status="COMPLETED").first()
            if completed:
                completed.amount += instance.amount
                completed.completed = timezone.now().date()
                completed.save()
                instance.delete()
            else:
                instance.status = 'COMPLETED'
                instance.completed = timezone.now().date()
                instance.save()
            if part:
                part.get_ava_amount()
            product.get_ava_amount()
            product.get_completed_amount()
            object.get_ready_percentage()
            Notification.objects.create(recipient_group=Group.objects.get(
                name='master'), title='Завершено изделие', message=f'{worker_data.display_name} завершил работу над {instance}')
            return HttpResponseRedirect('/workspace/my_products')
        elif 'cancel_product' in request.POST:
            while all_questions:
                all_questions.first().delete()
            product = instance.product if instance.product else instance.part.product
            product.ava_amount = None
            instance.delete()
            product.get_ava_amount()
            return HttpResponseRedirect('/workspace/my_products')
    # Если получен другой запрос (GET), создаём форму для отправки вопроса
    else:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            cache_key = f'worker_product_{request.user}'
            cur_hash = hashlib.md5(json.dumps(list(all_questions.values(
                "id", "quest", "answer")), sort_keys=True).encode()).hexdigest()
            prev_hash = cache.get(cache_key)
            if prev_hash and prev_hash == cur_hash:
                return JsonResponse({'html': ""})
            cache.set(cache_key, cur_hash, timeout=300)
            context = {
                'instance': instance,
                'questions': all_questions
            }
            data = {'html': render_to_string(
                "partials/questions_list.html", context, request)}
            return JsonResponse(data)
        else:
            form = EnterQuestionForm()
    # Отправляем заполненный шаблон
    context = {
        'form': form,
        'instance': instance,
        'questions': all_questions
    }
    return render(request, 'my_product.html', context)


@login_required
def object_detail_view(request, pk):
    if check_user_group(request, "master") is False:
        return HttpResponseRedirect('/workspace')
    notify = update_notification(request)
    if notify:
        return notify
    object = get_object_or_404(Object, pk=pk)
    states = ObjectStateInstance.objects.filter(object=object)
    # all_states = ObjectState.objects.all()
    # idx = 1
    # form_states = None
    # for state in all_states:
    #     if form_states:
    #         form_states.append((str(idx), state))
    #     else:
    #         form_states = [(str(idx), state)]
    #     idx += 1
    # form_states.append((str(idx), 'Дедлайн'))
    products = Product.objects.filter(object=object).prefetch_related('object')
    can_be_deleted = True
    for product in products:
        if product.get_ava_amount() != product.amount:
            can_be_deleted = False
            break
    ready = False
    for state in states:
        if state.state == get_ready_object_state():
            ready = True
            break
    context = {
        'object': object,
        'states': states,
        'products': products,
        'delete': can_be_deleted,
        'ready': ready
    }
    if request.method == "POST":
        # if 'add_state' in request.POST:
        #     form = AddStateForm(request.POST, choices=form_states)
        #     if form.is_valid():
        #         state_idx = int(form.cleaned_data["state"])
        #         created_at = form.cleaned_data["created_at"]
        #         idx = 1
        #         selected_state = None
        #         for state in all_states:
        #             if idx == state_idx:
        #                 selected_state = state
        #                 break
        #             idx += 1
        #         if selected_state:
        #             for cur_state in states:
        #                 if cur_state.state.group == selected_state.group:
        #                     if cur_state.state.priority > selected_state.priority and created_at > cur_state.created_at:
        #                         form.add_error(
        #                             'created_at', f'{selected_state.name}: состояние не может распологаться раньше {cur_state.state.name}')
        #                         context['form'] = form
        #                         break
        #             if created_at > object.deadline:
        #                 form.add_error(
        #                     'created_at', f'{selected_state.name}: состояние не может распологаться позже {object.deadline}')
        #                 context['form'] = form
        #         if created_at < datetime(year=2020, month=1, day=1).date():
        #             form.add_error(
        #                 'created_at', f'{selected_state.name}: состояние не может распологаться раньше 1 января 2020 года')
        #             context['form'] = form
        #         if not form.is_valid():
        #             return render(request, 'object_detail.html', context)
        #         if selected_state:
        #             if selected_state not in [x.state for x in states]:
        #                 ObjectStateInstance.objects.create(
        #                     object=object, state=selected_state, created_at=created_at)
        #             else:
        #                 changed_state = ObjectStateInstance.objects.filter(
        #                     object=object, state=selected_state).first()
        #                 changed_state.created_at = created_at
        #                 changed_state.save()
        #         else:
        #             object.deadline = created_at
        #             object.save()
        #             context['object'] = object
        if 'delete_obj' in request.POST:
            if can_be_deleted:
                object.delete()
                return HttpResponseRedirect('/workspace')
            else:
                return HttpResponseForbidden('Этот объект нельзя удалить – он уже в работе')
        elif 'to_work_obj' in request.POST:
            if ready is False:
                obj_states = ObjectStateInstance.objects.filter(object=object)
                for state in obj_states:
                    if state.state == get_default_object_state():
                        state.delete()
                        break
                ObjectStateInstance.objects.create(
                    object=object, state=get_ready_object_state(), created_at=timezone.now().date())
                ready = True
                context['ready'] = ready
            else:
                return HttpResponseForbidden('Этот объект уже В сборке')
        elif 'stop_obj' in request.POST:
            if ready is True:
                obj_states = ObjectStateInstance.objects.filter(object=object)
                for state in obj_states:
                    if state.state == get_ready_object_state():
                        state.delete()
                        break
                ObjectStateInstance.objects.create(
                    object=object, state=get_default_object_state(), created_at=timezone.now().date())
                ready = False
                context['ready'] = ready
            else:
                return HttpResponseForbidden('Этот объект уже Приостановлен')
        elif 'hide_obj' in request.POST:
            object.hidden = True
            object.save()
            context['object'] = object
        elif 'show_obj' in request.POST:
            object.hidden = False
            object.save()
            context['object'] = object

    elif request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        cache_key = f'object_detail_{object.id}'
        cache_data = []
        for product in products:
            cache_data.append(
                f'{product.id}: {product.get_ava_amount()}, {product.get_ava_parts_amount()}, {product.get_in_work_amount()}, {product.get_parts_in_work_amount()}')
        cur_hash = hashlib.md5(json.dumps(
            cache_data, sort_keys=True).encode()).hexdigest()
        prev_hash = cache.get(cache_key)
        if prev_hash and prev_hash == cur_hash:
            return JsonResponse({'html': ""})
        cache.set(cache_key, cur_hash, timeout=300)
        data = {'html': render_to_string(
            "partials/object_details.html", context, request)}
        return JsonResponse(data)
    # else:
        # form = AddStateForm(
        #     initial={'created_at': timezone.now().date()}, choices=form_states)
    # states = ObjectStateInstance.objects.filter(object=object).all()
    # context['form'] = form
    # context['states'] = states
    return render(request, 'object_detail.html', context)


@login_required
def in_work_view(request):
    if check_user_group(request, "master") is False:
        return HttpResponseRedirect('/workspace')
    notify = update_notification(request)
    if notify:
        return notify
    if request.method == "POST":
        finished_id = request.POST.get("work_id")
        instance = CreationInstance.objects.filter(id=finished_id).first()
        object = instance.product.object if instance.product else instance.part.product.object
        object.ready_percentage = None
        object.save()
        part = None
        if instance.part:
            part = instance.part
            part.ava_amount = None
        product = instance.product if instance.product else instance.part.product
        product.ava_amount = None
        product.completed_amount = None
        product.save()
        completed = CreationInstance.objects.filter(
            worker=instance.worker, product=instance.product, part=instance.part, status="COMPLETED").first()
        if completed:
            completed.amount += instance.amount
            completed.completed = timezone.now().date()
            completed.save()
            instance.delete()
        else:
            instance.status = 'COMPLETED'
            instance.completed = timezone.now().date()
            instance.save()
        if part:
            part.get_ava_amount()
        product.get_ava_amount()
        product.get_completed_amount()
        object.get_ready_percentage()
    instances = CreationInstance.objects.filter(status='IN_WORK')
    questions = Question.objects.filter(answer='')
    context = {
        'instances': instances,
        'questions': len(questions)
    }
    return render(request, 'in_work_list.html', context)


@login_required
def workers_list_view(request):
    """
    **view** для вкладки ***Работники***

    Получает из **БД**:
    - ***WorkerData*** с полем ***hidden***=**True**

    Включенные запросы к **БД** (вызываются в процессе подготовки данных):
    - x2 ***CreationInstance*** c полем ***worker***=***WorkerData***, ***completed*** >= **Начало указанного месяца**, ***completed*** <= **Конец указанного месяца**, ***status***=**COMPLETED**
    - x2 ***CreationInstance*** c полем ***worker***=***WorkerData***, ***status***=**COMPLETED**

    Работает с шаблоном ***workers_list.html***
    """
    # Проверяем группу пользователя
    # Для ограничения доступа
    if check_user_group(request, "master") is False:
        return HttpResponseRedirect('/workspace')
    # Обновляем уведомления (работает только если пришёл запрос на обновление уведомлений)
    notify = update_notification(request)
    if notify:
        return notify
    # Создаём пустой словарь для дальнейшего заполнения данными
    context = dict()
    # Если пришёл POST запрос
    # - Добавить пользователя (add_user)
    # - Сохранить пользователя (create_user)
    if request.method == "POST":
        # Если нужно добавить нового пользователя
        if 'add_user' in request.POST:
            # Создаём нужную для добавления пользователя форму
            form = CustomUserCreationForm()
            # Добавляем её в словарь с данными
            context['form'] = form
        # Если нужно сохранить созданного пользователя
        elif 'create_user' in request.POST:
            # Создаём форму для добавления пользователя и передаём в неё данные
            form = CustomUserCreationForm(request.POST)
            # Если форма корректна (нет ошибок в переданных значениях)
            if form.is_valid():
                # Сохраняем созданного пользователя (модель User)
                user = form.save()
                # Получаем из БД группу, соответствующую работнику
                group = Group.objects.get(name="worker")
                # Добавляем созданному пользователю группу "Работник"
                user.groups.add(group)
                # Вызываем метод проверки данных о работнике для их создания
                worker_data = check_worker_data(user=user)
                # Получаем отображаемое имя пользователя из формы
                display_name = form.cleaned_data["display_name"]
                # В данные о работнике добавляем отображаемое имя
                worker_data.display_name = display_name
                # Сохраняем данные о работнике
                worker_data.save()
            # Если произошла ошибка при заполнении формы
            # Возвращаем форму с сообщениями об ошибках
            else:
                context['form'] = form
    # Получаем из запроса дату (месяц, за который нужны данные)
    date = request.GET.get("date")
    # Если в запросе была дата
    if date:
        # Переводим её в подходящий формат
        cur_date = datetime.strptime(date, '%Y-%m-%d').date()
    # Если в запросе не было даты - используем текущую дату
    else:
        cur_date = datetime.now().date()
    # Определяем предыдущий месяц
    prev = cur_date - relativedelta(months=1)
    # Определяем следующий месяц
    next = cur_date + relativedelta(months=1)
    # Определяем начало выбранного месяца
    start = cur_date.replace(day=1)
    # Определяем конец выбранного месяца
    end = (start + relativedelta(months=1)
           ).replace(day=1) - relativedelta(days=1)
    # Получаем данные о всех работниках
    workers_data = WorkerData.objects.all()
    # Создаём пустой словарь для сбора данных о работниках
    workers = dict()
    # Создаём переменную для хранения общего кол-ва произведённых изделий
    all_completed = 0
    # Создаём переменную для хранения общей суммы выплат
    all_payment = 0
    # Создаём переменную для хранения кол-ва произведённых изделий за выбранный месяц
    completed = 0
    # Создаём переменную для хранения суммы выплат за выбранный месяц
    payment = 0
    # Собираем данные о всех работниках
    for worker in workers_data:
        # Если работник произвёл какие-либо изделия за выбранный месяц
        if worker.get_completed(start, end) > 0:
            # Добавляем в словарь данные о нём: его данные, кол-во произведённых изделий, сумму выплат
            workers[worker] = {"worker": worker, "completed": worker.get_completed(
                start, end), "payment": worker.get_payment(start, end)}
            # Обновляем данные за месяц
            completed += worker.get_completed(start, end)
            payment += worker.get_payment(start, end)
        # Обновляем данные за всё время
        all_completed += worker.get_all_completed_amount()
        all_payment += worker.get_all_payment()
    # Заполняем словарь с данными для шаблона
    context['workers'] = workers
    context['completed_products'] = completed
    context['payment'] = payment
    context['prev'] = prev
    context['next'] = next
    context['current_date'] = cur_date
    context['all_workers'] = workers_data
    context['all_completed'] = all_completed
    context['all_payment'] = all_payment
    # Получаем кол-во вопросов, на которые не был дан ответ
    context['questions'] = len(Question.objects.filter(answer=''))
    # Возвращаем заполненный шаблон
    return render(request, 'workers_list.html', context)


@login_required
def product_in_work_detail_view(request, pk):
    if check_user_group(request, "master") is False:
        return HttpResponseRedirect('/workspace')
    notify = update_notification(request)
    if notify:
        return notify
    product = get_object_or_404(Product, pk=pk)
    parts = Part.objects.filter(product=product)
    in_work_products = CreationInstance.objects.filter(
        product=product, status='IN_WORK')
    queued_products = CreationInstance.objects.filter(
        product=product, status='QUEUED')
    completed_products = CreationInstance.objects.filter(
        product=product, status="COMPLETED")
    in_work_parts = []
    queued_parts = []
    completed_parts = []
    for part in parts:
        raw_parts = CreationInstance.objects.filter(part=part)
        for raw_part in raw_parts:
            if raw_part.status == "IN_WORK":
                in_work_parts.append(raw_part)
            elif raw_part.status == "QUEUD":
                queued_parts.append(raw_part)
            elif raw_part.status == "COMPLETED":
                completed_parts.append(raw_part)
    # raise ValidationError(f"{completed_products} {completed_parts}")
    context = {
        'product': product,
        'in_work_products': in_work_products,
        'queued_products': queued_products,
        'completed_products': completed_products,
        'in_work_parts': in_work_parts,
        'queued_parts': queued_parts,
        'completed_parts': completed_parts,
        'parts': parts
    }
    raw_parts = Part.objects.filter(product=product)
    selectable_parts = None
    for part in raw_parts:
        if part.get_ava_amount() > 0:
            if selectable_parts is None:
                selectable_parts = [part]
            else:
                selectable_parts.append(part)
    choices = None
    def_amount = 1
    def_choice = '1'
    if product.get_ava_amount() > 0:
        def_amount = min(def_amount, product.ava_float())
        choices = [('1', 'Всё изделие')]
    idx = 2
    if selectable_parts:
        for part in selectable_parts:
            if choices is None:
                def_amount = min(def_amount, part.get_ava_amount())
                def_choice = str(idx)
                choices = [(str(idx), part.name)]
                idx += 1
            else:
                choices.append((str(idx), part.name))
                idx += 1
    if choices:
        form = AddProductToQueueForm(choices=choices, initial={
            'amount': def_amount, 'creation': def_choice})
        context['queueform'] = form
    if request.method == "GET":
        if 'edit' in request.GET:
            context['edit_mode'] = request.GET["edit"] == '1'
            form = EnterDescriptionForm(
                initial={'description': product.description})
            context['editform'] = form
        elif 'return' in request.GET:
            return HttpResponseRedirect(f"/workspace/objects/{product.object.id}")
        raw_parts = Part.objects.filter(product=product)
        selectable_parts = None
        for part in raw_parts:
            if part.get_ava_amount() > 0:
                if selectable_parts is None:
                    selectable_parts = [part]
                else:
                    selectable_parts.append(part)
        choices = None
        def_amount = 1
        def_choice = '1'
        if product.get_ava_amount() > 0:
            def_amount = min(def_amount, product.ava_float())
            choices = [('1', 'Всё изделие')]
        idx = 2
        if selectable_parts:
            for part in selectable_parts:
                if choices is None:
                    def_amount = min(def_amount, part.get_ava_amount())
                    def_choice = str(idx)
                    choices = [(str(idx), part.name)]
                    idx += 1
                else:
                    choices.append((str(idx), part.name))
                    idx += 1
        if choices:
            form = AddProductToQueueForm(choices=choices, initial={
                'amount': def_amount, 'creation': def_choice})
            context['queueform'] = form
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            cache_key = f'product_detail_{product.id}'
            cache_data = [
                f'{product.id}: {product.get_ava_amount()}, {product.get_ava_parts_amount()}, {product.get_in_work_amount()}, {product.get_parts_in_work_amount()}']
            for part in parts:
                cache_data.append(
                    f'{part.id}: {part.get_ava_amount()}, {part.get_completed_amount()}, {part.get_in_work_amount()}')
            cur_hash = hashlib.md5(json.dumps(
                cache_data, sort_keys=True).encode()).hexdigest()
            prev_hash = cache.get(cache_key)
            if prev_hash and prev_hash == cur_hash:
                return JsonResponse({'html': ""})
            cache.set(cache_key, cur_hash, timeout=300)
            data = {'html': render_to_string(
                "partials/product_in_work_details.html", context, request)}
            return JsonResponse(data)
    elif request.method == "POST":
        if 'save' in request.POST:
            form = EnterDescriptionForm(request.POST)
            if form.is_valid():
                description = form.cleaned_data["description"]
                product.description = description
                product.save()
                context['edit_mode'] = False
        elif 'cancel' in request.POST:
            context['edit_mode'] = False
        elif 'add_to_queue' in request.POST:
            raw_parts = Part.objects.filter(product=product)
            selectable_parts = None
            for part in raw_parts:
                if part.get_ava_amount() > 0:
                    if selectable_parts is None:
                        selectable_parts = [part]
                    else:
                        selectable_parts.append(part)
            choices = None
            def_amount = 1
            def_choice = "1"
            if product.get_ava_amount() > 0:
                def_amount = min(def_amount, product.ava_float())
                choices = [('1', 'Всё изделие')]
            idx = 2
            if selectable_parts:
                for part in selectable_parts:
                    if choices is None:
                        def_amount = min(def_amount, part.get_ava_amount())
                        def_choice = str(idx)
                        choices = [(str(idx), part.name)]
                        idx += 1
                    else:
                        choices.append((str(idx), part.name))
                        idx += 1
            if choices:
                form = AddProductToQueueForm(request.POST, choices=choices, initial={
                    'amount': def_amount, 'creation': def_choice})
            else:
                form = AddProductToQueueForm(request.POST)
            if form.is_valid():
                amount = form.cleaned_data['amount']
                choice = int(form.cleaned_data['creation'][0])
                worker = form.cleaned_data['worker']
                worker_data = check_worker_data(user=worker)
                if choice == 1:
                    if product.get_ava_amount() < amount:
                        form.add_error(
                            'amount', f'Выбрано недопустимое кол-во. К изготовлению доступно {product.get_ava_amount()} шт.')
                        context['queueform'] = form
                        return render(request, 'product_in_work.html', context)
                    product.ava_amount = None
                    product.save()
                    instance = CreationInstance.objects.filter(
                        worker=worker_data, product=product, status='QUEUED').first()
                    if instance:
                        instance.amount += amount
                        instance.save()
                    else:
                        CreationInstance.objects.create(
                            worker=worker_data, product=product, status='QUEUED', amount=amount, queued=timezone.now())
                    product.get_ava_amount()
                else:
                    selected_part = None
                    idx = 2
                    for part in selectable_parts:
                        if idx == choice:
                            selected_part = part
                            break
                        idx += 1
                    if amount > selected_part.get_ava_amount():
                        form.add_error(
                            'amount', f'Выбрано недопустимое кол-во. К изготовлению доступно {selected_part.get_ava_amount()} шт.')
                        context['queueform'] = form
                        return render(request, 'product_in_work.html', context)
                    selected_part.ava_amount = 0
                    selected_part.product.ava_amount = 0
                    selected_part.save()
                    selected_part.product.save()
                    instance = CreationInstance.objects.filter(
                        worker=worker_data, part=selected_part, status='QUEUED').first()
                    if instance:
                        instance.amount += amount
                        instance.save()
                    else:
                        CreationInstance.objects.create(
                            worker=worker_data, part=selected_part, status='QUEUED', amount=amount, queued=timezone.now())
                    selected_part.get_ava_amount()
                    selected_part.product.get_ava_amount()
                raw_parts = Part.objects.filter(product=product)
                selectable_parts = None
                for part in raw_parts:
                    if part.get_ava_amount() > 0:
                        if selectable_parts is None:
                            selectable_parts = [part]
                        else:
                            selectable_parts.append(part)
                choices = None
                def_amount = 1
                def_choice = '1'
                if product.get_ava_amount() > 0:
                    def_amount = min(def_amount, product.ava_float())
                    choices = [('1', 'Всё изделие')]
                idx = 2
                if selectable_parts:
                    for part in selectable_parts:
                        if choices is None:
                            def_amount = min(def_amount, part.get_ava_amount())
                            def_choice = str(idx)
                            choices = [(str(idx), part.name)]
                            idx += 1
                        else:
                            choices.append((str(idx), part.name))
                            idx += 1
                queued_parts = []
                for part in parts:
                    queue_parts = CreationInstance.objects.filter(
                        part=part, status='QUEUED')
                    for queue_part in queue_parts:
                        queued_parts.append(queue_part)
                queued_products = CreationInstance.objects.filter(
                    product=product, status='QUEUED')
                context['queued_parts'] = queued_parts
                context['queued_products'] = queued_products
                if choices:
                    form = AddProductToQueueForm(
                        choices=choices, initial={
                            'amount': def_amount, 'creation': def_choice})
                    context['queueform'] = form

    return render(request, 'product_in_work.html', context)


@login_required
def worker_detail(request, pk):
    if check_user_group(request, "master") is False:
        return HttpResponseRedirect('/workspace')
    notify = update_notification(request)
    if notify:
        return notify
    worker_data = get_object_or_404(WorkerData, pk=pk)
    date = request.GET.get("date")
    if date:
        cur_date = datetime.strptime(date, '%Y-%m-%d').date()
    else:
        cur_date = datetime.now().date()
    prev = cur_date - relativedelta(months=1)
    next = cur_date + relativedelta(months=1)
    start = cur_date.replace(day=1)
    end = start
    while end.month == start.month:
        end += relativedelta(days=1)
    end -= relativedelta(days=1)
    completed_products = CreationInstance.objects.filter(
        status="COMPLETED", completed__gte=start, completed__lte=end, worker=worker_data)
    payment = worker_data.get_payment(start, end)
    completed_amount = worker_data.get_completed(start, end)
    if request.method == "POST":
        if 'delete_user' in request.POST:
            worker = worker_data.worker
            worker_data.worker = None
            worker_data.save()
            worker.delete()
            return HttpResponseRedirect('/workspace/workers_list')
    products_in_work = CreationInstance.objects.filter(
        worker=worker_data).filter(status__in=['IN_WORK', 'QUEUED'])
    context = {
        'worker': worker_data,
        'products': completed_products,
        'payment': payment,
        'completed_amount': completed_amount,
        'in_work': products_in_work,
        'current_date': cur_date,
        'prev': prev,
        'next': next
    }
    return render(request, 'worker_detail.html', context)


@login_required
def questions_list(request):
    """
    **view** для вкладки ***Вопросы***

    Получает из **БД**:
    - ***Question*** с полем ***answer***=""

    Работает с шаблоном ***questions_list.html***
    """
    # Проверяем группу пользователя
    # Для ограничения доступа
    if check_user_group(request, "master") is False:
        return HttpResponseRedirect('/workspace')
    # Обновляем уведомления (работает только если пришёл запрос на обновление уведомлений)
    notify = update_notification(request)
    if notify:
        return notify
    # Получаем все вопросы, на которые не был дан ответ
    questions = Question.objects.filter(answer="")
    # Создаём словарь с данными для шаблона
    context = {
        'questions': questions,
    }
    # Возвращаем заполненный шаблон
    return render(request, 'questions_list.html', context)


@login_required
def instance_details(request, pk):
    if check_user_group(request, "master") is False:
        return HttpResponseRedirect('/workspace')
    notify = update_notification(request)
    if notify:
        return notify
    instance = get_object_or_404(CreationInstance, pk=pk)
    form = None
    if request.method == "GET":
        if 'question' in request.GET:
            question_id = request.GET["question"]
            if Question.objects.filter(instance=instance, id=question_id).exists():
                form = EnterAnswerForm(
                    initial={'answer': Question.objects.filter(instance=instance, id=question_id).first().answer})
            else:
                return HttpResponseForbidden('Такого вопроса не существует')
    else:
        question_id = request.GET["question"]
        if Question.objects.filter(instance=instance, id=question_id).exists():
            form = EnterAnswerForm(request.POST)
            if form.is_valid():
                answer = form.cleaned_data["answer"]
                question = Question.objects.filter(
                    instance=instance, id=question_id).first()
                question.answer = answer
                question.save()
        else:
            return HttpResponseForbidden('Такого вопроса не существует')
    questions = Question.objects.filter(instance=instance).all()
    context = {
        'instance': instance,
        'questions': questions,
        'form': form
    }
    return render(request, 'instance_detail.html', context)


@login_required
def migrate_view(request):
    if check_user_group(request, "master") is False:
        return HttpResponseRedirect('/workspace')
    notify = update_notification(request)
    if notify:
        return notify
    context = dict()
    # Получаем все вопросы, на которые не был дан ответ
    questions = Question.objects.filter(answer='')
    # Сохраняем кол-во вопросов в словарь данных для шаблона
    context['questions'] = len(questions)
    if request.method == "GET":
        form = SelectFileForm()
        context['form'] = form
    elif request.method == "POST":
        form = SelectFileForm(request.POST, request.FILES)
        if form.is_valid():
            # Получаем файл из запроса
            spec = request.FILES.get("spec")
            # deadline = form.cleaned_data["deadline"]
            # Считываем данные из файла
            spec_data = pd.read_excel(
                spec, header=None, sheet_name="Спецификация")
            spec_format = xl.load_workbook(spec, read_only=True)
            sheet = spec_format['Спецификация']
            if check_spec(spec_data, spec_format) is False:
                raise ValidationError(
                    "Спецификафия не соответствует формату")
            obj_number = spec.name.split()[0]
            # Парсим данные из спецификации
            prod_data = dict()
            parts = dict()
            row_idx = 10
            header = ''
            part_head = ''
            prod_price = Decimal(0.00)
            prod_amount = 0
            pay = 0
            part_price = Decimal(0.00)
            part_amount = Decimal(1.00)
            max_idx = 0
            unique_idx = 0
            skip = False
            blacklisted = False
            while pd.notna(spec_data.iloc[row_idx, 1]):
                cell = sheet[rc_to_a1(row_idx+1, 2)]
                if cell.fill and cell.fill.start_color.rgb == "FF33CCFF":
                    if cell.font and cell.font.bold:
                        if part_head != '':
                            payment = ((part_price / part_amount) /
                                       prod_price) * pay
                            parts[unique_idx] = {
                                'price': payment.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'amount': part_amount, 'name': part_head}
                            unique_idx += 1
                        if blacklisted:
                            parts = dict()
                            blacklisted = False
                        if header != '':
                            if ', ' in header or ' - ' in header:
                                list = header.split(', ')
                                idx = 1
                                for part in list:
                                    if ' - ' in part:
                                        start = part.split(" - ")[0]
                                        end = part.split(" - ")[1]
                                        deleted = ''
                                        sym = start[0]
                                        while sym.lower() in ALPHABET:
                                            deleted += sym
                                            start = start.replace(sym, '', 1)
                                            sym = start[0]
                                        if '.' in end:
                                            dec_places = len(end.split('.')[1])
                                        else:
                                            dec_places = 0
                                        end = end.replace(deleted, '', 1)
                                        start = Decimal(start)
                                        end = Decimal(end)
                                        step = Decimal(1) / pow(10, dec_places)
                                        while start <= end:
                                            prod_data[unique_idx] = {
                                                'parts': parts.copy(), 'price': pay, 'name': deleted + f'{start}', 'amount': 1, 'number': (len(str(prod_amount)) - len(str(idx))) * "0" + str(idx)}
                                            unique_idx += 1
                                            start += step
                                            idx += 1
                                    else:
                                        prod_data[unique_idx] = {
                                            'parts': parts.copy(), 'price': pay, 'name': part, 'amount': 1, 'number': (len(str(prod_amount)) - len(str(idx))) * "0" + str(idx)}
                                        unique_idx += 1
                                        idx += 1
                            else:
                                prod_data[unique_idx] = {
                                    'parts': parts.copy(), 'price': pay, 'name': header, 'amount': prod_amount}
                                unique_idx += 1
                        if spec_data.iloc[row_idx, 12] > 0:
                            header = spec_data.iloc[row_idx, 1]
                            prod_amount = int(spec_data.iloc[row_idx, 8])
                            prod_price = Decimal(spec_data.iloc[row_idx, 11])
                            pay = int(
                                spec_data.iloc[row_idx, 14] // spec_data.iloc[row_idx, 8])
                            parts = dict()
                            part_head = ''
                            part_price = Decimal(0.00)
                            part_amount = Decimal(1.00)
                            max_idx += 1
                            skip = False
                        else:
                            skip = True
                    else:
                        if any(fnmatch(spec_data.iloc[row_idx, 1], pattern.value) for pattern in ParseBlacklistValue.objects.all()) or skip:
                            if not skip:
                                blacklisted = True
                            row_idx += 1
                            continue
                        if part_head != '':
                            payment = ((part_price / part_amount) /
                                       prod_price) * pay
                            parts[unique_idx] = {
                                'price': payment.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'amount': part_amount, 'name': part_head}
                            unique_idx += 1
                        part_head = spec_data.iloc[row_idx, 1]
                        if pd.notna(spec_data.iloc[row_idx, 7]):
                            part_amount = Decimal(
                                spec_data.iloc[row_idx, 7])
                        part_price = Decimal(0.00)
                else:
                    if not skip:
                        part_price += Decimal(spec_data.iloc[row_idx, 11])
                row_idx += 1
            if part_head != '' and not skip:
                payment = ((part_price / part_amount) / prod_price) * pay
                parts[unique_idx] = {
                    'price': payment.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'amount': part_amount, 'name': part_head}
                unique_idx += 1
            if (', ' in header or ' - ' in header) and not skip:
                if blacklisted:
                    parts = dict()
                list = header.split(', ')
                idx = 1
                for part in list:
                    if ' - ' in part:
                        start = part.split(" - ")[0]
                        end = part.split(" - ")[1]
                        deleted = ''
                        sym = start[0]
                        while sym.lower() in ALPHABET:
                            deleted += sym
                            start = start.replace(sym, '', 1)
                            sym = start[0]
                        if '.' in end:
                            dec_places = len(end.split('.')[1])
                        else:
                            dec_places = 0
                        end = end.replace(deleted, '', 1)
                        start = Decimal(start)
                        end = Decimal(end)
                        step = Decimal(1) / pow(10, dec_places)
                        while start <= end:
                            prod_data[unique_idx] = {
                                'parts': parts.copy(), 'price': pay, 'name': deleted + f'{start}', 'amount': 1, 'number': (len(str(prod_amount)) - len(str(idx))) * "0" + str(idx)}
                            unique_idx += 1
                            start += step
                            idx += 1
                    else:
                        prod_data[unique_idx] = {
                            'parts': parts.copy(), 'price': pay, 'name': part, 'amount': 1, 'number': (len(str(prod_amount)) - len(str(idx))) * "0" + str(idx)}
                        unique_idx += 1
                        idx += 1
            elif not skip:
                if blacklisted:
                    parts = dict()
                prod_data[unique_idx] = {
                    'parts': parts.copy(), 'price': pay, 'name': header, 'amount': prod_amount}
                unique_idx += 1
            idx = 1
            lst_number = 0
            for key in prod_data:
                if prod_data[key].get('number') == None:
                    if lst_number != 0:
                        idx += 1
                        lst_number = 0
                    prod_data[key]['number'] = (
                        len(str(max_idx)) - len(str(idx))) * '0' + str(idx)
                    idx += 1
                else:
                    if Decimal(lst_number) > Decimal(prod_data[key].get('number')):
                        idx += 1
                    lst_number = prod_data[key].get('number')
                    prod_data[key]['number'] = (
                        len(str(max_idx)) - len(str(idx))) * '0' + str(idx) + '-' + lst_number
            # Добавляем записи в базу данных
            obj = Object.objects.create(obj_number=obj_number, created_at=timezone.now(
            ).date())
            ObjectStateInstance.objects.create(
                object=obj, state=get_default_object_state(), created_at=timezone.now())
            for key in prod_data:
                data = prod_data.get(key)
                prod = Product.objects.create(prod_number=data.get('number'), object=obj, name=data.get(
                    'name'), amount=data.get('amount'), price=data.get('price'))
                parts_data = data.get('parts')
                for part_key in parts_data:
                    part_data = parts_data.get(part_key)
                    Part.objects.create(
                        name=part_data.get('name'), product=prod, price=part_data.get('price'))
            context['products'] = prod_data
            context['object'] = obj
    return render(request, "migrate.html", context)


# @login_required
# def migrate_view(request):
#     check_user_group(request, "master", True)
#     context = dict()
#     if request.method == "GET":
#         form = SelectFileForm()
#         context['form'] = form
#     elif request.method == "POST":
#         form = SelectFileForm(request.POST, request.FILES)
#         if form.is_valid():
#             # Получаем файлы из запроса
#             summary = request.FILES.get("summary")
#             spec = request.FILES.get("spec")
#             all_data = request.FILES.get("all")
#             if summary and spec:
#                 # Считываем данные из файлов
#                 sum_data = pd.read_excel(
#                     summary, header=None, sheet_name="Сводная спецификация")
#                 spec_data = pd.read_excel(
#                     spec, header=None, sheet_name="Спецификация")
#                 spec_format = xl.load_workbook(spec, read_only=True)
#                 sheet = spec_format['Спецификация']
#             elif all_data:
#                 sum_data = pd.read_excel(
#                     all_data, header=None, sheet_name="Сводная")
#                 spec_data = pd.read_excel(
#                     all_data, header=None, sheet_name="Спецификация")
#                 spec_format = xl.load_workbook(all_data, read_only=True)
#                 sheet = spec_format['Спецификация']
#             else:
#                 raise ValidationError(
#                     'Должны быть выбраны файлы Сводной и Спецификации ИЛИ общий файл')
#             # Проверяем форматы и правильное расположение столбцов в файлах
#             if check_summary(sum_data) is False:
#                 raise ValidationError("Сводная не соответствует формату")
#             if check_spec(spec_data, spec_format) is False:
#                 raise ValidationError(
#                     "Спецификафия не соответствует формату")
#             # Проверяем, что в обоих файлах указан один объект
#             obj_number = sum_data.iloc[0, 3]
#             if summary and spec:
#                 if obj_number not in summary.name:
#                     raise ValidationError(
#                         "Неправильно указан объект в Сводной")
#                 if obj_number not in spec.name:
#                     raise ValidationError(
#                         "Указанный в Спецификации объект отличается от указанного в Сводной")
#             # Парсим данные из Сводной
#             products = dict()
#             row_idx = 4
#             while pd.notna(sum_data.iloc[row_idx, 1]):
#                 prod_number = sum_data.iloc[row_idx, 1].replace(
#                     f'{obj_number}-', '', 1)
#                 prod_name = sum_data.iloc[row_idx, 2]
#                 prod_amount = sum_data.iloc[row_idx, 3]
#                 products[prod_number] = {
#                     'name': prod_name, 'amount': prod_amount}
#                 row_idx += 1
#             row_idx += 3
#             isAva = True
#             while pd.notna(sum_data.iloc[row_idx, 2]):
#                 if pd.notna(sum_data.iloc[row_idx, 14]):
#                     if sum_data.iloc[row_idx, 14] > 0:
#                         isAva = False
#                 else:
#                     isAva = False
#                 row_idx += 1
#             # Парсим данные из спецификации
#             prod_data = dict()
#             parts = dict()
#             row_idx = 10
#             header = ''
#             part_head = ''
#             prod_price = 0
#             pay = 0
#             part_price = 0
#             part_amount = 1
#             while pd.notna(spec_data.iloc[row_idx, 1]):
#                 cell = sheet[rc_to_a1(row_idx+1, 2)]
#                 if cell.fill and cell.fill.start_color.rgb == "FF33CCFF":
#                     if cell.font and cell.font.bold:
#                         if part_head != '':
#                             payment = ((part_price / part_amount) /
#                                        prod_price) * pay
#                             parts[part_head] = {
#                                 'price': int(payment), 'amount': part_amount, 'name': part_head}
#                         if header != '':
#                             prod_data[header] = {
#                                 'parts': parts.copy(), 'price': int(pay)}
#                         header = spec_data.iloc[row_idx, 1]
#                         prod_price = spec_data.iloc[row_idx, 11]
#                         pay = spec_data.iloc[row_idx,
#                                              14] // spec_data.iloc[row_idx, 8]
#                         parts = dict()
#                         part_head = ''
#                         part_price = 0
#                         part_amount = 1
#                     else:
#                         if any(forbidden in spec_data.iloc[row_idx, 1] for forbidden in PARSING_BLACKLIST):
#                             row_idx += 1
#                             continue
#                         if part_head != '':
#                             payment = ((part_price / part_amount) /
#                                        prod_price) * pay
#                             parts[part_head] = {
#                                 'price': int(payment), 'amount': part_amount, 'name': part_head}
#                         part_head = spec_data.iloc[row_idx, 1]
#                         if pd.notna(spec_data.iloc[row_idx, 7]):
#                             part_amount = spec_data.iloc[row_idx, 7]
#                         part_price = 0
#                 else:
#                     part_price += spec_data.iloc[row_idx, 11]
#                 row_idx += 1
#             if part_head != '':
#                 payment = ((part_price / part_amount) / prod_price) * pay
#                 parts[part_head] = {
#                     'price': int(payment), 'amount': part_amount, 'name': part_head}
#             prod_data[header] = {
#                 'parts': parts.copy(), 'price': int(pay)}
#             # Объединяем данные
#             for key in products:
#                 data = products.get(key)
#                 name = data.get('name')
#                 products[key]['id'] = key
#                 products[key]['parts'] = prod_data.get(name).get('parts')
#                 products[key]['price'] = prod_data.get(name).get('price')
#             # Добавляем записи в базу данных
#             obj = Object.objects.create(obj_number=obj_number, created_at=timezone.now(
#             ).date(), deadline=(timezone.now() + timedelta(days=30)).date())
#             if isAva:
#                 ObjectStateInstance.objects.create(object=obj, state=ObjectState.objects.filter(
#                     name="Закуплен").first(), created_at=timezone.now().date())
#             for key in products:
#                 data = products.get(key)
#                 prod = Product.objects.create(prod_number=key, object=obj, name=data.get(
#                     'name'), amount=data.get('amount'), price=data.get('price'))
#                 parts_data = data.get('parts')
#                 for part_key in parts_data:
#                     part_data = parts_data.get(part_key)
#                     Part.objects.create(
#                         name=part_key, product=prod, price=part_data.get('price'))
#             context['products'] = products
#             context['object'] = obj

#     return render(request, "migrate.html", context)

@login_required
def queued_details(request, pk):
    if check_user_group(request, "worker") is False:
        return HttpResponseRedirect('/workspace')
    notify = update_notification(request)
    if notify:
        return notify
    worker = check_worker_data(request)
    instance = get_object_or_404(CreationInstance, pk=pk)
    if instance.worker != worker:
        return HttpResponseRedirect("/workspace")
    context = {'instance': instance}
    if request.method == "POST" and 'claim_product' in request.POST:
        in_work = CreationInstance.objects.filter(
            worker=worker, product=instance.product, part=instance.part, status='IN_WORK').first()
        if in_work:
            in_work.amount += instance.amount
            in_work.save()
            instance.delete()
        else:
            instance.status = "IN_WORK"
            instance.queued = None
            instance.started = timezone.now().date()
            instance.save()
        return HttpResponseRedirect('/workspace')
    return render(request, "queued.html", context)


@login_required
def hidden_view(request):
    """
    **view** для вкладки ***Скрытые***

    Получает из **БД**:
    - ***Object*** с полем ***hidden***=**True**
    - ***Question*** с полем ***answer***=""

    Работает с шаблонами ***master.html***, ***partials/objects_table.html***
    """
    # Проверяем группу пользователя
    # Для ограничения доступа
    if check_user_group(request, "master") is False:
        return HttpResponseRedirect('/workspace')
    # Обновляем уведомления (работает только если пришёл запрос на обновление уведомлений)
    notify = update_notification(request)
    if notify:
        return notify
    # Получаем все скрытые объекты
    objects = Object.objects.filter(hidden=True)
    # Получаем все вопросы, на которые не был дан ответ
    questions = Question.objects.filter(answer='')
    # Получаем из запроса Поисковый запрос
    search_query = request.GET.get('search', '')
    # Если что-то было введено в поиск
    if search_query:
        # Оставляем только подходящие по номеру объекты
        objects = objects.filter(obj_number__icontains=search_query)
    # Создаём словарь с нужными данными
    context = {'objects': objects, 'hidden': True, 'questions': len(questions)}
    # Если пришёл запрос на динамическое обновление страницы
    # (Приходит после ввода в поисковое поле ИЛИ через определённый промежуток времени)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Возвращаем специальный шаблон, который будет включен в страницу
        return render(request, 'partials/objects_table.html', context)
    # Возвращаем заполненный шаблон страницы
    return render(request, 'master.html', context)


@login_required
def blacklist_settings_view(request):
    if check_user_group(request, "master") is False:
        return HttpResponseRedirect('/workspace')
    notify = update_notification(request)
    if notify:
        return notify
    blacklist = ParseBlacklistValue.objects.all()
    context = dict()
    # Получаем все вопросы, на которые не был дан ответ
    questions = Question.objects.filter(answer='')
    # Сохраняем кол-во вопросов в словарь данных для шаблона
    context['questions'] = len(questions)
    if request.method == "POST":
        if 'add_value' in request.POST:
            form = AddParseBlacklistValueForm(request.POST)
            if form.is_valid():
                value = form.cleaned_data["blacklist_value"]
                if value in blacklist:
                    form.add_error("blacklist_value",
                                   f"Маска {value} уже содержится в списке!")
                    context = {
                        "blacklist": blacklist,
                        "form": form,
                        'questions': len(questions),
                    }
                    return render(request, 'blacklist_settings.html', context)
                ParseBlacklistValue.objects.create(value=value)
                blacklist = ParseBlacklistValue.objects.all()
            context['form'] = form
        if 'delete' in request.POST:
            ParseBlacklistValue.objects.filter(
                id=request.POST.get('delete')).first().delete()
            blacklist = ParseBlacklistValue.objects.all()
            form = AddParseBlacklistValueForm()
            context['form'] = form
    else:
        form = AddParseBlacklistValueForm()
        context['form'] = form
    context['blacklist'] = blacklist
    return render(request, 'blacklist_settings.html', context)
