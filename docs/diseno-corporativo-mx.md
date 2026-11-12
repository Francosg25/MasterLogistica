# Sistema visual de MasterLogistica · México

El producto se organiza como una mesa de trabajo documental: un índice de masters, hojas editables y consultas financieras. La navegación es horizontal y el lienzo utiliza el ancho completo. Los registros y los archivos que el usuario necesita abrir determinan la jerarquía. Los saldos aparecen al pie como contexto de consulta.

## Fundamentos

| Función | Valor |
| --- | --- |
| Superficie principal | `#FFFFFF` |
| Superficies secundarias | `#F5F5F7` |
| Texto principal | `#1D1D1F` |
| Texto secundario | `#6E6E73` |
| Metadatos y etiquetas sutiles | `#86868B` |
| Acción primaria y enlaces | `#0071E3` |
| Hover primario | `#0077ED` |
| Borde de contenedor | `1px solid rgba(0,0,0,.06)` |
| Sombra ambiental | `0 4px 24px rgba(0,0,0,.04)` |
| Navegación y cabeceras superpuestas | Blanco al 72 %, desenfoque 20 px, saturación 180 % |
| Radio de contenedores | 16–20 px |
| Acciones y filtros | Radio 9999 px |

La tipografía utiliza la pila de sistema `-apple-system`, `BlinkMacSystemFont`, `SF Pro Display`, `Inter`, `Segoe UI`, `sans-serif`, sin descargar fuentes ni distribuir archivos propietarios. Los títulos usan peso 600, interlineado 1.1 y tracking -0.025em. Los textos de lectura mantienen interlineado 1.5 y ancho máximo de 65ch.

El color de marca se reserva para acciones y enlaces, con el mismo azul como señal de foco y selección de celdas. Los estados ordinarios se distinguen mediante texto y superficies neutras; los errores y confirmaciones conservan su función semántica. El foco de teclado permanece visible. Se respetan las preferencias de movimiento reducido, contraste alto y, donde el navegador lo admite, transparencia reducida.

## Pantallas

- **Inicio:** lista de masters por responsable con búsqueda, apertura directa y una segunda vista para referencias recientes. Las columnas se cuentan y se describen a partir del catálogo real. La estructura particular de la hoja acompaña a su nombre. El último master abierto se identifica durante la sesión.
- **Navegación:** pestañas de texto en una barra horizontal translúcida. El menú móvil se despliega bajo la barra; Escape y el cierre exterior devuelven el foco al control de navegación. La búsqueda global conserva Ctrl + K.
- **Masters:** aprovecha el ancho disponible para la hoja y mantiene controles compactos. Conserva edición de celdas, teclado, pegado y columnas de cada responsable de la versión publicada.
- **Provisiones y facturas:** consultas de ancho completo con filtros en gris suave, cifras alineadas y tablas continuas. Los formularios conservan superficies elevadas y mayor separación entre campos.
- **Consolidación:** archivo, revisión y confirmación dentro de una superficie de trabajo continua. Mantiene la carga XLSX real y las validaciones existentes.
- **Ficha, búsqueda y formularios:** superficies elevadas, radios continuos, cabeceras translúcidas y mayor separación entre grupos de campos.

El pie del índice presenta los saldos por moneda, el mes consultado y los pendientes del alcance autorizado. Los datos provienen del resumen existente; abrir un master utiliza el flujo real de consulta y recuerda la selección del usuario.

## Código y compatibilidad

`frontend/src/styles.css` es la entrada estable de estilos y se mantiene como única entrada en Angular. Importa `base.css`, `workspace.css` y `design-system.css`, en ese orden. El último archivo define la identidad visual. La estructura de navegación está en `app.component.html`; `workspace-home.component` presenta el índice y solicita la apertura del master. El catálogo y la lista de responsables se comparten desde la aplicación, sin añadir peticiones por cada hoja. No cambia dependencias ni locks de Node/Python, migraciones, permisos ni reglas de aplicación financiera. El diseño es adaptable a escritorio y móvil; la hoja mantiene desplazamiento dentro de la tabla.

La entrada única permite que un servidor local ya abierto reciba el diseño mediante su archivo CSS conocido. Se reprodujo el caso de Angular CLI 21.2.27 conservando las opciones iniciales al cambiar `angular.json`: las plantillas nuevas aparecían con los estilos básicos anteriores. Incorporar las capas por importaciones en la entrada existente recuperó el diseño en el mismo servidor. La prueba de regresión utiliza el arranque normal y el servicio de acceso real configurado para desarrollo, con respuestas API sintéticas.

La comprobación visual utiliza datos sintéticos de las pruebas del proyecto. Las capturas no contienen operaciones reales.

## Capturas verificadas

| Pantalla | Captura |
| --- | --- |
| Inicio | [Índice de masters](../frontend/docs/home-preview.png) |
| Master | [Hoja editable en escritorio](../frontend/docs/masters-preview.png) |
| Provisiones | [Saldos y registros](../frontend/docs/finance-preview.png) |
| Captura | [Nueva provisión](../frontend/docs/provision-date-preview.png) |
| Facturas | [Lista de facturas](../frontend/docs/invoices-simple-preview.png) |
| Consolidación | [Revisión del Excel](../frontend/docs/invoice-import-preview.png) |
| Ficha | [Familia de referencias](../frontend/docs/reference-activity-preview.png) |
| Móvil | [Inicio adaptable](../frontend/docs/mobile-preview.png) |

## Verificación de esta entrega

El conjunto de navegador contiene 67 casos: 40 de masters, 19 de finanzas, 3 de navegación del espacio de trabajo, 4 de acceso/demostración y 1 de actualización de estilos en una sesión local abierta. Comprueba la búsqueda del master y su apertura directa con teclado, el menú móvil con Escape, captura, edición, pegado, guardado, consultas financieras y aislamiento de los datos de práctica. Las pruebas de densidad conservan más de la mitad de la ventana para las filas del master a 1920 × 1080, 1366 × 768 y 1280 × 600, con la primera fila antes de los 240 px. En facturas, la primera fila permanece antes de los 260 px a 1366 × 768.

Los casos de interfaz utilizan respuestas simuladas y datos de demostración. Esta comprobación visual no sustituye las pruebas de integración de base de datos o de acceso corporativo.

Desde `frontend/`:

```sh
npm run build
npx tsc --noEmit -p tsconfig.e2e.json
npx playwright test
```

`CHROMIUM_PATH` permite utilizar un Chromium ya disponible en el entorno de pruebas, sin cambiar las dependencias de la aplicación.
