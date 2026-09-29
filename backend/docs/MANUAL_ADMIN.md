# Manual del panel

## Una regla fácil de recordar

**Cargar no publica. Editar no publica. Indexar tampoco publica.** Solo el propietario cambia la versión visible con una acción expresa de publicación.

## Acceso

Entrar con correo y contraseña. Una cuenta TOTP nueva debe registrar el QR en su aplicación autenticadora y comprobar un código. Guardar los códigos de recuperación: se muestran una sola vez y cada uno se consume al usarlo. Las cuentas configuradas por correo reciben un código temporal, siempre que el servidor SMTP esté correctamente preparado.

El propietario administra cuentas y puede publicar, retirar, volver atrás o borrar bases. El editor administra documentos, revisión e indexación. El rol de consulta puede inspeccionar el panel y exportar el corpus, que puede contener material interno: asignarlo únicamente a personal autorizado. No existe un rol de “lector público” del admin.

Las operaciones críticas exigen verificación reciente. Si aparece el formulario de reconfirmación, introducir contraseña y segundo factor. Un TOTP ya usado se rechaza, incluso dentro de sus mismos 30 segundos: esperar el siguiente código. Al reconfirmar, repetir la acción administrativa deseada; no se ejecutan formularios antiguos automáticamente.

En Seguridad se puede cambiar contraseña y cerrar otras sesiones. Los cambios de contraseña revocan sesiones. La recuperación excepcional de una cuenta sin segundo factor exige un operador con acceso a la consola del servidor; no un enlace público.

## Cargar una guía

Abrir Bases, escribir un nombre y elegir un archivo. Para la guía incluida, usar `invest_lavalleja_2026.gianna.json`. El JSON lleva texto y fuentes, no vectores. Los JSONL completos también se aceptan; no confundirlos con una lista de textos sin metadatos.

La carga crea un trabajo. En su pantalla aparecen estado y mensajes de progreso; actualizar los detalles al terminar para abrir el borrador. Si falla, leer el error antes de reintentar. El límite inicial es 12 MiB por carga y 10.000 registros por base, ajustable por entorno.

Los DOCX desconocidos, Markdown y TXT entran como internos para revisión. El perfil de la guía suministrada conserva su separación editorial original. No admite PDF, imágenes, archivos comprimidos genéricos ni documentos con macros. No se realiza OCR.

## Revisar y editar

La base permite buscar por texto y filtrar tema, audiencia y revisión. Abrir un registro para leer texto completo, fecha de corte, período, referencias y condiciones. Se puede editar o deshabilitar; para publicar solo se seleccionan registros públicos, habilitados y aprobados.

Las condiciones son piezas separadas por una línea `---` en el editor. Conservar allí las restricciones necesarias para no recuperar una oportunidad sin sus límites. Las fuentes tienen un editor propio; cambiar una fuente reinicia la aprobación para que no se herede una revisión anterior.

La aprobación masiva de registros públicos exige confirmar la revisión. No certifica automáticamente que una norma siga vigente, que un teléfono atienda o que una oportunidad sea rentable. Los registros internos no pasan al índice público por estar aprobados o en la misma base.

Las modificaciones solo afectan al borrador. Una versión ya indexada contiene su propia instantánea. Para reflejar cambios hay que construir y publicar otra versión.

## Crear el índice

Pulsar la acción de crear versión. El sistema toma una instantánea del contenido público aprobado, tokeniza con E5, corta fragmentos respetando el presupuesto configurado, genera vectores densos y BM25 y carga una colección privada Qdrant.

El trabajo muestra progreso y verifica la cantidad final de puntos. El modelo se carga una vez por proceso y los embeddings idénticos se reutilizan por huella. Los textos cambiados se vuelven a calcular. Un reintento mantiene identificadores estables y no duplica puntos.

