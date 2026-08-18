from django import forms

from .models import HelpOffer


class HelpOfferForm(forms.ModelForm):
    class Meta:
        model = HelpOffer

        fields = [
            "title",
            "category",
            "description",
            "is_active",
        ]