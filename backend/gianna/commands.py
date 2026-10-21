"""Console account management, including the Buzón Ciudadano CLI syntax."""
import click
from .security import PASSWORDS,validate_password
from .db import IntegrityError
from .errors import DomainError


def register_commands(app):
    @app.cli.command('create-admin')
    @click.argument('name',required=False)
    @click.argument('email',required=False)
    @click.argument('password',required=False)
    @click.argument('is_superuser',required=False,type=click.Choice(['true','false'],case_sensitive=False))
    @click.option('--email','email_option',help='Correo para el modo interactivo anterior.')
    @click.option('--name','name_option',help='Nombre para el modo interactivo anterior.')
    @click.option('--mfa',type=click.Choice(['totp','email']),default='totp',show_default=True,
                  help='Método de doble factor; email requiere SMTP configurado.')
    def create_admin(name,email,password,is_superuser,email_option,name_option,mfa):
        """Crear una cuenta: NOMBRE CORREO CONTRASEÑA [true|false].

        true crea un superadministrador (owner); false u omitirlo crea un
        administrador (editor). Sin argumentos, conserva el alta interactiva
        anterior de un superadministrador, con contraseña oculta.
        """
        positional=any(value is not None for value in (name,email,password,is_superuser))
        if positional:
            if email_option is not None or name_option is not None:
                raise click.UsageError('No mezcles argumentos posicionales con --email o --name.')
            if name is None or email is None or password is None:
                raise click.UsageError('Indicá NOMBRE CORREO CONTRASEÑA [true|false], o no uses argumentos para el modo interactivo.')
            role='owner' if is_superuser=='true' else 'editor'
        else:
            email=email_option if email_option is not None else click.prompt('Correo del administrador')
            name=name_option if name_option is not None else click.prompt('Nombre')
            password=click.prompt('Contraseña',hide_input=True,confirmation_prompt=True)
            role='owner'
        name=name.strip()
        if not name or len(name)>100:
            raise click.ClickException('Usá un nombre de entre 1 y 100 caracteres.')
        s=app.extensions['gianna']
        try:id=s.security.create_user(email,name,password,role,mfa)
        except DomainError as exc:raise click.ClickException(str(exc)) from exc
        except IntegrityError as exc:raise click.ClickException('Ya existe una cuenta con ese correo.') from exc
        s.db.audit(id,'OWNER_CREATED_BY_CONSOLE' if role=='owner' else 'ADMIN_CREATED_BY_CONSOLE',
                   details={'role':role,'mfa_method':mfa})
        label='Superadministrador' if role=='owner' else 'Administrador'
        if mfa=='email':
            click.echo(f'{label} creado. Entrá en /admin/login; el código se enviará por correo.')
        else:
            click.echo(f'{label} creado. Entrá en /admin/login y configurá tu aplicación autenticadora.')

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
        click.echo('Configuración válida. MariaDB accesible; no se imprimen secretos.')
        click.echo('Ollama token: '+('configurado' if s.cfg.ollama_api_key else 'pendiente'))