La cancelación es cooperativa: se comprueba entre etapas/lotes, no detiene una operación nativa ni una descarga a mitad de una instrucción. Los trabajos interrumpidos se recuperan cuando vence su lease y vuelve el trabajador. No apagar repetidamente para “acelerar”.

Al finalizar, la versión queda lista para probar, no publicada. Si falla, la versión pública anterior permanece seleccionada.

## Explorar los chunks

Cada versión muestra perfil del modelo, huella, revisión, tamaño y lista de fragmentos. Buscar un tema o título, abrir contenido y revisar el conteo real de tokens. El texto indexado incluye prefijo `passage:`, título y metadatos de contexto.

El mapa 2D usa PCA sobre los vectores reales y como máximo 1.200 fragmentos. Seleccionar puntos para inspeccionarlos. La reducción a dos dimensiones puede acercar o separar textos artificialmente: no utilizar el dibujo para afirmar que una respuesta es correcta o para reemplazar las pruebas de recuperación.

## Probar antes de publicar

El laboratorio permite recuperar evidencia y conversar contra una versión concreta sin hacerla pública. No permite seleccionar material interno como fuente del chat. Las consultas de prueba pueden usar la API de pago; la prueba de recuperación no necesita generar una respuesta con Ollama.

Para esta guía, cargar las 62 preguntas de `pruebas_recuperacion.json`. El resultado indica si se recuperó alguno de los registros esperados. Ese indicador **no mide exactitud de la redacción**, cobertura de todos los aspectos ni validez jurídica. Complementarlo con las 12 situaciones de revisión humana y preguntas propias.

Comprobar especialmente que no se mezclen puntos con porcentajes; propuestas con servicios operativos; estadísticas con ejemplos hipotéticos; reconocimiento territorial con permisos por padrón. Probar una pregunta sin respuesta en la guía y una instrucción para revelar información interna.

## Publicar, volver atrás y borrar

El propietario confirma las pruebas y publica con segundo factor reciente. La nueva versión pasa a ser la única activa para nuevas consultas. El cambio del puntero se guarda en una transacción SQLite. No se anuncia como una transacción distribuida entre SQLite y Qdrant.

Para volver atrás, elegir una versión previamente publicada. Las versiones quedan preservadas hasta borrar su base. No se puede publicar una versión obsoleta frente al borrador actual como si reflejara las últimas ediciones, salvo el flujo explícito de retorno a una versión previamente publicada.

Antes de borrar una base, publicar otra o retirar la actual. El sistema exige escribir su nombre y bloquea el borrado de la base activa. La eliminación se procesa en cola y borra sus colecciones y contenido asociado. No es una acción reversible mediante un botón; exportar y respaldar antes. Esta RC no tiene borrado individual de versiones ni papelería recuperable de colecciones.

Al cambiar de versión o borrar una base anterior, evitar hacerlo durante conversaciones o pruebas en curso. El índice activo se captura por consulta, pero no hay un sistema de leases de lectura que conserve indefinidamente versiones retiradas para peticiones en vuelo.

## Analítica y personalización

Analítica muestra consultas, sesiones anónimas, latencias p50/p95, errores, abstenciones, feedback y tokens que informa el proveedor. Las sesiones no son personas únicas; los temas se derivan del contenido recuperado, no de una clasificación infalible de intención. Los datos comienzan vacíos en una instalación nueva. Los screenshots entregados usan datos sintéticos de presentación, no tráfico real.

Ajustes permite editar identidad textual, saludo, tono, aviso, modelo de Ollama, temperatura, salida, candidatos, contexto, fragmentos, límites y retención. Los cambios de fragmentación afectan versiones nuevas, no rehacen silenciosamente la activa. No hay personalizador visual de colores o logotipos; esa adaptación se hace en CSS y plantillas.

El panel muestra si el token existe, nunca su valor. Guardar una configuración no comprueba que una credencial sea válida; utilizar el catálogo y realizar una prueba real. No escribir contraseñas, tokens o documentos privados dentro de las instrucciones editoriales.
