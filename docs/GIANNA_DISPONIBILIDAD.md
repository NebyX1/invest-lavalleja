# Disponibilidad de Gianna — 07/11/2026

La isla conserva el contrato de CAPTCHA, sesiones, chat y citas. Los únicos cambios
afectan la disponibilidad y los errores temporales del conocimiento.

`GET /api/config` mantiene `enabled`/`available` y puede agregar:

```json
{
  "enabled": true,
  "available": false,
  "knowledge_state": "restoring_index",
  "knowledge_code": "index_missing",
  "knowledge_message": "Recuperando el índice de conocimiento."
}
```

Estados: `initializing`, `restoring_models`, `restoring_index`, `ready`, `no_knowledge`,
`failed`. Los campos nuevos son opcionales para admitir backends anteriores. No se
interpretan rutas internas ni se exponen credenciales. El servidor es quien decide
si el modelo y la colección están preparados; habilitar el chat requiere ambos
booleanos. `knowledge_message` se muestra como texto, sin HTML.

La configuración se vuelve a consultar cada 5 s durante indisponibilidad, 30 s cuando
está lista y 15 s tras un fallo de conexión. Cada petición tiene un plazo de 10 s;
se cancelan peticiones y timers al desmontar la isla. No se recarga la página ni se
borra la conversación para detectar una recuperación.

Un 503 estructurado por dependencia de conocimiento deshabilita temporalmente el
formulario y adelanta la consulta de configuración. La pregunta permanece escrita
para que la persona pueda reenviarla cuando termine la recuperación. No se reenvía
automáticamente ni se consumen otra vez la sesión o el CAPTCHA. Los errores del
proveedor conservan su tratamiento separado.

Validación local: Astro check sin errores/advertencias, ESLint correcto, build estática
correcta, Vitest **9/9** y **16 pruebas Playwright aprobadas** en escritorio y móvil.
Dos pruebas nuevas cubren los estados de restauración y un índice perdido después de
habilitar el chat. El contrato HTTP se simula en estas pruebas del frontend; la
restauración con MariaDB, LanceDB y ONNX reales se prueba en el backend institucional.

En producción conservar `PUBLIC_GIANNA_API_BASE=https://mapi.invest.lavalleja.uy`
y el origen permitido correspondiente. La reparación del índice y la persistencia
se realizan en el backend; el frontend no modifica publicaciones. No se desplegó
este cambio ni se modificó la configuración productiva desde esta validación.
