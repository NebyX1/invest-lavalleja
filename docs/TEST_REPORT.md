# Reporte de verificación — Invest Lavalleja

Fecha de cierre: 2026-09-21

## Resultado

| Comprobación | Resultado |
| --- | --- |
| `npm run check` | 0 errores, 0 warnings, 0 hints |
| `npm run lint` | OK |
| `npm run test` | 2 archivos, 4 pruebas, 4 pasaron |
| `npm run build` | OK; 30 rutas editoriales + 404 + robots |
| `npm run test:e2e` | 13 pasaron y 1 captura móvil omitida intencionalmente |
| `npm run test:e2e:preview` | 13 pasaron y 1 captura móvil omitida intencionalmente contra `astro preview` |
| axe sobre `/recursos/` | Sin violaciones |
| PDF local | Responde HTTP 200 en la prueba E2E |

## Flujos cubiertos

- Las rutas del manifiesto responden con contenido propio y título esperado.
- La navegación interna conserva `performance.timeOrigin` y un marcador de ventana, señal de navegación cliente sin recarga completa.
- Guardar “Minas y su entorno” persiste entre navegación y recarga.
- El buscador global abre con Ctrl+K, filtra “UNESCO” y navega a `/fuentes/`.
- El asistente conserva actividad, etapa y necesidad en la sesión.
- El menú móvil abre y cierra mediante el botón accesible.
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
- El atlas es esquemático y no representa coordenadas ni disponibilidad inmobiliaria.
- El dossier exporta Markdown y usa la impresión del navegador; no se presenta como generación PDF del producto.
- La instalación local informa una advertencia de engine porque `undici@8.10.2` declara Node `>=22.19.0` y el entorno de validación usa Node `22.15.1`. `npm install` también reporta dos vulnerabilidades moderadas del árbol de dependencias; no se ejecutó un `npm audit fix --force` por el riesgo de cambios no solicitados.
