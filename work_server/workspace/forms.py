from django import forms
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.contrib.auth.forms import UserCreationForm
from decimal import Decimal, ROUND_HALF_UP


class TakeProductToWorkForm(forms.Form):

    def __init__(self, *args, **kwargs):
        choices = kwargs.pop('choices')
        super().__init__(*args, **kwargs)
        self.fields['creation'].choices = choices

    amount = forms.DecimalField(
        min_value=Decimal('0.1'), label='Кол-во', decimal_places=1, max_digits=10)

    creation = forms.ChoiceField(label='Изготовить')

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        return amount

    def clean_creation(self):
        creation = self.cleaned_data['creation']
        return creation


class EnterQuestionForm(forms.Form):

    question = forms.CharField(
        min_length=1, max_length=1024, strip=True, label="Ваш вопрос")

    def clean_question(self):
        question = self.cleaned_data['question']
        return question


# class AddStateForm(forms.Form):

#     def __init__(self, *args, **kwargs):
#         choices = kwargs.pop('choices')
#         super().__init__(*args, **kwargs)
#         self.fields['state'].choices = choices

#     state = forms.ChoiceField(label='Состояние')

#     created_at = forms.DateField(
#         label="Дата добавления состояния", widget=forms.DateInput(attrs={'type': 'date'}))

#     def clean_state(self):
#         state = self.cleaned_data["state"]
#         return state

#     def clean_created_at(self):
#         created_at = self.cleaned_data["created_at"]
#         return created_at


class SelectPeriodForm(forms.Form):

    start = forms.DateField(
        label="От", widget=forms.DateInput(attrs={'type': 'date'}))
    end = forms.DateField(
        label="До", widget=forms.DateInput(attrs={'type': 'date'}))

    def clean_start(self):
        start = self.cleaned_data["start"]
        return start

    def clean_end(self):
        end = self.cleaned_data["end"]

        if end < self.clean_start():
            raise ValidationError(
                f'Конечная дата ({end}) периода не может располагаться раньше начальной ({self.clean_start()})')
        return end


class EnterDescriptionForm(forms.Form):

    description = forms.CharField(
        min_length=1, max_length=8096, strip=True, label="Примечание", required=False)

    def clean_description(self):
        description = self.cleaned_data['description']
        return description


class EnterAnswerForm(forms.Form):

    answer = forms.CharField(
        min_length=1, max_length=2048, strip=True, label="Ответ")

    def clean_answer(self):
        answer = self.cleaned_data['answer']
        return answer


# class SelectFileForm(forms.Form):

#     summary = forms.FileField(label="Выберите файл Сводной", validators=[
#         FileExtensionValidator(allowed_extensions=['xls', 'xlsx', 'xlsm'])], widget=forms.FileInput(attrs={'accept': '.xls, .xlsx, .xlsm'}), required=False)
#     spec = forms.FileField(label="Выберите файл Спецификации", validators=[
#         FileExtensionValidator(allowed_extensions=['xls', 'xlsx', 'xlsm'])], widget=forms.FileInput(attrs={'accept': '.xls, .xlsx, .xlsm'}), required=False)
#     all = forms.FileField(label="Выберите общий файл", validators=[
#         FileExtensionValidator(allowed_extensions=['xls', 'xlsx', 'xlsm'])], widget=forms.FileInput(attrs={'accept': '.xls, .xlsx, .xlsm'}), required=False)


class SelectFileForm(forms.Form):

    spec = forms.FileField(label="Выберите файл Спецификации", validators=[
        FileExtensionValidator(allowed_extensions=['xls', 'xlsx', 'xlsm'])], widget=forms.FileInput(attrs={'accept': '.xls, .xlsx, .xlsm', 'title': 'Выберите Спецификацию'}))
    # deadline = forms.DateField(
    #     label="Дата сдачи объекта", widget=forms.DateInput(attrs={'type': 'date'}))

    # def clean_deadline(self):
    #     deadline = self.cleaned_data["deadline"]
    #     return deadline


class AddProductToQueueForm(forms.Form):

    def __init__(self, *args, **kwargs):
        choices = kwargs.pop('choices')
        super().__init__(*args, **kwargs)
        self.fields['creation'].choices = choices
        group = Group.objects.get(name='worker')
        self.fields['worker'] = forms.ModelChoiceField(
            queryset=group.user_set.all(),
            label="Работник"
        )

    creation = forms.ChoiceField(label='Изготовить')

    amount = forms.DecimalField(
        min_value=Decimal('0.1'), label='Кол-во', decimal_places=1, max_digits=10)

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        return amount

    def clean_creation(self):
        creation = self.cleaned_data['creation']
        return creation

    def clean_worker(self):
        worker = self.cleaned_data['worker']
        return worker


class CustomUserCreationForm(UserCreationForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['username'].label = "Логин"
        self.fields['password1'].label = "Пароль"
        self.fields['password2'].label = "Повтор пароля"

        self.fields['username'].help_text = "Латиница, цифры и @/./+/-/_"
        self.fields['password1'].help_text = "Минимум 8 символов, достаточно сложный"
        self.fields['password2'].help_text = "Введите пароль ещё раз для проверки"

    display_name = forms.CharField(max_length=256, label="Отображаемое имя",
                                   help_text="Введите имя, под которым будет виден пользователь")

    def clean_display_name(self):
        display_name = self.cleaned_data["display_name"]
        return display_name


class AddParseBlacklistValueForm(forms.Form):

    blacklist_value = forms.CharField(max_length=256, label="Игнорируемое значение",
                                      help_text="Укажите в данном поле маску, которая должна игнорироваться (пр. *Маска ?.*)")

    def clean_blacklist_value(self):
        blacklist_value = self.cleaned_data["blacklist_value"]
        return blacklist_value
