# Reporte de verificación — Invest Lavalleja

Fecha de cierre: 2026-09-28

## Resultado

| Comprobación | Resultado |
| --- | --- |
| `npm run check` | 0 errores, 0 warnings, 0 hints |
| `npm run lint` | OK |
| `npm run test` | 2 archivos, 5 pruebas, 5 pasaron |
| `npm run build` | OK; 30 rutas editoriales + 404 + robots |
| `npm run test:e2e` | 19 pasaron y 1 captura móvil omitida intencionalmente |
| Suite E2E contra `astro preview` compilado | 19 pasaron y 1 captura móvil omitida intencionalmente; el wrapper `npm run test:e2e:preview` termina con código 13 en Windows después de iniciar el servidor |
| axe sobre `/recursos/` y el explorador territorial | Sin violaciones |
| PDF local | HTTP 200, `application/pdf` y descarga verificada con nombre original |

## Flujos cubiertos

- Las rutas del manifiesto responden con contenido propio y título esperado.
- La navegación interna conserva `performance.timeOrigin` y un marcador de ventana, señal de navegación cliente sin recarga completa.
- Guardar “Minas y su entorno” persiste entre navegación y recarga.
- El buscador global abre con Ctrl+K, filtra “UNESCO” y navega a `/fuentes/`.
- El asistente conserva actividad, etapa y necesidad en la sesión.
- El menú móvil abre y cierra mediante el botón accesible.
- El mapa SVG conserva su proporción, permite seleccionar sus seis localidades y sincroniza el perfil mostrado; los siete perfiles siguen disponibles desde la lista.
- El explorador apila mapa, detalle y lista en móvil sin desbordamiento horizontal; sus controles cumplen el análisis axe.
- El asistente conserva ancho legible y pasos sin superposición en 1920, 1366, 1024, 768 y 390 px.
- Las islas esperan hidratación antes de leer estado persistido; el primer render permanece estable con SSR.

## Capturas

Playwright generó estas capturas en `reports/captures/`:

- `home-1440.png`
- `menu-mobile-390.png`
- `sector-turismo.png`
- `zona-minas.png`
- `explorer.png`
- `search-dialog.png`
- `dossier.png`
- `project-wizard.png`

## Limitaciones conocidas

- La preproducción usa `noindex` hasta configurar `PUBLIC_SITE_URL` y `PUBLIC_INDEXING=true`.
- Los seis puntos se toman del esquema SVG, no de georreferenciación; el mapa no representa límites administrativos, parcelas ni disponibilidad inmobiliaria. Dos perfiles agregados sin punto en el SVG permanecen accesibles desde la lista.
- El dossier exporta Markdown y usa la impresión del navegador; no se presenta como generación PDF del producto.
- La instalación local informa una advertencia de engine porque `undici@8.10.2` declara Node `>=22.19.0` y el entorno de validación usa Node `22.15.1`. `npm install` también reporta dos vulnerabilidades moderadas del árbol de dependencias; no se ejecutó un `npm audit fix --force` por el riesgo de cambios no solicitados.
