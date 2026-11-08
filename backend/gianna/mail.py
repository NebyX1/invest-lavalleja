"""Transactional email composition, independent of Flask and SMTP connections."""
from email.message import EmailMessage

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape


_templates = Environment(
    loader=PackageLoader('gianna', 'templates/emails'),
    autoescape=select_autoescape(['html']),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def access_code_email(sender, recipient, code, *, expires_minutes):
    values = {'code': code, 'expires_minutes': expires_minutes}
    message = EmailMessage()
    message['Subject'] = 'Tu código de acceso a Gianna'
    message['From'] = sender
    message['To'] = recipient
    message.set_content(_templates.get_template('access_code.txt').render(**values))
    message.add_alternative(_templates.get_template('access_code.html').render(**values), subtype='html')
    return message
