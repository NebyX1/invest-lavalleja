"""Render the actual access email with a synthetic code, without SMTP or .env."""
import argparse
from email.policy import SMTP
from pathlib import Path

from gianna.mail import access_code_email
from gianna.security import EMAIL_OTP_TTL_SECONDS


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('reports/email/preview'))
    output = parser.parse_args(argv).output_dir
    output.mkdir(parents=True, exist_ok=True)
    message = access_code_email('Gianna <gianna@example.test>', 'preview@example.test', '012345',
                                expires_minutes=EMAIL_OTP_TTL_SECONDS // 60)
    for subtype, suffix in (('plain', 'txt'), ('html', 'html')):
        output.joinpath('access-code.' + suffix).write_text(
            message.get_body(preferencelist=(subtype,)).get_content(), encoding='utf-8', newline='\n')
    output.joinpath('access-code.eml').write_bytes(message.as_bytes(policy=SMTP))
    print(f'Synthetic email preview: {output.resolve()} (no SMTP connection or real recipient).')


if __name__ == '__main__':
    main()
