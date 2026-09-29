# Checklist de aceptación en el servidor destino

Esta lista contiene trabajo real pendiente. No marcarla como cumplida por haber descargado el ZIP.

## Construcción y acceso

- Resolver dependencias directas/transitivas y ejecutar pruebas en Python 3.12; comprobar también 3.13 si se utiliza. Ejecutar la revisión de vulnerabilidades y corregir hallazgos antes de publicar.
- Construir la imagen Docker sin credenciales como argumentos, subir ambos servicios y verificar volúmenes persistentes, HTTPS, hosts y orígenes.
- Crear la primera cuenta por consola. Probar TOTP, código erróneo, código reutilizado, recuperación, revocación y bloqueo de cuenta. Probar el método de correo solo con SMTP validado.
- Confirmar que una cuenta de consulta no edita, un editor no publica y una sesión anónima no accede al admin. Comprobar CSRF y cierre de sesión por POST.

## Datos e indexación

- Importar el JSON canónico. Confirmar 271 registros y 50 fuentes; revisar la separación 196/75 antes de aprobar.
- Comprobar descarga de E5, 384 dimensiones, pooling y normalización, prefijos y tokenización. Revisar que ningún chunk indexado supere el límite.
- Guardar la revisión resuelta en `E5_REVISION` y repetir carga/reinicio sin cambios inesperados de huella.
- Confirmar que Qdrant contiene exclusivamente contenido público aprobado y los puntos coinciden con la versión SQLite.
- Interrumpir una construcción en un entorno de prueba, reiniciar, reintentar y verificar que no duplica puntos ni cambia la versión activa. Confirmar cancelación entre lotes.

## Recuperación y generación

- Ejecutar las 62 preguntas y registrar resultados reales. El umbral de aceptación lo fija el equipo con evidencia; no hay un porcentaje precalculado de acierto.
- Configurar Ollama y completar las 12 situaciones de revisión humana. Comprobar referencias, fecha, condiciones, rechazo de premisas falsas y abstención cuando corresponda.
- Probar continuidad de conversación, pregunta fuera de tema, inyección de instrucciones, intento de usar el anexo interno, mensaje excesivo y límite de uso.
- Validar errores al apagar Qdrant o simular fallo del proveedor: sin inventar respuesta, sin publicar borradores y sin filtrar secretos.

## Administración y capacidad

- Publicar una versión; editar el borrador y comprobar que no cambia el chat. Construir otra, publicar y volver a la anterior. Borrar una base inactiva solo fuera de conversaciones en curso.
- Probar desktop/móvil con Flask real, navegación y formularios; las capturas de esta entrega no sustituyen estos recorridos.
- Medir carga en reposo, pico al cargar el modelo, indexación y 1/3 conversaciones concurrentes. Registrar memoria, CPU, p50/p95, tiempo de respuesta y errores. Ajustar límites sin sobreasignar el VPS.
- Probar copia y restauración en otra instancia con las claves correctas. Confirmar que la restauración revoca sesiones y exige revalidar/publicar el índice.
- Verificar aviso de privacidad, retención y canales de consulta institucional antes de abrir el servicio.

Solo después de completar estas comprobaciones corresponde etiquetar una versión de producción. Registrar fecha, commit, imagen, dependencias, huella del modelo, versión del corpus, resultados y responsable.
