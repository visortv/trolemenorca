MENORCA BUS V10 - TODAS LAS LINEAS

ARRANQUE
-------
Ejecuta INICIAR_WINDOWS.bat

Antes de abrir la web:
1. Descubre las líneas desde https://www.tmsa.es/transporte-regular
2. Lee OPERATIVA / NO OPERATIVA.
3. Lee cada página de línea y sus sentidos/paradas.
4. Lee el recurso de horarios publicado por TMSA.
5. Reconstruye las matrices parada x expedición.
6. Guarda TODO en data_snapshot.json.
7. Sólo entonces arranca http://127.0.0.1:5055/

La web consulta el snapshot local, no TMSA en cada clic.

FLUJO
-----
Fecha
-> población origen
-> sólo poblaciones destino viables
-> todas las paradas de salida viables
-> horas disponibles (incluye línea)
-> todas las paradas de llegada de esa misma expedición
-> hora real de llegada

Nunca muestra "hora pendiente": una llegada sin hora concreta no se ofrece.

DIAGNÓSTICO
-----------
http://127.0.0.1:5055/api/snapshot

Ahí puedes ver para cada línea:
- operativa/no operativa
- número de sentidos
- número de bloques horarios
- error de sincronización si lo hubiera

Puerto fijo: 5055.
