"""Console-only bootstrap and emergency recovery. Passwords are never CLI arguments."""
import click
from .security import PASSWORDS,validate_password
from .db import uid


def register_commands(app):
    @app.cli.command('create-admin')
    @click.option('--email',prompt='Correo del administrador')
    @click.option('--name',prompt='Nombre')
    @click.option('--mfa',type=click.Choice(['totp','email']),default='totp',show_default=True,
                  help='Método de doble factor; email requiere SMTP configurado.')
    def create_admin(email,name,mfa):
        password=click.prompt('Contraseña',hide_input=True,confirmation_prompt=True)
        s=app.extensions['gianna']
        try:id=s.security.create_user(email,name,password,'owner',mfa)
        except Exception as exc:raise click.ClickException(str(exc)) from exc
        s.db.audit(id,'OWNER_CREATED_BY_CONSOLE')
        if mfa=='email':
            click.echo('Administrador creado. Entrá en /admin/login; el código se enviará por correo.')
        else:
            click.echo('Administrador creado. Entrá en /admin/login y configurá tu aplicación autenticadora.')

    @app.cli.command('reset-admin')
    @click.option('--email',prompt='Correo del administrador')
    @click.confirmation_option(prompt='¿Restablecer contraseña y segundo factor, revocando todas las sesiones de esta cuenta?')
    def reset_admin(email):
        password=click.prompt('Nueva contraseña',hide_input=True,confirmation_prompt=True)
        s=app.extensions['gianna'];validate_password(password)
        row=s.db.one('SELECT id,mfa_method FROM users WHERE email=?',(email.strip().lower(),))
        if not row:raise click.ClickException('La cuenta no existe.')
        with s.db.tx(immediate=True) as db:
            db.execute("UPDATE users SET password_hash=?,mfa_enrolled=CASE WHEN mfa_method='email' THEN 1 ELSE 0 END,totp_secret=NULL,totp_last_step=-1,active=1 WHERE id=?",(PASSWORDS.hash(password),row['id']))
            for table in ('admin_sessions','recovery_codes','auth_challenges'):db.execute(f'DELETE FROM {table} WHERE user_id=?',(row['id'],))
        s.db.audit(row['id'],'OWNER_CONSOLE_ACCOUNT_RESET')
        click.echo('Cuenta restablecida. El segundo factor configurado seguirá siendo obligatorio.')

    @app.cli.command('check-config')
    def check_config():
        s=app.extensions['gianna']
        click.echo('Configuración válida. SQLite accesible. No se imprimen secretos.')
        click.echo('Ollama token: '+('configurado' if s.cfg.ollama_api_key else 'pendiente'))
