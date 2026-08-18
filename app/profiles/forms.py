from django import forms

from .models import Education, Employment, Skill


class EmploymentForm(forms.ModelForm):
    class Meta:
        model = Employment

        fields = [
            "organization",
            "position",
            "start_date",
            "end_date",
            "is_current",
            "description",
        ]

        widgets = {
            "start_date": forms.DateInput(
                attrs={"type": "date"}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date"}
            ),
        }


class EducationForm(forms.ModelForm):
    class Meta:
        model = Education

        fields = [
            "institution",
            "degree",
            "field_of_study",
            "start_year",
            "end_year",
            "description",
        ]


class SkillForm(forms.ModelForm):
    class Meta:
        model = Skill

        fields = [
            "name",
            "description",
        ]